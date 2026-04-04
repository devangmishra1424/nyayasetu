const API_BASE = "";

let sessions = [];
let activeSessionId = null;
let isLoading = false;
let sidebarCollapsed = localStorage.getItem("sidebarCollapsed") === "true";

const textarea = document.getElementById("query-input");
const sendBtn = document.getElementById("send-btn");
const proceedings = document.getElementById("proceedings");

if (sidebarCollapsed) {
  document.getElementById("sidebar").classList.add("collapsed");
}

textarea.addEventListener("input", () => {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
});

textarea.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submitQuery();
  }
});

function showScreen(name) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById("screen-" + name).classList.add("active");
}

function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  sidebarCollapsed = !sidebarCollapsed;
  sidebar.classList.toggle("collapsed");
  localStorage.setItem("sidebarCollapsed", sidebarCollapsed);
}

function createSession(firstQuery) {
  const id = Date.now();
  const title = firstQuery.length > 40 ? firstQuery.substring(0, 40) + "…" : firstQuery;
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
  proceedings.innerHTML = "";
  showScreen("welcome");
  document.getElementById("topbar-title").textContent = "New Research Session";
  renderSessionsList();
  textarea.focus();
}

function renderSessionsList() {
  const list = document.getElementById("sessions-list");
  if (sessions.length === 0) {
    list.innerHTML = '<div class="sessions-empty">No sessions</div>';
    return;
  }
  list.innerHTML = sessions.map(s => `
    <div class="session-item ${s.id === activeSessionId ? "active" : ""}" onclick="switchSession(${s.id})">
      ${escHtml(s.title)}
    </div>
  `).join("");
}

function renderMessages() {
  const session = getActiveSession();
  if (!session) return;
  proceedings.innerHTML = "";
  session.messages.forEach(msg => {
    if (msg.role === "user") appendUserBubble(msg.text, false);
    else if (msg.role === "ai") appendAIBubble(msg.data, false);
    else if (msg.role === "error") appendErrorBubble(msg.text, false);
  });
  scrollBottom();
}

async function submitQuery() {
  const query = textarea.value.trim();
  if (!query || isLoading) return;
  if (query.length < 10) { alert("Query too short"); return; }
  if (query.length > 1000) { alert("Query too long"); return; }

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
      const msg = data.detail || "Error: please try again";
      getActiveSession().messages.push({ role: "error", text: msg });
      appendErrorBubble(msg);
    } else {
      getActiveSession().messages.push({ role: "ai", data });
      appendAIBubble(data);
    }
  } catch (err) {
    removeLoader(loaderId);
    const msg = "Could not reach server";
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

function appendUserBubble(text, scroll = true) {
  const div = document.createElement("div");
  div.className = "message user";
  div.innerHTML = `<div class="bubble user">${escHtml(text)}</div>`;
  proceedings.appendChild(div);
  if (scroll) scrollBottom();
}

function appendAIBubble(data, scroll = true) {
  const verified = data.verification_status === true || data.verification_status === "verified";
  const badgeClass = verified ? "verified" : "unverified";
  const badgeText = verified ? "✓ Verified" : "⚠ Unverified";

  const sourceCount = (data.sources || []).length;
  const sourcesBtn = sourceCount > 0 ? `<button class="sources-btn">📄 ${sourceCount} Source${sourceCount > 1 ? "s" : ""}</button>` : "";

  const latency = data.latency_ms ? `<span style="margin-left: auto; font-size: 10px; color: var(--text-3);">${Math.round(data.latency_ms)}ms</span>` : "";

  const div = document.createElement("div");
  div.className = "message ai";
  div.innerHTML = `
    <div class="bubble ai">
      <div>${formatAnswer(data.answer)}</div>
      <div class="bubble-meta">
        <span class="badge ${badgeClass}">${badgeText}</span>
        ${sourcesBtn}
        ${latency}
      </div>
    </div>`;
  proceedings.appendChild(div);
  if (scroll) scrollBottom();
}

function appendErrorBubble(text, scroll = true) {
  const div = document.createElement("div");
  div.className = "message ai";
  div.innerHTML = `<div class="bubble ai" style="border-left-color: var(--red);">⚠ ${escHtml(text)}</div>`;
  proceedings.appendChild(div);
  if (scroll) scrollBottom();
}

function appendLoader() {
  const id = "loader-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "message ai";
  div.innerHTML = `
    <div class="bubble ai loading">
      <div class="dots"><span></span><span></span><span></span></div>
      Searching...
    </div>`;
  proceedings.appendChild(div);
  scrollBottom();
  return id;
}

function removeLoader(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function setLoading(loading) {
  isLoading = loading;
  sendBtn.disabled = loading;
  const pill = document.getElementById("status-pill");
  if (loading) {
    pill.classList.add("loading");
    document.getElementById("status-text").textContent = "Searching...";
  } else {
    pill.classList.remove("loading");
    document.getElementById("status-text").textContent = "Ready";
  }
}

function scrollBottom() {
  setTimeout(() => {
    const container = document.querySelector(".chat-area");
    if (container) container.scrollTop = container.scrollHeight;
  }, 0);
}

function formatAnswer(text) {
  if (!text) return "";
  return text.replace(/\n/g, "<br>");
}

function escHtml(text) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return text.replace(/[&<>"']/g, m => map[m]);
}

function showAnalytics() {
  showScreen("analytics");
  document.getElementById("topbar-title").textContent = "System Analytics";
  loadAnalytics();
}

function loadAnalytics() {
  fetch(`${API_BASE}/analytics`)
    .then(r => r.json())
    .then(data => {
      document.getElementById("stat-total").textContent = data.total_queries || "—";
      document.getElementById("stat-verified").textContent = (data.verified_rate || 0).toFixed(1) + "%";
      document.getElementById("stat-latency").textContent = Math.round(data.avg_latency_ms || 0) + "ms";
      document.getElementById("stat-ood").textContent = (data.ood_rate || 0).toFixed(1) + "%";
      document.getElementById("stat-sources").textContent = (data.avg_sources || 0).toFixed(1);
    })
    .catch(err => console.error("Analytics load failed:", err));
}
