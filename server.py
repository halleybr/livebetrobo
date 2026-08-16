#!/usr/bin/env python3
"""⚡ LIVE BET SCANNER — radar de jogos ao vivo.

Sem dependências externas (apenas a stdlib do Python 3.9+).

Fluxo:
  1. Poll do RoboBet (API pública) a cada POLL_SECONDS -> partidas ao vivo.
  2. Cálculo do LIVE PRESSURE SCORE para cada partida.
  3. API JSON em /api/scanner + frontend estático em /.

Como rodar:
    python server.py
    # http://localhost:8765

Configuração (variáveis de ambiente):
    PORT=8765            porta do servidor
    POLL_SECONDS=30      frequência de atualização do RoboBet
    TOP_N=10             máximo de jogos exibidos
    MIN_LPS=70           filtro mínimo do Live Pressure Score
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scanner import robobet
from scanner.entries import EntryTracker
from scanner.scorer import classify

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("scanner")

def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


PORT = _env_int("PORT", 8765)
POLL_SECONDS = _env_int("POLL_SECONDS", 30)
TOP_N = _env_int("TOP_N", 10)
MIN_LPS = float(os.environ.get("MIN_LPS", "70"))

STATIC_DIR = Path(__file__).parent / "static"
ENTRIES_FILE = Path(__file__).parent / "data" / "entries.json"

# ---------------------------------------------------------------------------
# Estado compartilhado
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_tracker = EntryTracker(ENTRIES_FILE, MIN_LPS)

_state: dict = {
    "live_matches": [],       # todas as partidas ao vivo (com score calculado)
    "opportunities": [],      # filtradas (LPS >= MIN_LPS, ordenadas, TOP_N)
    "entries": [],            # entradas recomendadas (histórico green/red)
    "summary": {
        "monitored": 0,
        "opportunities": 0,
        "updated_at": None,
    },
    "sources": {
        "robobet": "unknown",
        "last_error": None,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


# ---------------------------------------------------------------------------
# Poll RoboBet
# ---------------------------------------------------------------------------

def _robobet_poll_loop() -> None:
    while True:
        started = time.time()
        try:
            payload = robobet.fetch_today()
            if payload is None:
                _set_state(
                    sources={
                        **_state["sources"],
                        "robobet": "error",
                        "last_error": "Falha ao buscar dados do RoboBet",
                    }
                )
                log.warning("RoboBet: falha na atualização")
            else:
                matches = robobet.extract_live_matches(payload)
                scored = [classify(m) for m in matches]
                scored.sort(key=lambda m: m["lps"], reverse=True)
                opportunities = [
                    m for m in scored if m["lps"] >= MIN_LPS
                ][:TOP_N]
                finished = robobet.extract_finished_matches(payload)
                _tracker.observe(opportunities, finished)
                _tracker.save()
                _set_state(
                    live_matches=scored,
                    opportunities=opportunities,
                    entries=_tracker.snapshot(),
                    summary={
                        "monitored": len(scored),
                        "opportunities": len(opportunities),
                        "updated_at": _now_iso(),
                    },
                    sources={
                        **_state["sources"],
                        "robobet": "ok",
                        "last_error": None,
                    },
                )
                log.info(
                    "RoboBet OK: %d ao vivo, %d oportunidades (LPS>=%.0f)",
                    len(scored),
                    len(opportunities),
                    MIN_LPS,
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro no poll do RoboBet")
            _set_state(
                sources={
                    **_state["sources"],
                    "robobet": "error",
                    "last_error": str(exc)[:300],
                }
            )
        # Sincroniza o ciclo com o intervalo configurado.
        elapsed = time.time() - started
        time.sleep(max(1, POLL_SECONDS - elapsed))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LiveBetScanner/1.0"

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel_path: str) -> None:
        # Proteção contra path traversal.
        target = (STATIC_DIR / rel_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/scanner":
            with _state_lock:
                payload = {
                    "summary": dict(_state["summary"]),
                    "sources": dict(_state["sources"]),
                    "opportunities": _state["opportunities"],
                    "entries": _state.get("entries", []),
                    "live_count": len(_state["live_matches"]),
                    "min_lps": MIN_LPS,
                    "config": {
                        "poll_seconds": POLL_SECONDS,
                        "top_n": TOP_N,
                    },
                    "generated_at": _now_iso(),
                }
            self._json(payload)
        elif path == "/api/status":
            with _state_lock:
                self._json({"sources": dict(_state["sources"]), "summary": dict(_state["summary"])})
        elif path in ("/", "/index.html"):
            self._static("index.html")
        elif path.startswith("/static/"):
            self._static(path[len("/static/"):])
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.debug(fmt, *args)


def main() -> None:
    threading.Thread(target=_robobet_poll_loop, daemon=True, name="robobet-poll").start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log.info("⚡ LIVE BET SCANNER rodando em http://localhost:%d", PORT)
    log.info("Poll RoboBet: %ds | Filtro LPS >= %s", POLL_SECONDS, MIN_LPS)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Encerrando...")


if __name__ == "__main__":
    main()
