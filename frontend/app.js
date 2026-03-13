// Set to "" for HuggingFace (same origin), or "http://localhost:8000" for local dev
const API_BASE = "";

let isLoading = false;

// Auto-resize textarea
const input = document.getElementById("query-input");
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
});

// Submit on Enter (Shift+Enter for newline)
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    submitQuery();
  }
});

function fillQuery(card) {
  input.value = card.textContent;
  input.dispatchEvent(new Event("input"));
  input.focus();
}

async function submitQuery() {
  const query = input.value.trim();
  if (!query || isLoading) return;
  if (query.length < 10) { alert("Query too short — minimum 10 characters"); return; }
  if (query.length > 1000) { alert("Query too long — maximum 1000 characters"); return; }

  // Switch from welcome to chat
  document.getElementById("welcome-screen").classList.add("hidden");
  document.getElementById("chat-area").classList.remove("hidden");

  // Clear input
  input.value = "";
  input.style.height = "auto";

  // Add to history
  addToHistory(query);

  // Add user bubble
  appendMessage("user", query);

  // Add loading bubble
  const loadingId = appendLoading();

  // Disable button
  setLoading(true);

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });

    const data = await res.json();
    removeLoading(loadingId);

    if (!res.ok) {
      appendError(data.detail || "Something went wrong. Please try again.");
    } else {
      appendAnswer(data);
    }
  } catch (err) {
    removeLoading(loadingId);
    appendError("Could not reach the server. Please check your connection.");
  }

  setLoading(false);
  scrollToBottom();
}

function appendMessage(type, text) {
  const messages = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `message message-${type}`;
  div.innerHTML = `<div class="bubble-${type}">${escapeHtml(text)}</div>`;
  messages.appendChild(div);
  scrollToBottom();
}

function appendAnswer(data) {
  const messages = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message message-ai";

  const verified = data.verification_status === "verified";
  const badge = verified
    ? `<span class="verification-badge badge-verified">✓ Verified</span>`
    : `<span class="verification-badge badge-unverified">⚠ Unverified</span>`;

  const truncNote = data.truncated
    ? `<div style="font-size:11px;color:#9aa3b2;margin-top:8px;">Only 3 of 5 retrieved documents used due to context length.</div>`
    : "";

  // Build sources HTML
  let sourcesHtml = "";
  if (data.sources && data.sources.length > 0) {
    const sourceItems = data.sources.map(s => {
      const meta = s.meta || {};
      const id = meta.judgment_id || "Unknown";
      const year = meta.year || "";
      const excerpt = (s.text || "").substring(0, 200) + "...";
      return `
        <div class="source-card">
          <div class="source-meta">${escapeHtml(id)}${year ? " · " + year : ""}</div>
          <div class="source-excerpt">${escapeHtml(excerpt)}</div>
        </div>`;
    }).join("");

    sourcesHtml = `
      <div class="sources-section">
        <button class="sources-toggle" onclick="toggleSources(this)">▶ Sources (${data.sources.length})</button>
        <div class="sources-list hidden">${sourceItems}</div>
      </div>`;
  }

  div.innerHTML = `
    <div class="bubble-ai">
      <div>${formatAnswer(data.answer)}</div>
      ${badge}
      ${truncNote}
      ${sourcesHtml}
    </div>`;

  messages.appendChild(div);
}

function appendError(msg) {
  const messages = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = "message message-ai";
  div.innerHTML = `
    <div class="bubble-ai" style="border-left-color:#e05252; color:#e8a0a0;">
      ⚠ ${escapeHtml(msg)}
    </div>`;
  messages.appendChild(div);
}

function appendLoading() {
  const messages = document.getElementById("messages");
  const id = "loading-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "message message-ai";
  div.innerHTML = `
    <div class="bubble-ai bubble-loading">
      <div class="loading-dots">
        <span></span><span></span><span></span>
      </div>
      Searching judgments...
    </div>`;
  messages.appendChild(div);
  scrollToBottom();
  return id;
}

function removeLoading(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function toggleSources(btn) {
  const list = btn.nextElementSibling;
  const isHidden = list.classList.contains("hidden");
  list.classList.toggle("hidden");
  btn.textContent = (isHidden ? "▼" : "▶") + btn.textContent.slice(1);
}

function addToHistory(query) {
  const list = document.getElementById("history-list");
  const empty = list.querySelector(".history-empty");
  if (empty) empty.remove();

  const item = document.createElement("div");
  item.className = "history-item";
  item.title = query;
  item.textContent = query.length > 40 ? query.substring(0, 40) + "…" : query;
  list.insertBefore(item, list.firstChild);

  // Keep max 10 items
  const items = list.querySelectorAll(".history-item");
  if (items.length > 10) items[items.length - 1].remove();
}

function setLoading(state) {
  isLoading = state;
  const btn = document.getElementById("send-btn");
  btn.disabled = state;
  document.getElementById("send-icon").textContent = state ? "…" : "→";
}

function scrollToBottom() {
  const chat = document.getElementById("chat-area");
  chat.scrollTop = chat.scrollHeight;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatAnswer(text) {
  // Convert newlines to paragraphs
  return text
    .split(/\n\n+/)
    .map(p => `<p>${escapeHtml(p.trim())}</p>`)
    .join("");
}