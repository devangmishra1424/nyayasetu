// ── Config ──────────────────────────────────────────────────────
const API_BASE = ""; // "" = same origin (HF Spaces). "http://localhost:8000" for local dev.

// ── State ───────────────────────────────────────────────────────
let sessions = [];          // [{id, title, messages:[]}]
let activeSessionId = null;
let isLoading = false;
let sidebarCollapsed = localStorage.getItem("sidebarCollapsed") === "true";

// ── Init ────────────────────────────────────────────────────────
const textarea  = document.getElementById("query-input");
const sendBtn   = document.getElementById("send-btn");
const msgsList  = document.getElementById("messages-list");

// Apply sidebar collapsed state on load
if (sidebarCollapsed) {
  document.getElementById("sidebar").classList.add("collapsed");
}

textarea.addEventListener("input", () => {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + "px";
});

textarea.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitQuery(); }
});

// ── Screen switching ─────────────────────────────────────────────
function showScreen(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("screen-" + name).classList.add("active");
}

// ── Sidebar toggle ───────────────────────────────────────────────
function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  sidebarCollapsed = !sidebarCollapsed;
  sidebar.classList.toggle("collapsed");
  localStorage.setItem("sidebarCollapsed", sidebarCollapsed);
}

// ── Session management ───────────────────────────────────────────
function createSession(firstQuery) {
  const id = Date.now();
  const title = firstQuery.length > 45
    ? firstQuery.substring(0, 45) + "…"
    : firstQuery;
  const session = { id, title, messages: [] };
  sessions.unshift(session);
  activeSessionId = id;
  renderSessionsList();
  return session;
}

function getActiveSession() {
  return sessions.find(s => s.id === activeSessionId);
}

function switchSession(id) {
  activeSessionId = id;
  renderSessionsList();
  renderMessages();
  showScreen("chat");
  const session = getActiveSession();
  document.getElementById("topbar-title").textContent = session.title;
}

function newChat() {
  activeSessionId = null;
  msgsList.innerHTML = "";
  showScreen("welcome");
  document.getElementById("topbar-title").textContent = "New Research Session";
  renderSessionsList();
  textarea.focus();
}

function renderSessionsList() {
  const list = document.getElementById("sessions-list");
  if (sessions.length === 0) {
    list.innerHTML = '<div class="sessions-empty">No sessions yet</div>';
    return;
  }
  list.innerHTML = sessions.map(s => `
    <div class="session-item ${s.id === activeSessionId ? "active" : ""}"
         onclick="switchSession(${s.id})">
      <div class="session-dot"></div>
      <span class="session-label">${escHtml(s.title)}</span>
      <span class="session-count">${s.messages.filter(m => m.role === "ai").length}</span>
    </div>
  `).join("");
}

function renderMessages() {
  const session = getActiveSession();
  if (!session) return;
  msgsList.innerHTML = "";
  session.messages.forEach(msg => {
    if (msg.role === "user") appendUserBubble(msg.text, false);
    else if (msg.role === "ai") appendAIBubble(msg.data, false);
    else if (msg.role === "error") appendErrorBubble(msg.text, false);
  });
  scrollBottom();
}

// ── Submit ───────────────────────────────────────────────────────
async function submitQuery() {
  const query = textarea.value.trim();
  if (!query || isLoading) return;
  if (query.length < 10) { showToast("Query too short — minimum 10 characters."); return; }
  if (query.length > 1000) { showToast("Query too long — maximum 1000 characters."); return; }

  if (!activeSessionId) {
    createSession(query);
    showScreen("chat");
    document.getElementById("topbar-title").textContent = getActiveSession().title;
  }

  getActiveSession().messages.push({ role: "user", text: query });

  textarea.value = "";
  textarea.style.height = "auto";

  appendUserBubble(query);
  const loaderId = appendLoader();
  setLoading(true);

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        session_id: activeSessionId ? String(activeSessionId) : "default"
      })
    });

    const data = await res.json();
    removeLoader(loaderId);

    if (!res.ok) {
      const msg = data.detail || "Something went wrong. Please try again.";
      getActiveSession().messages.push({ role: "error", text: msg });
      appendErrorBubble(msg);
    } else {
      getActiveSession().messages.push({ role: "ai", data });
      appendAIBubble(data);
    }

  } catch (err) {
    removeLoader(loaderId);
    const msg = "Could not reach the server. The Space may be waking up — try again in 30 seconds.";
    getActiveSession().messages.push({ role: "error", text: msg });
    appendErrorBubble(msg);
  }

  setLoading(false);
  scrollBottom();
}

function usesuggestion(el) {
  textarea.value = el.textContent;
  textarea.dispatchEvent(new Event("input"));
  submitQuery();
}

// ── Bubble renderers ─────────────────────────────────────────────
function appendUserBubble(text, scroll = true) {
  const div = document.createElement("div");
  div.className = "msg msg-user";
  div.innerHTML = `<div class="bubble-user">${escHtml(text)}</div>`;
  msgsList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendAIBubble(data, scroll = true) {
  const verified = data.verification_status === true || data.verification_status === "verified";
  const badgeClass = verified ? "verified" : "unverified";
  const badgeText  = verified ? "✓ Verified" : "⚠ Unverified";

  const truncNote = data.truncated
    ? `<div class="truncated-note">3 of 5 retrieved documents used — context limit reached.</div>`
    : "";

  const sourceCount = (data.sources || []).length;
  const sourcesBtn = sourceCount > 0
    ? `<button class="sources-btn" onclick='openSources(${escAttr(JSON.stringify(data.sources))})'>
         📄 ${sourceCount} Source${sourceCount > 1 ? "s" : ""}
       </button>`
    : "";

  const latency = data.latency_ms
    ? `<span class="latency-label">${Math.round(data.latency_ms)}ms</span>`
    : "";

  const div = document.createElement("div");
  div.className = "msg msg-ai";
  div.innerHTML = `
    <div class="bubble-ai">
      <div class="bubble-answer">${formatAnswer(data.answer)}</div>
      ${truncNote}
      <div class="bubble-meta">
        <span class="verify-badge ${badgeClass}">${badgeText}</span>
        ${sourcesBtn}
        ${latency}
      </div>
    </div>`;
  msgsList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendErrorBubble(text, scroll = true) {
  const div = document.createElement("div");
  div.className = "msg msg-ai";
  div.innerHTML = `<div class="bubble-error">⚠ ${escHtml(text)}</div>`;
  msgsList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendLoader() {
  const id = "loader-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "msg msg-ai";
  div.innerHTML = `
    <div class="bubble-ai bubble-loading">
      <div class="dots"><span></span><span></span><span></span></div>
      Searching judgments…
    </div>`;
  msgsList.appendChild(div);
  scrollBottom();
  return id;
}

function removeLoader(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ── Sources panel ────────────────────────────────────────────────
function openSources(sources) {
  const panel   = document.getElementById("sources-panel");
  const overlay = document.getElementById("sources-overlay");
  const body    = document.getElementById("sources-panel-body");

  body.innerHTML = sources.map((s, i) => {
    const meta    = s.meta || {};
    const id      = meta.judgment_id || "Unknown";
    const year    = meta.year ? ` · ${meta.year}` : "";
    const excerpt = (s.text || "").trim().substring(0, 400);
    return `
      <div class="source-card">
        <div class="source-num">${i + 1}</div>
        <div class="source-id">${escHtml(id)}</div>
        <div class="source-year">Supreme Court of India${year}</div>
        <div class="source-excerpt">${escHtml(excerpt)}${s.text && s.text.length > 400 ? "…" : ""}</div>
      </div>`;
  }).join("");

  panel.classList.add("open");
  overlay.classList.add("open");
  requestAnimationFrame(() => { panel.style.transform = "translateX(0)"; });
}

function closeSourcesPanel() {
  const panel   = document.getElementById("sources-panel");
  const overlay = document.getElementById("sources-overlay");
  panel.classList.remove("open");
  overlay.classList.remove("open");
}

// ── Helpers ──────────────────────────────────────────────────────
function setLoading(state) {
  isLoading = state;
  sendBtn.disabled = state;
  const pill = document.getElementById("status-pill");
  const text = document.getElementById("status-text");
  if (state) {
    pill.classList.add("loading");
    text.textContent = "Searching…";
  } else {
    pill.classList.remove("loading");
    text.textContent = "Ready";
  }
}

function scrollBottom() {
  const c = document.querySelector(".messages-container");
  if (c) c.scrollTop = c.scrollHeight;
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(str) {
  return String(str || "").replace(/'/g, "&#39;").replace(/"/g, "&quot;");
}

// ── Answer formatter ─────────────────────────────────────────────
function formatAnswer(text) {
  if (!text) return "";
  text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  const lines = text.split('\n');
  let html = '';
  let inTable = false;
  let tableHtml = '';
  let inList = false;
  let listType = '';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Table row
    if (line.trim().startsWith('|')) {
      if (line.match(/^\|[\s\-|]+\|$/)) continue; // skip separator rows
      if (!inTable) { tableHtml = '<table class="answer-table">'; inTable = true; }
      const cells = line.split('|').filter((c, idx, a) => idx > 0 && idx < a.length - 1);
      tableHtml += '<tr>' + cells.map(c => `<td>${inline(c.trim())}</td>`).join('') + '</tr>';
      continue;
    } else if (inTable) {
      html += tableHtml + '</table>';
      tableHtml = ''; inTable = false;
    }

    // Numbered list
    if (line.match(/^\d+\.\s+/)) {
      if (!inList || listType !== 'ol') {
        if (inList) html += `</${listType}>`;
        html += '<ol>'; inList = true; listType = 'ol';
      }
      html += `<li>${inline(line.replace(/^\d+\.\s+/, ''))}</li>`;
      continue;
    }

    // Bullet list
    if (line.match(/^[\*\-]\s+/)) {
      if (!inList || listType !== 'ul') {
        if (inList) html += `</${listType}>`;
        html += '<ul>'; inList = true; listType = 'ul';
      }
      html += `<li>${inline(line.replace(/^[\*\-]\s+/, ''))}</li>`;
      continue;
    }

    // Close list on blank line
    if (inList && line.trim() === '') {
      html += `</${listType}>`;
      inList = false; listType = '';
    }

    // Headers
    if (line.startsWith('### ')) { html += `<h3>${inline(line.slice(4))}</h3>`; continue; }
    if (line.startsWith('## '))  { html += `<h2>${inline(line.slice(3))}</h2>`; continue; }
    if (line.startsWith('# '))   { html += `<h1>${inline(line.slice(2))}</h1>`; continue; }

    // Blank line
    if (line.trim() === '') { html += '<br>'; continue; }

    // Normal paragraph line
    html += `<p>${inline(line)}</p>`;
  }

  // Close any unclosed tags
  if (inTable) html += tableHtml + '</table>';
  if (inList)  html += `</${listType}>`;

  return html;
}

function inline(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}

function showToast(msg) {
  alert(msg);
}

// ── Analytics ────────────────────────────────────────────────────────
async function showAnalytics() {
  showScreen("analytics");
  document.getElementById("topbar-title").textContent = "System Analytics";
  await loadAnalytics();
}

async function loadAnalytics() {
  try {
    const res = await fetch(`${API_BASE}/analytics`);
    const data = await res.json();

    if (data.total_queries === 0) {
      document.getElementById("stat-total").textContent = "0";
      document.getElementById("stat-verified").textContent = "—";
      document.getElementById("stat-latency").textContent = "—";
      document.getElementById("stat-ood").textContent = "—";
      document.getElementById("stat-sources").textContent = "—";
      document.getElementById("chart-stages").innerHTML = "<p class='no-data'>No queries yet. Start asking questions.</p>";
      document.getElementById("chart-entities").innerHTML = "<p class='no-data'>No entity data yet.</p>";
      document.getElementById("chart-latency").innerHTML = "<p class='no-data'>No latency data yet.</p>";
      return;
    }

    // Stat cards
    document.getElementById("stat-total").textContent = data.total_queries;
    document.getElementById("stat-verified").textContent = data.verified_ratio + "%";
    document.getElementById("stat-latency").textContent = data.avg_latency_ms + "ms";
    document.getElementById("stat-ood").textContent = data.out_of_domain_rate + "%";
    document.getElementById("stat-sources").textContent = data.avg_sources;

    // Stage distribution bar chart
    renderBarChart("chart-stages", data.stage_distribution);

    // Entity frequency bar chart
    renderBarChart("chart-entities", data.entity_type_frequency);

    // Latency sparkline
    renderSparkline("chart-latency", data.recent_latencies);

  } catch (err) {
    document.getElementById("chart-stages").innerHTML = "<p class='no-data'>Could not load analytics.</p>";
  }
}

function renderBarChart(containerId, data) {
  const container = document.getElementById(containerId);
  if (!data || Object.keys(data).length === 0) {
    container.innerHTML = "<p class='no-data'>No data yet.</p>";
    return;
  }

  const max = Math.max(...Object.values(data));
  const html = Object.entries(data)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => `
      <div class="bar-row">
        <span class="bar-label">${escHtml(label)}</span>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${Math.round(value / max * 100)}%"></div>
        </div>
        <span class="bar-value">${value}</span>
      </div>
    `).join("");

  container.innerHTML = `<div class="bar-chart">${html}</div>`;
}

function renderSparkline(containerId, latencies) {
  const container = document.getElementById(containerId);
  if (!latencies || latencies.length === 0) {
    container.innerHTML = "<p class='no-data'>No data yet.</p>";
    return;
  }

  const max = Math.max(...latencies);
  const min = Math.min(...latencies);
  const range = max - min || 1;
  const height = 60;
  const width = 300;
  const step = width / (latencies.length - 1 || 1);

  const points = latencies.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  }).join(" ");

  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="sparkline">
      <polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    </svg>
    <div class="sparkline-range">
      <span>${Math.round(min)}ms min</span>
      <span>${Math.round(max)}ms max</span>
    </div>
  `;
}

function escHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}