"""Enriquecimento com estatísticas ao vivo do SokkerPRO (m2.sokkerpro.com).

O endpoint público `GET https://m2.sokkerpro.com/livescores` devolve, para
cada partida ao vivo, TODAS as estatísticas em um único JSON:
xG, finalizações (total/no gol/fora/área), escanteios, posse, ataques e
ataques perigosos, pressão (barra 0-100), ataques perigosos por minuto
(janelas 1/3/5/10 min), faltas, cartões, defesas e o placar.

Fluxo:
  1. Buscar `/livescores` uma vez por ciclo (1 chamada, todas as partidas).
  2. Casar cada partida do RoboBet com uma do SokkerPRO por nomes das equipes
     (tokens normalizados + confirmação do placar) — os ids de fixture são de
     espaços diferentes e não podem ser cruzados diretamente.
  3. Normalizar as estatísticas para os campos usados pelo scorer.
  4. Se não casar ou se a chamada falhar -> N/D (nunca inventar dado).
"""

from __future__ import annotations

import json
import re
import ssl
import unicodedata
import urllib.request
from typing import Any, Optional

BASE_URL = "https://m2.sokkerpro.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

FETCH_TIMEOUT = 15

# Status que contam como "ao vivo" no SokkerPRO.
LIVE_STATUSES = {"1st", "2nd", "HT", "ET", "PEN"}

# Tokens genéricos de nome de clube que não ajudam no casamento.
_NOISE_TOKENS = {
    "ec", "ca", "cd", "fc", "sc", "ac", "aa", "ad", "cr", "crc", "ge",
    "club", "clube", "de", "do", "da", "dos", "das", "the",
}

# Sinônimos pontuais para abreviações comuns (usados com confirmação de placar).
_SYNONYMS = {
    "pr": "paranaense",
    "ba": "bahia",   # "Vitória BA" == "EC Vitória"
}

# Ex.: "(W)", " W", "Femenil", "Women's" -> marcador feminino padronizado.
_W_RE = re.compile(r"\(w\)|\bw\b|women|womens|femenil|feminino|feminina|\(f\)|\(m\)")


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context()


def _get_json(url: str) -> Optional[Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Origin": "https://sokkerpro.com",
            "Referer": "https://sokkerpro.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT, context=_ssl_ctx()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_livescores() -> Optional[list[dict]]:
    """Busca todas as partidas ao vivo + estatísticas em uma única chamada."""
    try:
        data = _get_json(f"{BASE_URL}/livescores")
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
        return None
    fixtures: list[dict] = []
    for cat in data["data"].get("sortedCategorizedFixtures") or []:
        for f in cat.get("fixtures") or []:
            if f.get("status") in LIVE_STATUSES and (f.get("localTeamName") or f.get("visitorTeamName")):
                fixtures.append(f)
    return fixtures


def fetch_fixture(fixture_id: str) -> Optional[dict]:
    """Detalhe de uma partida (fallback para estatísticas por id)."""
    try:
        data = _get_json(f"{BASE_URL}/fixture/{fixture_id}")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Normalização de nomes (para casar RoboBet <-> SokkerPRO)
# ---------------------------------------------------------------------------

def normalize_team_name(name: Optional[str]) -> str:
    """Normaliza um nome de equipe para comparação por tokens."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode("utf-8", "ignore").lower()
    s = _W_RE.sub(" w ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    tokens = [t for t in s.split() if t not in _NOISE_TOKENS]
    tokens = [_SYNONYMS.get(t, t) for t in tokens]
    return " ".join(sorted(set(tokens)))


def _tokens(name: str) -> set[str]:
    return set(normalize_team_name(name).split())


def _names_match(name_a: Optional[str], name_b: Optional[str]) -> bool:
    """True se dois nomes representam a mesma equipe.

    Regra: contenção total de um lado OU Jaccard >= 0.5 entre os tokens.
    O placar (fora desta função) protege contra falsos positivos.
    """
    ta, tb = _tokens(name_a), _tokens(name_b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if ta <= tb or tb <= ta:
        return True
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and inter / union >= 0.5


def _score_of(fixture: dict, local: bool) -> Optional[int]:
    key = f"local{'' if local else 'Visitor'}TeamScore"  # nome alternativo
    if local:
        raw = fixture.get("scoresLocalTeam")
    else:
        raw = fixture.get("scoresVisitorTeam")
    if raw is None or raw == "":
        raw = fixture.get(key)
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def match_fixture(
    home: Optional[str], away: Optional[str],
    home_score: Optional[int], away_score: Optional[int],
    fixtures: list[dict],
) -> Optional[dict]:
    """Encontra a partida do SokkerPRO correspondente ao jogo do RoboBet.

    Casa por nomes (ambos os lados) e confirma com o placar quando disponível.
    Retorna o fixture ou None.
    """
    if not home or not away:
        return None

    candidates = []
    for f in fixtures:
        local, visitor = f.get("localTeamName"), f.get("visitorTeamName")
        # Mantém a ordem local/visitante como no RoboBet.
        if _names_match(home, local) and _names_match(away, visitor):
            candidates.append((f, False))  # ordem igual
        elif _names_match(home, visitor) and _names_match(away, local):
            candidates.append((f, True))   # ordem invertida
    if not candidates:
        return None

    # 1) Prefere candidato com placar idêntico.
    for f, inverted in candidates:
        lh, la = _score_of(f, True), _score_of(f, False)
        if inverted:
            lh, la = la, lh
        if home_score is not None and away_score is not None and lh is not None and la is not None:
            if lh == home_score and la == away_score:
                return f
    # 2) Sem placar confirmado, usa o primeiro candidato (nome exato já filtrou).
    return candidates[0][0]


# ---------------------------------------------------------------------------
# Normalização das estatísticas
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum(f: dict, *keys: str) -> Optional[float]:
    """Soma os valores dos campos indicados (None se todos ausentes)."""
    total = 0.0
    any_val = False
    for k in keys:
        v = _num(f.get(k))
        if v is not None:
            total += v
            any_val = True
    return total if any_val else None


def normalize_live_stats(fixture: dict) -> Optional[dict]:
    """Converte um fixture do SokkerPRO nos campos usados pelo scorer.

    Campos ausentes ficam None (o scorer e a interface mostram N/D).
    """
    out = {
        "xg_home": None, "xg_away": None,
        "shots": None, "shots_on_target": None,
        "dangerous_attacks": None, "possession_home": None,
        "corners": None, "big_chances": None, "fouls": None,
        "yellow_cards": None, "red_cards": None,
        "blocked_shots": None, "crosses": None,
        # Extras do SokkerPRO (pressão e ataques por minuto)
        "pressure_bar_home": None, "pressure_bar_away": None,
        "attacks": None, "dapm_total": None, "dapm_home": None, "dapm_away": None,
    }

    out["xg_home"] = _num(fixture.get("localXg"))
    out["xg_away"] = _num(fixture.get("visitorXg"))
    out["shots"] = _sum(fixture, "localShotsTotal", "visitorShotsTotal")
    out["shots_on_target"] = _sum(fixture, "localShotsOnGoal", "visitorShotsOnGoal")
    out["dangerous_attacks"] = _sum(
        fixture, "localAttacksDangerousAttacks", "visitorAttacksDangerousAttacks"
    )
    out["possession_home"] = _num(fixture.get("localBallPossession"))
    out["corners"] = _sum(fixture, "localCorners", "visitorCorners")
    out["fouls"] = _sum(fixture, "localFouls", "visitorFouls")
    out["yellow_cards"] = _sum(fixture, "localYellowCards", "visitorYellowCards")
    out["red_cards"] = _sum(fixture, "localRedCards", "visitorRedCards")
    out["blocked_shots"] = _sum(fixture, "localShotsBlocked", "visitorShotsBlocked")
    out["attacks"] = _sum(fixture, "localAttacksAttacks", "visitorAttacksAttacks")
    out["pressure_bar_home"] = _num(fixture.get("localPressureBar"))
    out["pressure_bar_away"] = _num(fixture.get("visitorPressureBar"))
    out["dapm_home"] = _num(fixture.get("localDapm10"))
    out["dapm_away"] = _num(fixture.get("visitorDapm10"))
    out["dapm_total"] = _sum(fixture, "localDapm10", "visitorDapm10")

    if all(v is None for v in out.values()):
        return None
    return out
