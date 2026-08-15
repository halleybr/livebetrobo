/* ⚡ Live Bet Scanner — frontend (sem frameworks) */

const REFRESH_MS = 30000; // fallback; o servidor informa o intervalo real
const ALERT_LIMIT = 8;

const state = {
  prev: new Map(),   // id -> snapshot anterior (para detecção de alertas)
  alerts: [],        // [{time, msg}]
  refreshMs: REFRESH_MS,
};

const $ = (id) => document.getElementById(id);

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-BR", { hour12: false });
}

function nd(v) {
  return v === null || v === undefined ? "N/D" : v;
}

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return "N/D";
  return Number(v).toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtInt(v) {
  if (v === null || v === undefined) return "N/D";
  return Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

function pressureBar(m) {
  const bars = [m.pressure_bar_home, m.pressure_bar_away].filter((v) => v !== null && v !== undefined);
  if (!bars.length) return "N/D";
  return fmtInt(bars.reduce((a, b) => a + b, 0) / bars.length);
}

function tierLabel(tier) {
  return {
    muito_forte: "🟢 OPORTUNIDADE MUITO FORTE",
    interessante: "🟡 OPORTUNIDADE INTERESSANTE",
    observar: "🟠 OBSERVAR",
    ignorar: "🔴 IGNORAR",
  }[tier] || tier;
}

function entryBadge(m) {
  const cls = { goals: "", corners: "corners", both: "both", none: "none" }[m.entry_type] || "none";
  const txt = {
    goals: "⚽ GOLS",
    corners: "🚩 ESCANTEIOS",
    both: "⚽🚩 GOLS + ESCANTEIOS",
    none: "❌ SEM ENTRADA",
  }[m.entry_type] || "❌ SEM ENTRADA";

  let detail = "";
  if (m.entry_type === "goals") detail = m.market || "";
  else if (m.entry_type === "corners") detail = m.corner_market || "";
  else if (m.entry_type === "both") detail = [m.market, m.corner_market].filter(Boolean).join(" · ");

  return `<span class="entry ${cls}">${txt}${detail ? ` — ${detail}` : ""}</span>`;
}

function confidenceHtml(m) {
  const c = m.confidence || "Baixa";
  return `<span class="confidence">Confiança: <strong class="${c.toLowerCase()}">${c}</strong></span>`;
}

function cardHtml(m) {
  const hot = m.lps >= 80 ? "hot" : "";
  const xgTot =
    m.xg_home !== null && m.xg_away !== null
      ? fmtNum(m.xg_home + m.xg_away)
      : "N/D";
  const minuteLabel = m.time_label || `${m.minute || "?"}'`;

  return `
  <article class="card ${hot}" data-id="${m.id}">
    <div class="card-head">
      <div>
        <div class="league">${escapeHtml(m.league || "N/D")}</div>
        <div class="teams">
          ${escapeHtml(m.home || "?")} <span class="score">${fmtInt(m.home_score)} x ${fmtInt(m.away_score)}</span> ${escapeHtml(m.away || "?")}
        </div>
        <div class="minute">⏱ ${minuteLabel}</div>
        ${entryBadge(m)}
        ${confidenceHtml(m)}
      </div>
      <div class="lps-box tier-${m.tier}">
        <div class="lps-value">${Math.round(m.lps)}</div>
        <div class="lps-label">LIVE PRESSURE</div>
      </div>
    </div>
    <div class="stats-grid">
      <div class="cell"><span class="k">xG</span><span class="v ${xgTot === "N/D" ? "nd" : ""}">${xgTot}</span></div>
      <div class="cell"><span class="k">Finalizações</span><span class="v ${m.shots === null ? "nd" : ""}">${fmtInt(m.shots)}</span></div>
      <div class="cell"><span class="k">No alvo</span><span class="v ${m.shots_on_target === null ? "nd" : ""}">${fmtInt(m.shots_on_target)}</span></div>
      <div class="cell"><span class="k">Ataq. perigosos</span><span class="v ${m.dangerous_attacks === null ? "nd" : ""}">${fmtInt(m.dangerous_attacks)}</span></div>
      <div class="cell"><span class="k">Escanteios</span><span class="v ${m.corners === null ? "nd" : ""}">${fmtInt(m.corners)}</span></div>
      <div class="cell"><span class="k">Esc. esperados (modelo)</span><span class="v">${fmtNum(m.corners_expected_total)}</span></div>
      <div class="cell"><span class="k">Pressão 🔥</span><span class="v">${pressureBar(m)}</span></div>
      <div class="cell"><span class="k">Prob. +1.5 gol (modelo)</span><span class="v">${m.prob_over15_ft === null ? "N/D" : fmtInt(m.prob_over15_ft) + "%"}</span></div>
      <div class="cell"><span class="k">BTTS (modelo)</span><span class="v">${m.prob_btts === null ? "N/D" : fmtInt(m.prob_btts) + "%"}</span></div>
    </div>
    <div class="foot">
      <span>${tierLabel(m.tier)} · dados: ${m.data_availability >= 0.7 ? "completos" : "parciais"}</span>
      <span class="basis">fonte: ${m.basis === "robobet+sokkerpro" ? "RoboBet + SokkerPRO" : "RoboBet"}</span>
    </div>
  </article>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- Alertas ---------- */

function pushAlert(msg) {
  state.alerts.unshift({ time: new Date(), msg });
  state.alerts = state.alerts.slice(0, ALERT_LIMIT);
  renderAlerts();
}

function renderAlerts() {
  const el = $("alerts");
  if (!state.alerts.length) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  el.innerHTML = state.alerts
    .map(
      (a) => `<div class="alert"><span class="time">${a.time.toLocaleTimeString("pt-BR", { hour12: false })}</span><span class="msg">${a.msg}</span></div>`
    )
    .join("");
}

function detectAlerts(opportunities) {
  const now = new Map(opportunities.map((m) => [m.id, m]));
  for (const m of opportunities) {
    const prev = state.prev.get(m.id);
    if (!prev) continue;

    // 🔥 nova oportunidade: cruzou o limite de 80 ou salto grande de pressão
    if (m.lps >= 80 && (prev.lps < 80 || m.lps - prev.lps >= 8)) {
      pushAlert(`🔥 NOVA OPORTUNIDADE — ${m.home} x ${m.away} (LPS ${Math.round(m.lps)})`);
    }
    // ⚽ gol
    if (
      (m.home_score !== prev.home_score || m.away_score !== prev.away_score) &&
      m.entry_type !== "none"
    ) {
      pushAlert(`⚽ GOL! ${m.home} ${fmtInt(m.home_score)} x ${fmtInt(m.away_score)} ${m.away} — pressão alta (LPS ${Math.round(m.lps)})`);
    }
    // mudança de entrada
    if (m.entry_type !== prev.entry_type && m.entry_type !== "none") {
      const label = m.entry_type === "goals" ? "⚽ GOLS" : m.entry_type === "corners" ? "🚩 ESCANTEIOS" : "⚽🚩 GOLS + ESCANTEIOS";
      pushAlert(`🔄 Entrada alterada: ${m.home} x ${m.away} → ${label}`);
    }
  }
  state.prev = now;
}

/* ---------- Render principal ---------- */

function renderSources(sources) {
  const el = $("source-status");
  if (!sources) { el.innerHTML = ""; return; }
  const provider = (sources.provider || "SokkerPRO").toUpperCase();
  const parts = [];
  parts.push(
    sources.robobet === "ok"
      ? '<span class="badge badge-ok">RoboBet: OK</span>'
      : '<span class="badge badge-err">RoboBet: erro</span>'
  );
  if (sources.stats === "disabled") {
    parts.push(`<span class="badge badge-warn">${provider}: desligado</span>`);
  } else if (sources.stats === "error") {
    parts.push(`<span class="badge badge-warn">${provider}: indisponível (estatísticas = N/D)</span>`);
  } else if (sources.stats === "ok") {
    parts.push(`<span class="badge badge-ok">${provider}: OK</span>`);
  } else {
    parts.push(`<span class="badge badge-warn">${provider}: aguardando…</span>`);
  }
  if (sources.last_error) {
    parts.push(`<span>${escapeHtml(sources.last_error)}</span>`);
  }
  el.innerHTML = parts.join(" ");
}

function render(data) {
  const { summary, opportunities, sources } = data;
  $("stat-monitored").textContent = summary?.monitored ?? "—";
  $("stat-opportunities").textContent = summary?.opportunities ?? "—";
  $("stat-updated").textContent = fmtTime(summary?.updated_at);

  renderSources(sources);

  const cardsEl = $("cards");
  if (!opportunities || !opportunities.length) {
    cardsEl.innerHTML = `<div class="empty"><p>😴 <strong>SEM ENTRADA</strong></p><p>Nenhuma partida ao vivo atingiu o LIVE PRESSURE SCORE mínimo (${data.min_lps ?? 70}) agora. O radar continua monitorando ${summary?.monitored ?? 0} jogos.</p></div>`;
    return;
  }

  cardsEl.innerHTML = opportunities.map(cardHtml).join("");
  if (data.config) state.refreshMs = (data.config.poll_seconds || 30) * 1000;
}

async function fetchScanner() {
  // No GitHub Pages não existe o backend Python: consumimos o JSON estático
  // gerado pelo GitHub Actions (api/scanner.json). No servidor local,
  // caímos na API ao vivo (/api/scanner).
  const urls = ["api/scanner.json", "/api/scanner"];
  let lastErr = null;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      detectAlerts(data.opportunities || []);
      render(data);
      return;
    } catch (err) {
      lastErr = err;
    }
  }
  $("cards").innerHTML = `<div class="empty"><p>❌ Erro ao conectar com o servidor.</p><p style="font-size:13px">Verifique se o scanner está rodando: <code>python server.py</code></p></div>`;
  console.error(lastErr);
}

function loop() {
  fetchScanner();
  setInterval(fetchScanner, state.refreshMs);
}

loop();
