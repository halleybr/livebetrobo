/* ⚡ Live Bet Scanner — frontend (sem frameworks) */

const REFRESH_MS = 30000; // fallback; o servidor informa o intervalo real
const ALERT_LIMIT = 8;
// No GitHub Pages o JSON é gerado pelo GitHub Actions a cada 5 min; acima deste
// tempo a idade dos dados é destacada no topo (o deploy pode levar alguns min).
const STALE_AFTER_MS = 10 * 60 * 1000;

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
  const minuteLabel = m.time_label || `${m.minute || "?"}'`;
  // Janela de 10 min mais próxima (mesma regra do scorer: 25'-59' -> h1, 60'+ -> h2).
  const cornerWindow = m.minute >= 60 ? m.corners_next10_h2 : m.minute >= 25 ? m.corners_next10_h1 : null;

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
      <div class="cell"><span class="k">Esc. esperados (modelo)</span><span class="v">${fmtNum(m.corners_expected_total)}</span></div>
      <div class="cell"><span class="k">Esc. 10 min (modelo)</span><span class="v">${cornerWindow === null ? "N/D" : fmtInt(cornerWindow) + "%"}</span></div>
      <div class="cell"><span class="k">Prob. +1.5 gol (modelo)</span><span class="v">${m.prob_over15_ft === null ? "N/D" : fmtInt(m.prob_over15_ft) + "%"}</span></div>
      <div class="cell"><span class="k">Over 2.5 (modelo)</span><span class="v">${m.prob_over25_ft === null ? "N/D" : fmtInt(m.prob_over25_ft) + "%"}</span></div>
      <div class="cell"><span class="k">BTTS (modelo)</span><span class="v">${m.prob_btts === null ? "N/D" : fmtInt(m.prob_btts) + "%"}</span></div>
      <div class="cell"><span class="k">Sugestão</span><span class="v">${m.suggestion_market ? `${escapeHtml(m.suggestion_label || m.suggestion_market)} ${m.suggestion_prob === null ? "" : fmtInt(m.suggestion_prob) + "%"}`.trim() : "N/D"}</span></div>
    </div>
    <div class="foot">
      <span>${tierLabel(m.tier)} · dados: ${m.data_availability >= 0.7 ? "completos" : "parciais"}</span>
      <span class="basis">fonte: RoboBet</span>
    </div>
  </article>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- Idade dos dados ---------- */

let lastUpdatedAt = null;

function fmtAge(iso) {
  if (!iso) return "—";
  const ageMs = Date.now() - new Date(iso).getTime();
  if (!(ageMs >= 0)) return "agora";
  const s = Math.floor(ageMs / 1000);
  if (s < 60) return "há <1 min";
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  return `há ${h}h ${m % 60}min`;
}

function renderAge() {
  const el = $("stat-updated");
  if (!el || !lastUpdatedAt) return;
  el.textContent = fmtAge(lastUpdatedAt);
  el.title = `Gerado às ${fmtTime(lastUpdatedAt)}`;
  const stale = Date.now() - new Date(lastUpdatedAt).getTime() > STALE_AFTER_MS;
  el.classList.toggle("stale", stale);
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

/* ---------- Possíveis entradas ---------- */

const ENTRIES_DISPLAY_HOURS = 24;
const ENTRIES_MAX = 60;

function entryStatusBadge(e) {
  const map = {
    ativa: '<span class="entry-status st-live">⏳ ATIVA</span>',
    green: '<span class="entry-status st-green">🟢 GREEN</span>',
    red: '<span class="entry-status st-red">🔴 RED</span>',
    n_d: '<span class="entry-status st-nd">⚪ SEM DADO</span>',
  };
  return map[e.status] || `<span class="entry-status">${escapeHtml(e.status)}</span>`;
}

function entryHtml(e) {
  const market = e.market || e.corner_market || "—";
  const odd = e.odd != null ? `@ ${fmtNum(e.odd)}` : "";
  const prob = e.prob != null ? ` · ${fmtInt(e.prob)}%` : "";
  const finalScore = e.final_score ? ` · final ${escapeHtml(e.final_score)}` : "";
  const minute = e.minute_at_entry != null ? ` ${e.minute_at_entry}'` : "";
  return `
  <div class="entry-row" data-id="${escapeHtml(e.id)}">
    <div class="entry-main">
      <span class="entry-teams">${escapeHtml(e.home)} x ${escapeHtml(e.away)}</span>
      <span class="entry-league">${escapeHtml(e.league || "")}</span>
    </div>
    <div class="entry-detail">
      <span class="entry-market">${escapeHtml(market)}</span>
      <span class="entry-odd">${odd}${prob}</span>
      <span class="entry-meta">LPS ${Math.round(e.lps_at_entry ?? 0)}${minute} · entrou ${fmtTime(e.entered_at)}${finalScore}</span>
    </div>
    ${entryStatusBadge(e)}
  </div>`;
}

function renderEntries(entries) {
  const section = $("entries-section");
  const list = $("entries-list");
  if (!entries || !entries.length) {
    section.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  const cutoff = Date.now() - ENTRIES_DISPLAY_HOURS * 3600 * 1000;
  const recent = entries
    .filter((e) => e.entered_at && new Date(e.entered_at).getTime() >= cutoff)
    .slice(0, ENTRIES_MAX);
  if (!recent.length) {
    section.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  const green = recent.filter((e) => e.status === "green").length;
  const red = recent.filter((e) => e.status === "red").length;
  $("entries-summary").textContent = `${recent.length} entradas · 🟢 ${green} · 🔴 ${red}`;
  list.innerHTML = recent.map(entryHtml).join("");
  section.classList.remove("hidden");
}

/* ---------- Render principal ---------- */

function renderSources(sources) {
  const el = $("source-status");
  if (!sources) { el.innerHTML = ""; return; }
  const parts = [];
  parts.push(
    sources.robobet === "ok"
      ? '<span class="badge badge-ok">RoboBet: OK</span>'
      : '<span class="badge badge-err">RoboBet: erro</span>'
  );
  if (sources.last_error) {
    parts.push(`<span>${escapeHtml(sources.last_error)}</span>`);
  }
  el.innerHTML = parts.join(" ");
}

function render(data) {
  const { summary, opportunities, sources } = data;
  $("stat-monitored").textContent = summary?.monitored ?? "—";
  $("stat-opportunities").textContent = summary?.opportunities ?? "—";
  lastUpdatedAt = summary?.updated_at ?? null;
  renderAge();

  renderSources(sources);
  renderEntries(data.entries);

  const cardsEl = $("cards");
  if (!opportunities || !opportunities.length) {
    cardsEl.innerHTML = `<div class="empty"><p>😴 <strong>SEM ENTRADA</strong></p><p>Nenhuma partida ao vivo atingiu o LIVE PRESSURE SCORE mínimo (${data.min_lps ?? 70}) agora. O radar continua monitorando ${summary?.monitored ?? 0} jogos.</p></div>`;
  } else {
    cardsEl.innerHTML = opportunities.map(cardHtml).join("");
  }
  if (data.config) state.refreshMs = (data.config.poll_seconds || 30) * 1000;
}

async function fetchScanner() {
  // No GitHub Pages não existe o backend Python: consumimos o JSON estático
  // gerado pelo GitHub Actions (api/scanner.json). No servidor local,
  // caímos na API ao vivo (/api/scanner).
  // O GitHub Pages (CDN) serve scanner.json com cache de 10 min; o sufixo ?t=
  // força uma busca nova a cada poll e garante que o arquivo recém-deployado
  // apareça assim que o GitHub Actions termina (no servidor local é inofensivo).
  const urls = [`api/scanner.json?t=${Date.now()}`, "/api/scanner"];
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

async function loop() {
  await fetchScanner();
  // setTimeout recursivo: relê state.refreshMs (o servidor/JSON informa o
  // intervalo real) em vez de congelar o valor inicial como fazia o setInterval.
  setTimeout(loop, Math.max(5000, state.refreshMs));
}

// Tic-tac da idade dos dados (o texto "há X min" envelhece entre os polls).
setInterval(renderAge, 15000);

loop();
