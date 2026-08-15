"""Cliente da API pública do RoboBet (https://m.robobet.app/api).

Somente o endpoint público /api/events/today é usado. Ele já entrega, para cada
partida ao vivo: minuto, período, placar, odds 1X2, bandeiras de momentum
(hasFire/hasBall/justScored/cartões) e as probabilidades do modelo da própria
plataforma para mercados de gols (over_05/15/25, BTTS) e escanteios
(total esperado e janelas de 10 min).

Nota: campos premium (live_stats, superiority, xG bruto etc.) são criptografados
e removidos pela própria plataforma para contas gratuitas — não tentamos
contornar isso. O que não vier no payload público é tratado como N/D.
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

BASE_URL = "https://m.robobet.app/api"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Cria um contexto SSL que usa os certificados do sistema.
def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


def _get_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_today(timeout: int = 20) -> Optional[dict]:
    """Baixa a lista de eventos do dia. Retorna dict bruto ou None em falha."""
    try:
        return _get_json(f"{BASE_URL}/events/today", timeout=timeout)
    except Exception:
        return None


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _prob(market: Optional[dict]) -> Optional[float]:
    """Extrai a probabilidade (%) de um submercado, se existir."""
    if not market or not isinstance(market, dict):
        return None
    p = market.get("probability")
    return _num(p)


def extract_live_matches(payload: Optional[dict]) -> list[dict]:
    """Normaliza o payload de /events/today em uma lista de partidas ao vivo.

    Cada item mantém apenas campos públicos, já com tipos limpos e valores
    opcionais como None (que o frontend exibe como N/D).
    """
    if not payload or not isinstance(payload.get("leagues"), list):
        return []

    matches: list[dict] = []
    for league in payload["leagues"]:
        league_name = league.get("name") or "N/D"
        for m in league.get("matches", []):
            if not m.get("isLive"):
                continue

            fg = m.get("forecast_data") or {}
            mkts = fg.get("markets") or {}
            og = mkts.get("over_goals") or {}
            cn = mkts.get("corners") or {}

            suggestion = m.get("best_suggestion") or {}
            if not isinstance(suggestion, dict):
                suggestion = {}

            matches.append(
                {
                    "id": m.get("id"),
                    "league": league_name,
                    "home": m.get("home"),
                    "away": m.get("away"),
                    "home_score": m.get("scoreHome"),
                    "away_score": m.get("scoreAway"),
                    "minute": m.get("minute"),
                    "injury_time_min": m.get("injury_time_min"),
                    "period": m.get("period"),
                    "time_label": m.get("time"),
                    "fixture_id": m.get("fi_id"),
                    "odds": m.get("odds"),
                    "has_fire": bool(m.get("hasFire")),
                    "has_ball": bool(m.get("hasBall")),
                    "just_scored": bool(m.get("justScored")),
                    "red_card_home": bool(m.get("redCardHome")),
                    "red_card_away": bool(m.get("redCardAway")),
                    "start_time": m.get("start_time"),
                    # ---- Probabilidades do modelo (dados reais, não inventados)
                    "prob_over05_ht": _prob(og.get("over_05_ht")),
                    "prob_over05_ft": _prob(og.get("over_05_ft")),
                    "prob_over15_ft": _prob(og.get("over_15_ft")),
                    "prob_over25_ft": _prob(og.get("over_25_ft")),
                    "prob_btts": _prob(og.get("btts")),
                    "corners_expected_total": _num(
                        (cn.get("match_total") or {}).get("value")
                    ),
                    "corners_expected_ht": _num((cn.get("ht_total") or {}).get("value")),
                    "corners_next10_h1": _prob(cn.get("c_match_35_45_prob")),
                    "corners_next10_h2": _prob(cn.get("c_match_80_90_prob")),
                    "suggestion_market": suggestion.get("market_type"),
                    "suggestion_label": suggestion.get("abbreviation"),
                    "suggestion_prob": _num(suggestion.get("probability")),
                    "suggestion_odd": suggestion.get("odd"),
                    # ---- Estatísticas ao vivo (preenchidas pelo SokkerPRO; None = N/D)
                    "xg_home": None,
                    "xg_away": None,
                    "shots": None,
                    "shots_on_target": None,
                    "dangerous_attacks": None,
                    "possession_home": None,
                    "corners": None,
                    "big_chances": None,
                    "fouls": None,
                    "yellow_cards": None,
                    "red_cards": None,
                    "blocked_shots": None,
                    "crosses": None,
                    "stats_updated_at": None,
                    # ---- Diagnóstico
                    "stats_source": "robobet",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    return matches
