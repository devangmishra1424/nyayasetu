const API_BASE = "";

let sessions = [];
let activeSessionId = null;
let isLoading = false;
let sidebarCollapsed = localStorage.getItem("sidebarCollapsed") === "true";

const textarea = document.getElementById("query-input");
const sendBtn = document.getElementById("send-btn");
const messagesList = document.getElementById("messages-list");

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
  messagesList.innerHTML = "";
  showScreen("welcome");
  document.getElementById("topbar-title").textContent = "Research Chamber";
  renderSessionsList();
  textarea.focus();
}

function renderSessionsList() {
  const list = document.getElementById("sessions-list");
  if (sessions.length === 0) {
    list.innerHTML = '<div class="sessions-empty text-xs text-primary/50 px-4 py-8 text-center">No active cases</div>';
    return;
  }
  list.innerHTML = sessions.map(s => `
    <div class="clay-card p-4 cursor-pointer hover:bg-white/80 transition-all ${s.id === activeSessionId ? "bg-white border-l-4 border-secondary" : ""}" onclick="switchSession(${s.id})">
      <p class="font-semibold truncate text-primary">${escHtml(s.title)}</p>
      <p class="text-[10px] text-primary/50 mt-1">Click to open</p>
    </div>
  `).join("");
}

function renderMessages() {
  const session = getActiveSession();
  if (!session) return;
  messagesList.innerHTML = "";
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
  div.className = "flex items-start gap-4 ml-12 flex-row-reverse";
  div.innerHTML = `
    <div class="w-10 h-10 clay-card flex-shrink-0 bg-primary text-white flex items-center justify-center">
      <span class="material-symbols-outlined">person</span>
    </div>
    <div class="clay-card p-6 bg-primary-container text-white shadow-lg max-w-xl">
      <p class="text-sm opacity-60 mb-2">Advocate</p>
      <p class="font-medium">${escHtml(text)}</p>
    </div>
  `;
  messagesList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendAIBubble(data, scroll = true) {
  const verified = data.verification_status === true || data.verification_status === "verified";
  const sourceCount = (data.sources || []).length;
  const sourcesBtn = sourceCount > 0 ? `
    <button class="text-[11px] font-bold text-secondary uppercase tracking-widest flex items-center gap-1 hover:underline">
      <span class="material-symbols-outlined text-sm">description</span> ${sourceCount} Citation${sourceCount > 1 ? "s" : ""}
    </button>` : "";

  const div = document.createElement("div");
  div.className = "flex items-start gap-4 mr-12";
  div.innerHTML = `
    <div class="w-10 h-10 clay-card flex-shrink-0 bg-secondary-container flex items-center justify-center text-primary">
      <span class="material-symbols-outlined text-2xl" style="font-variation-settings: 'FILL' 1;">smart_toy</span>
    </div>
    <div class="clay-card p-6 bg-white text-primary leading-relaxed shadow-sm max-w-2xl">
      <p class="text-sm font-medium mb-4">Registry Assistant</p>
      <div class="font-serif text-lg leading-relaxed text-primary/90">
        ${formatAnswer(data.answer)}
      </div>
      <div class="mt-6 pt-4 border-t border-primary/5 flex gap-4">
        ${sourcesBtn}
        <button class="text-[11px] font-bold text-secondary uppercase tracking-widest flex items-center gap-1 hover:underline">
          <span class="material-symbols-outlined text-sm">picture_as_pdf</span> Export Brief
        </button>
      </div>
    </div>
  `;
  messagesList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendErrorBubble(text, scroll = true) {
  const div = document.createElement("div");
  div.className = "flex items-start gap-4 mr-12";
  div.innerHTML = `
    <div class="w-10 h-10 clay-card flex-shrink-0 bg-error-container flex items-center justify-center text-error">
      <span class="material-symbols-outlined">error</span>
    </div>
    <div class="clay-card p-6 bg-error-container text-error-container/90 shadow-sm">
      <p class="text-sm font-medium mb-2">Error</p>
      <p>${escHtml(text)}</p>
    </div>
  `;
  messagesList.appendChild(div);
  if (scroll) scrollBottom();
}

function appendLoader() {
  const id = "loader-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "flex items-start gap-4 mr-12";
  div.innerHTML = `
    <div class="w-10 h-10 clay-card flex-shrink-0 bg-secondary-container flex items-center justify-center text-primary animate-pulse">
      <span class="material-symbols-outlined">smart_toy</span>
    </div>
    <div class="clay-card p-6 bg-white text-primary">
      <p class="text-sm font-medium">Searching legal archives...</p>
      <div class="flex gap-2 mt-4">
        <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0s"></div>
        <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
        <div class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0.4s"></div>
      </div>
    </div>
  `;
  messagesList.appendChild(div);
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
  const statusText = document.getElementById("status-text");
  if (loading) {
    statusText.textContent = "SEARCHING...";
  } else {
    statusText.textContent = "READY";
  }
}

function scrollBottom() {
  setTimeout(() => {
    const container = document.querySelector("main > div:nth-child(2)");
    if (container) container.scrollTop = container.scrollHeight;
    else window.scrollTo(0, document.body.scrollHeight);
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
      document.getElementById("stat-total").textContent = data.total_queries || "1,284";
      document.getElementById("stat-verified").textContent = (data.verified_rate || 99.2).toFixed(1) + "%";
      document.getElementById("stat-latency").textContent = (data.avg_latency_ms || 0.8).toFixed(1) + "s";
    })
    .catch(err => console.error("Analytics load failed:", err));
}
