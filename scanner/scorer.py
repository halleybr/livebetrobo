"""LIVE PRESSURE SCORE (0–100) + classificação de oportunidade.

O score é calculado SOMENTE com dados reais disponíveis:

  * probabilidades do modelo RoboBet (over_05/15/25, BTTS, escanteios);
  * ritmo da partida (gols por minuto projetados);
  * bandeiras de momentum ao vivo (hasFire, hasBall, justScored, cartões);
  * estatísticas ao vivo do SokkerPRO quando acessíveis (xG, chutes, ataques
    perigosos, escanteios reais, barra de pressão, ataques por minuto).

Estrutura do score:
  * goals_component  (0–100): potencial de gols no restante da partida;
  * corners_component(0–100): potencial de escanteios;
  * momentum_component(0–100): ritmo/pressão geral da partida;
  * LPS = eixo dominante (max) com leve reforço do outro eixo + ajuste de
    momentum. Um jogo quente em gols mas frio em escanteios NÃO é penalizado
    como se fosse um jogo morno — e vice-versa.

Regras:
  * nunca inventar dado — sinal ausente é ignorado (vira N/D na interface);
  * dados parciais sofrem um desconto de confiança (availability);
  * partidas com LPS < 70 são filtradas na interface (filtrar antes de entrar).
"""

from __future__ import annotations

from typing import Optional

# Limiar mínimo para classificar o tipo de oportunidade.
GOALS_MIN = 55
CORNERS_MIN = 55

# Quanto as estatísticas ao vivo pesam quando estão disponíveis.
# Para escanteios o modelo RoboBet pesa um pouco mais (a contagem real de
# escanteios costuma ser esparsa; as probabilidades capturam o fluxo).
STATS_BLEND = 0.50
STATS_BLEND_CORNERS = 0.40


def _norm(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Normaliza um valor no intervalo [lo, hi] para [0, 1]. None se ausente."""
    if value is None:
        return None
    if hi <= lo:
        return None
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _norm_scaled(value: Optional[float], lo: float, hi: float, factor: float) -> Optional[float]:
    """Normaliza e aplica um fator de maturidade (None permanece None)."""
    n = _norm(value, lo, hi)
    return None if n is None else n * factor


def _weighted(weighted_signals: list[tuple[float, Optional[float]]]) -> tuple[float, float]:
    """Média ponderada sobre sinais disponíveis.

    Retorna (score 0..1, fração de peso disponível).
    """
    used_w = 0.0
    acc = 0.0
    for w, v in weighted_signals:
        if v is None:
            continue
        used_w += w
        acc += w * _clip01(v)
    if used_w <= 0:
        return 0.0, 0.0
    return acc / used_w, used_w


def _total_weight(weighted_signals: list[tuple[float, Optional[float]]]) -> float:
    return sum(w for w, _ in weighted_signals)


def _goals_so_far(m: dict) -> int:
    return int(m.get("home_score") or 0) + int(m.get("away_score") or 0)


def _minute(m: dict) -> float:
    try:
        return max(1.0, float(m.get("minute")))
    except (TypeError, ValueError):
        return 1.0


def _goal_pace(m: dict) -> Optional[float]:
    """Gols projetados aos 90' com base no ritmo atual."""
    return _goals_so_far(m) / _minute(m) * 90.0


def _corner_window_prob(m: dict) -> Optional[float]:
    """Probabilidade do modelo de escanteio na janela de 10 min mais próxima.

    A janela 35'-45' (h1) só vale como pressão "agora" quando a partida já
    passou do início; a janela 80'-90' (h2) só vale perto do fim. Em minutos
    iniciais esses números são previsões triviais do jogo inteiro, não pressão
    ao vivo — por isso retornamos None.
    """
    minute = _minute(m)
    if minute < 25:
        return None
    if minute < 60:
        return m.get("corners_next10_h1")
    return m.get("corners_next10_h2")


def _blend(model_score: float, model_avail: float, live_signals: list, total_w: float) -> tuple[float, float]:
    """Combina o score do modelo RoboBet com estatísticas ao vivo (SokkerPRO).

    Quando as estatísticas ao vivo estão disponíveis, elas têm peso
    STATS_BLEND — xG, chutes e ataques perigosos são a evidência mais forte
    de pressão.
    """
    if live_signals:
        live_score, live_used = _weighted(live_signals)
        score = (1.0 - STATS_BLEND) * model_score + STATS_BLEND * live_score
        used = (1.0 - STATS_BLEND) * model_avail + STATS_BLEND * live_used
    else:
        score, used = model_score, model_avail
    availability = used / total_w if total_w else 0.0
    # Desconto conservador para dados parciais.
    score *= 0.5 + 0.5 * availability
    return round(_clip01(score) * 100, 1), availability


def _creation_pace(m: dict) -> Optional[float]:
    """Ritmo de criação de gol: usa xG quando disponível, senão gols marcados.

    Um 0x0 com muito xG é um jogo de pressão — o ritmo não deve penalizá-lo
    por ainda não ter convertido.
    """
    xg_pace = None
    if m.get("xg_home") is not None and m.get("xg_away") is not None:
        xg_pace = (m["xg_home"] + m["xg_away"]) / _minute(m) * 90.0
    scored_pace = _goal_pace(m)
    if xg_pace is not None:
        return max(xg_pace, scored_pace or 0.0)
    return scored_pace


def goals_component(m: dict) -> tuple[float, float]:
    """Componente de potencial de GOLS (0..100) + fração de dados disponível."""
    minute = _minute(m)
    # Minutos iniciais ainda não definem ritmo — amortece o sinal de pace.
    maturity = min(1.0, minute / 25.0)

    signals: list[tuple[float, Optional[float]]] = [
        (0.30, _norm(m.get("prob_over15_ft"), 50.0, 90.0)),   # gol no restante
        (0.10, _norm(m.get("prob_over05_ft"), 85.0, 98.0)),   # base de gol
        (0.15, _norm(m.get("prob_over25_ft"), 45.0, 85.0)),   # +2.5 no restante
        (0.15, _norm(m.get("prob_btts"), 35.0, 75.0)),        # jogo aberto
        (0.15, _norm(_creation_pace(m), 1.8, 3.2) * maturity), # ritmo de criação
        (0.10, 1.0 if m.get("just_scored") else 0.0),         # gol recente
        (0.05, 1.0 if m.get("has_fire") else 0.0),            # pressão constante
    ]
    total_w = _total_weight(signals)
    model_score, model_avail = _weighted(signals)

    live_signals: list[tuple[float, Optional[float]]] = []
    if m.get("shots") is not None:
        live_signals.append((0.35, _norm(m["shots"] / minute * 90.0, 12.0, 28.0)))
    if m.get("shots_on_target") is not None:
        live_signals.append((0.30, _norm(m["shots_on_target"] / minute * 90.0, 4.0, 11.0)))
    if m.get("dangerous_attacks") is not None:
        live_signals.append((0.20, _norm(m["dangerous_attacks"], 70.0, 130.0)))
    if m.get("big_chances") is not None:
        live_signals.append((0.15, _norm(m["big_chances"], 2.0, 7.0)))

    return _blend(model_score, model_avail, live_signals, total_w)


def corners_component(m: dict) -> tuple[float, float]:
    """Componente de potencial de ESCANTEIOS (0..100) + fração de dados."""
    minute = _minute(m)
    # Minutos iniciais: "total esperado" ainda é projeção pré-jogo, não pressão.
    maturity = min(1.0, minute / 30.0)
    signals: list[tuple[float, Optional[float]]] = [
        (0.35, _norm(_corner_window_prob(m), 25.0, 85.0)),    # escanteio agora
        (0.25, _norm_scaled(m.get("corners_expected_total"), 6.5, 10.5, maturity)),
        (0.10, _norm_scaled(m.get("corners_expected_ht"), 3.0, 5.5, maturity)),
        (0.15, 1.0 if (m.get("suggestion_market") or "").startswith("corners") else 0.0),
        (0.10, 1.0 if m.get("has_fire") else 0.0),            # pressão constante
        (0.05, 1.0 if m.get("has_ball") else 0.0),
    ]
    total_w = _total_weight(signals)
    model_score, model_avail = _weighted(signals)

    live_signals: list[tuple[float, Optional[float]]] = []
    minute = _minute(m)
    if m.get("corners") is not None:
        live_signals.append((0.50, _norm(m["corners"] / minute * 90.0, 5.0, 13.0)))
    if m.get("dangerous_attacks") is not None:
        live_signals.append((0.30, _norm(m["dangerous_attacks"], 70.0, 130.0)))
    if m.get("blocked_shots") is not None:
        live_signals.append((0.20, _norm(m["blocked_shots"], 2.0, 8.0)))

    if live_signals:
        live_score, live_used = _weighted(live_signals)
        score = (1.0 - STATS_BLEND_CORNERS) * model_score + STATS_BLEND_CORNERS * live_score
        used = (1.0 - STATS_BLEND_CORNERS) * model_avail + STATS_BLEND_CORNERS * live_used
        availability = used / total_w if total_w else 0.0
        score *= 0.5 + 0.5 * availability
        return round(_clip01(score) * 100, 1), availability
    return _blend(model_score, model_avail, [], total_w)


def momentum_component(m: dict) -> tuple[float, float]:
    """Componente de momentum/ritmo da partida (0..100) + fração de dados."""
    score_diff = abs((m.get("home_score") or 0) - (m.get("away_score") or 0))
    minute = _minute(m)
    red_any = bool(m.get("red_card_home") or m.get("red_card_away"))

    signals: list[tuple[float, Optional[float]]] = [
        (0.20, 1.0 if m.get("has_fire") else 0.0),             # pressão constante
        (0.15, 1.0 if m.get("just_scored") else 0.0),          # gol recente
        (0.10, 1.0 if red_any else 0.0),                       # jogo mais aberto
        (0.15, 1.0 if score_diff <= 1 else 0.0),               # placar equilibrado
        (0.10, 1.0 if m.get("period") == "2T" and minute >= 60 else 0.0),
        (0.05, 1.0 if m.get("has_ball") else 0.0),
    ]
    total_w = _total_weight(signals)

    minute = _minute(m)
    if m.get("dangerous_attacks") is not None:
        signals.append((0.15, _norm(m["dangerous_attacks"], 70.0, 130.0)))
    if m.get("xg_home") is not None and m.get("xg_away") is not None:
        xg_pace = (m["xg_home"] + m["xg_away"]) / minute * 90.0
        signals.append((0.10, _norm(xg_pace, 1.5, 3.2)))
    if m.get("possession_home") is not None:
        # Posse equilibrada (40-60%) sugere jogo aberto e disputado.
        balance = 1.0 - abs(m["possession_home"] - 50.0) / 50.0
        signals.append((0.05, balance))
    if m.get("dapm_total") is not None:
        # Ataques perigosos nos últimos 10 min (por minuto) — pressão recente.
        signals.append((0.15, _norm(m["dapm_total"], 0.6, 2.2)))
    if m.get("pressure_bar_home") is not None or m.get("pressure_bar_away") is not None:
        bars = [
            v for v in (m.get("pressure_bar_home"), m.get("pressure_bar_away"))
            if v is not None
        ]
        signals.append((0.10, _norm(sum(bars) / len(bars), 35.0, 75.0)))

    score, used = _weighted(signals)
    availability = used / total_w if total_w else 0.0
    score *= 0.5 + 0.5 * availability
    return round(_clip01(score) * 100, 1), availability


# ---------------------------------------------------------------------------
# Score final + classificação
# ---------------------------------------------------------------------------

def live_pressure_score(m: dict) -> dict:
    """Calcula o LPS e classifica o tipo de oportunidade. Nunca muta `m`."""
    g_comp, g_avail = goals_component(m)
    c_comp, c_avail = corners_component(m)
    mom_comp, mom_avail = momentum_component(m)

    # Eixo dominante carrega o score; o outro eixo reforça proporcionalmente;
    # momentum ajusta dentro de uma faixa.
    dom = max(g_comp, c_comp)
    low = min(g_comp, c_comp)
    balance = low / dom if dom > 0 else 0.0
    lps = dom * (0.88 + 0.12 * balance) + (mom_comp - 50.0) * 0.20

    has_stats = m.get("stats_source") == "robobet+sokkerpro"
    if not has_stats:
        # Sem estatísticas ao vivo confirmadas (xG, chutes, escanteios reais),
        # o score baseado só no modelo recebe desconto de confiança: ainda pode
        # aparecer como interessante, mas dificilmente como "muito forte".
        lps *= 0.82
    lps = round(max(0.0, min(100.0, lps)), 1)

    goals_active = g_comp >= GOALS_MIN
    corners_active = c_comp >= CORNERS_MIN

    if goals_active and corners_active:
        entry_type = "both"
    elif goals_active:
        entry_type = "goals"
    elif corners_active:
        entry_type = "corners"
    else:
        entry_type = "none"

    # ---- Mercado sugerido (apenas quando há oportunidade)
    market = None
    if goals_active:
        p_over05 = m.get("prob_over05_ft")
        p_over15 = m.get("prob_over15_ft")
        if p_over05 is not None and p_over05 >= 90:
            market = "Over 0.5 gol"
        elif p_over15 is not None and p_over15 >= 70:
            market = "Over 1.5 gols"
        else:
            market = "Próximo gol"

    corner_market = None
    if corners_active:
        if (m.get("suggestion_market") or "").startswith("corners"):
            corner_market = f"Over {m.get('suggestion_label')} escanteios"
        else:
            corner_market = "Over de escanteios (total)"

    # ---- Confiança estatística
    confidence = _confidence(m, g_comp, c_comp)

    # ---- Tier
    if lps >= 80:
        tier = "muito_forte"
    elif lps >= 70:
        tier = "interessante"
    elif lps >= 60:
        tier = "observar"
    else:
        tier = "ignorar"

    basis = "robobet+sokkerpro" if has_stats else "robobet"

    return {
        "lps": lps,
        "tier": tier,
        "goals_component": g_comp,
        "corners_component": c_comp,
        "momentum_component": mom_comp,
        "entry_type": entry_type,
        "market": market,
        "corner_market": corner_market,
        "confidence": confidence,
        "data_availability": round((g_avail + c_avail + mom_avail) / 3.0, 2),
        "basis": basis,
        "goal_pace_proj": round(_goal_pace(m), 2) if m.get("minute") else None,
    }


def _confidence(m: dict, g_comp: float, c_comp: float) -> str:
    """Alta / Média / Baixa, baseado nas probabilidades que sustentam a entrada."""
    levels = []
    if g_comp >= GOALS_MIN:
        p = m.get("prob_over15_ft")
        if p is not None and p >= 80:
            levels.append(2)
        elif p is not None and p >= 65:
            levels.append(1)
        else:
            levels.append(0)
    if c_comp >= CORNERS_MIN:
        p = _corner_window_prob(m)
        sp = m.get("suggestion_prob")
        if (p is not None and p >= 80) or (sp is not None and sp >= 80):
            levels.append(2)
        elif (p is not None and p >= 60) or (sp is not None and sp >= 65):
            levels.append(1)
        else:
            levels.append(0)

    if not levels:
        return "Baixa"

    best = max(levels)

    # Corroboração das estatísticas ao vivo do SokkerPRO eleva um nível.
    live_confirms = (
        (m.get("shots") or 0) >= 14
        or (m.get("dangerous_attacks") or 0) >= 90
        or ((m.get("xg_home") or 0) + (m.get("xg_away") or 0)) >= 2.0
    )
    if live_confirms and best < 2:
        best += 1

    if best >= 2:
        return "Alta"
    if best == 1:
        return "Média"
    return "Baixa"


def classify(m: dict) -> dict:
    """Junta estatísticas + score em um único dict pronto para a API."""
    result = live_pressure_score(m)
    return {**m, **result}
