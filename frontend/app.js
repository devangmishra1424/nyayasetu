// ── Config ──────────────────────────────────────────────────────
const API_BASE = ""; // "" = same origin (HF Spaces). "http://localhost:8000" for local dev.

// ── State ───────────────────────────────────────────────────────
let sessions = [];          // [{id, title, messages:[]}]
let activeSessionId = null;
let isLoading = false;

// ── Init ────────────────────────────────────────────────────────
const textarea  = document.getElementById("query-input");
const sendBtn   = document.getElementById("send-btn");
const msgsList  = document.getElementById("messages-list");

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

  // First message in this chat — create session and switch screen
  if (!activeSessionId) {
    createSession(query);
    showScreen("chat");
    document.getElementById("topbar-title").textContent = getActiveSession().title;
  }

  // Save user message to session
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
      body: JSON.stringify({ query })
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
  const panel  = document.getElementById("sources-panel");
  const overlay = document.getElementById("sources-overlay");
  const body   = document.getElementById("sources-panel-body");

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
  // Trigger CSS transition
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

function formatAnswer(text) {
  // Split double newlines into paragraphs, single newlines into line breaks
  return (text || "")
    .split(/\n\n+/)
    .map(para => `<p>${escHtml(para.trim()).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

function showToast(msg) {
  // Simple alert fallback — can be styled later
  alert(msg);
}