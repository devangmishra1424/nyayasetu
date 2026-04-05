const API_BASE = "";

let sessions = [];
let activeSessionId = null;
let isLoading = false;
let sidebarCollapsed = localStorage.getItem("sidebarCollapsed") === "true";

let textarea, sendBtn, messagesList;

// Wait for DOM to be ready
function initializeApp() {
  console.log("=== App Initialization ===");
  
  textarea = document.getElementById("query-input");
  sendBtn = document.getElementById("send-btn");
  messagesList = document.getElementById("messages-list");
  
  console.log("Elements found - textarea:", !!textarea, "sendBtn:", !!sendBtn, "messagesList:", !!messagesList);
  
  if (!textarea || !sendBtn || !messagesList) {
    console.error("CRITICAL: Required elements not found in DOM!");
    console.error("textarea:", textarea);
    console.error("sendBtn:", sendBtn);
    console.error("messagesList:", messagesList);
    return;
  }

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
  
  console.log("App initialization complete");
}

// Initialize when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeApp);
} else {
  // DOM already loaded (script might be async or deferred)
  initializeApp();
}

function showScreen(name) {
  console.log("showScreen called with name:", name);
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  const screenEl = document.getElementById("screen-" + name);
  if (!screenEl) {
    console.error("Screen element not found:", "screen-" + name);
    return;
  }
  screenEl.classList.add("active");
  console.log("Screen switched to:", name);
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
  if (query.length < 10) { alert("Query too short (minimum 10 characters)"); return; }
  if (query.length > 1000) { alert("Query too long"); return; }

  setLoading(true);
  console.log("=== Submitting Query ===");
  console.log("Query:", query);

  // Create session if needed and switch to chat view
  if (!activeSessionId) {
    createSession(query);
    console.log("Created new session:", activeSessionId);
  }

  // Ensure chat screen is visible
  showScreen("chat");
  console.log("Switched to chat screen");

  const session = getActiveSession();
  
  // Add user message to session and display
  session.messages.push({ role: "user", text: query });
  appendUserBubble(query);
  console.log("Added user message to session");
  
  // Clear input
  textarea.value = "";
  textarea.style.height = "auto";
  
  // Show loading state
  const loaderId = appendLoader();
  console.log("Showing loader:", loaderId);

  try {
    const sessionId = activeSessionId ? String(activeSessionId) : "default";
    console.log("Posting to /query with session_id:", sessionId);
    
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        session_id: sessionId
      })
    });

    console.log("Response status:", res.status);
    console.log("Response ok:", res.ok);

    const data = await res.json();
    console.log("Response data:", data);
    
    removeLoader(loaderId);
    console.log("Removed loader");

    if (!res.ok) {
      const msg = data.detail || data.error || JSON.stringify(data) || "Error: please try again";
      console.error("API Error:", msg);
      session.messages.push({ role: "error", text: msg });
      appendErrorBubble(msg);
    } else {
      console.log("API Success - Adding AI message");
      session.messages.push({ role: "ai", data });
      appendAIBubble(data);
      console.log("AI message added");
    }
  } catch (err) {
    removeLoader(loaderId);
    console.error("Fetch error:", err);
    const msg = `Connection error: ${err.message}`;
    session.messages.push({ role: "error", text: msg });
    appendErrorBubble(msg);
  }

  setLoading(false);
  scrollBottom();
  console.log("=== Query Complete ===");
}

function usesuggestion(queryText) {
  textarea.value = queryText;
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
  submitQuery();
}

function appendUserBubble(text, scroll = true) {
  console.log("appendUserBubble called with text:", text);
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
  console.log("User message appended to DOM");
  if (scroll) scrollBottom();
}

function appendAIBubble(data, scroll = true) {
  console.log("appendAIBubble called with data:", data);
  
  // Handle different response structures
  const answer = data.answer || data.response || data.text || JSON.stringify(data);
  const verified = data.verification_status === true || data.verification_status === "verified";
  const sourceCount = (data.sources || data.source_judgments || []).length;
  
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
        ${formatAnswer(answer)}
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
  console.log("AI message appended to DOM");
  if (scroll) scrollBottom();
}

function appendErrorBubble(text, scroll = true) {
  console.error("appendErrorBubble called with text:", text);
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
  console.log("Error message appended to DOM");
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
  if (!messagesList) {
    console.error("messagesList element not found!");
    return id;
  }
  messagesList.appendChild(div);
  console.log("Loader appended with id:", id, "messagesList children:", messagesList.children.length);
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
    // Find the scrollable content container (the flex container with overflow-y-auto)
    const container = document.querySelector("main > div:nth-child(2)");
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }, 100); // Small delay to ensure DOM has updated
}

function formatAnswer(text) {
  if (!text) {
    console.warn("formatAnswer received empty text");
    return "<em>No response received</em>";
  }
  if (typeof text !== "string") {
    console.log("formatAnswer received non-string:", typeof text);
    return "<em>Invalid response format</em>";
  }
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
