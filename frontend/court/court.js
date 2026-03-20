// ════════════════════════════════════════════════════════════
// GLOBAL STATE
// ════════════════════════════════════════════════════════════

const state = {
  currentSession: null,
  currentScreen: 'lobby',
  setupStep: 1,
  setupData: {
    side: null,
    title: '',
    userClient: '',
    opposingParty: '',
    issues: [],
    facts: '',
    jurisdiction: 'supreme_court',
    bench: 'division',
    difficulty: 'standard',
    Length: 'standard',
    trapWarnings: true,
  },
  currentRound: 0,
  transcript: [],
  concessions: [],
  documents: [],
  traps: [],
  isWaitingForResponse: false,
};

// ════════════════════════════════════════════════════════════
// INITIALIZATION
// ════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  console.log('✓ NyayaSetu Moot Court UI loaded');
  try { loadRecentSessions(); } catch (e) { console.warn('Could not load sessions:', e); }
  updateLobbyTime();
  setInterval(updateLobbyTime, 1000);
  const argInput = document.getElementById('argument-input');
  if (argInput) {
    argInput.addEventListener('input', updateWordCount);
  }
});

// ════════════════════════════════════════════════════════════
// SCREEN MANAGEMENT
// ════════════════════════════════════════════════════════════

function showScreen(screenId) {
  console.log(`🔄 Navigating to screen: ${screenId}`);
  // Hide all screens
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  
  // Show target screen
  const targetScreen = document.getElementById(`screen-${screenId}`);
  if (targetScreen) {
    targetScreen.classList.add('active');
    state.currentScreen = screenId;
    console.log(`✓ Screen active: ${screenId}`);
    
    // Screen-specific initialization
    if (screenId === 'lobby') {
      try { loadRecentSessions(); } catch (e) { console.warn('Error loading sessions:', e); }
    } else if (screenId === 'courtroom') {
      initializeCourtroom();
    } else if (screenId === 'analysis') {
      renderAnalysis();
    } else if (screenId === 'sessions') {
      loadAllSessions();
    }
  } else {
    console.error(`✗ Screen not found: screen-${screenId}`);
  }
}

// ════════════════════════════════════════════════════════════
// SETUP WIZARD
// ════════════════════════════════════════════════════════════

function selectSide(side) {
  state.setupData.side = side;
  document.querySelectorAll('.side-card').forEach(c => c.classList.remove('selected'));
  document.getElementById(`side-${side}`).classList.add('selected');
}

function selectOption(category, value) {
  if (category === 'bench') state.setupData.bench = value;
  if (category === 'diff') state.setupData.difficulty = value;
  if (category === 'len') state.setupData.Length = value;

  document.querySelectorAll(`[id^="${category}-"]`).forEach(c => c.classList.remove('selected'));
  document.getElementById(`${category}-${value}`).classList.add('selected');
}

function addIssue() {
  const input = document.getElementById('issue-input');
  const issue = input.value.trim();
  if (issue) {
    state.setupData.issues.push(issue);
    input.value = '';
    renderIssues();
  }
}

function renderIssues() {
  const list = document.getElementById('issues-list');
  list.innerHTML = state.setupData.issues.map(issue => 
    `<span class="px-3 py-1 bg-secondary-fixed text-secondary rounded-full text-sm font-sans flex items-center gap-2">
      ${issue}
      <button onclick="removeIssue('${issue}')" class="cursor-pointer">✕</button>
    </span>`
  ).join('');
}

function removeIssue(issue) {
  state.setupData.issues = state.setupData.issues.filter(i => i !== issue);
  renderIssues();
}

function goToStep(step) {
  console.log(`→ Moving to setup step ${step}`);
  
  // Validate current step
  if (state.setupStep === 1 && !state.setupData.side) {
    alert('Please select your side');
    console.warn('Cannot advance: side not selected');
    return;
  }
  if (state.setupStep === 2) {
    const title = document.getElementById('case-title').value.trim();
    if (!title) {
      alert('Please enter case title');
      console.warn('Cannot advance: case title missing');
      return;
    }
    state.setupData.title = title;
    state.setupData.userClient = document.getElementById('user-client').value;
    state.setupData.opposingParty = document.getElementById('opposing-party').value;
    state.setupData.facts = document.getElementById('brief-facts').value;
    state.setupData.jurisdiction = document.getElementById('jurisdiction').value;
  }

  // Update steps
  state.setupStep = step;
  document.querySelectorAll('.setup-step').forEach(s => s.classList.add('hidden'));
  const stepEl = document.getElementById(`setup-step-${step}`);
  if (stepEl) {
    stepEl.classList.remove('hidden');
    console.log(`✓ Setup step ${step} displayed`);
  } else {
    console.error(`✗ Setup step ${step} element not found`);
  }

  // Update indicators
  document.querySelectorAll('.step-indicator').forEach((ind, i) => {
    ind.classList.toggle('active', i + 1 <= step);
  });
}

function enterCourtroom() {
  state.setupData.trapWarnings = document.getElementById('trap-warnings').checked;
  createNewSession();
}

// ════════════════════════════════════════════════════════════
// API INTEGRATION
// ════════════════════════════════════════════════════════════

async function createNewSession() {
  try {
    const briefingPhase = {
      round: 0,
      parties: {
        user: { side: state.setupData.side, client: state.setupData.userClient },
        opposing: { client: state.setupData.opposingParty }
      },
      legalIssues: state.setupData.issues,
      jurisdiction: state.setupData.jurisdiction,
      facts: state.setupData.facts
    };

    const requestBody = {
      case_title: state.setupData.title,
      jurisdiction: state.setupData.jurisdiction,
      user_side: state.setupData.side,
      user_client: state.setupData.userClient,
      opposing_party: state.setupData.opposingParty,
      legal_issues: state.setupData.issues,
      case_facts: state.setupData.facts,
      difficulty: state.setupData.difficulty,
      bench_type: state.setupData.bench,
      max_rounds: state.setupData.Length === 'brief' ? 3 : state.setupData.Length === 'extended' ? 8 : 5
    };

    const response = await fetch('/court/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    if (!response.ok) throw new Error('Failed to create session');
    
    const data = await response.json();
    state.currentSession = data.session_id;
    
    // Initialize courtroom with opening statement
    showScreen('courtroom');
    await loadSessionData();
    
    // Add opening statement to transcript
    setTimeout(() => {
      addTranscriptEntry('registrar', 'The court is now in session. ' + data.opening_statement || 'Proceedings begin.');
    }, 300);

  } catch (error) {
    console.error('Error creating session:', error);
    alert('Failed to create session. Please try again.');
  }
}

async function loadSessionData() {
  try {
    const response = await fetch(`/court/session/${state.currentSession}`);
    const data = await response.json();
    
    // Update UI with session info
    document.getElementById('court-case-title').textContent = data.case_title;
    document.getElementById('panel-case-title').textContent = data.case_title;
    document.getElementById('panel-issues').innerHTML = data.legal_issues
      .map(issue => `<span class="text-xs px-2 py-1 bg-primary-container text-on-primary-container rounded-full">${issue}</span>`)
      .join('');
    
    // Current bench
    const benchLabel = data.bench_type === 'single' ? 'Single Judge' : 
                       data.bench_type === 'division' ? 'Division Bench' : 'Constitutional Bench';
    document.getElementById('bench-label').textContent = benchLabel;
    
    // User side badge
    const sideText = data.user_side === 'petitioner' ? 'Petitioner' : 'Respondent';
    document.getElementById('user-side-badge').textContent = `You: ${sideText}`;
    
  } catch (error) {
    console.error('Error loading session:', error);
  }
}

async function submitArgument() {
  const textarea = document.getElementById('argument-input');
  const argument = textarea.value.trim();

  if (!argument) return;
  if (state.isWaitingForResponse) return;

  // Add user's argument to transcript
  addTranscriptEntry('user', argument);
  
  textarea.value = '';
  updateWordCount();
  state.isWaitingForResponse = true;
  
  try {
    // Show loading screen
    showScreen('loading');
    finishLoadingAnimation();

    const response = await fetch('/court/argue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.currentSession,
        user_argument: argument
      })
    });

    if (!response.ok) throw new Error('Argument submission failed');
    
    const data = await response.json();
    
    // Process responses
    if (data.trap_detected && state.setupData.trapWarnings) {
      showTrapWarning(data.trap_description);
    }

    // Add responses to transcript
    if (data.opposing_response) {
      setTimeout(() => addTranscriptEntry('opposing', data.opposing_response), 500);
    }
    if (data.judge_question) {
      setTimeout(() => addTranscriptEntry('judge', data.judge_question), 1000);
    }
    if (data.registrar_note) {
      setTimeout(() => addTranscriptEntry('registrar', data.registrar_note), 1500);
    }

    // Update metrics
    if (data.concessions) {
      data.concessions.forEach(c => {
        if (!state.concessions.includes(c)) {
          state.concessions.push(c);
          addConcession(c);
        }
      });
    }

    // Update round
    state.currentRound = data.round;
    updateRoundIndicator();

    // Check if session should end
    if (data.session_ended) {
      setTimeout(() => {
        showScreen('loading');
        finishLoadingAnimation();
        state.currentSession = data.session_id;
        showScreen('analysis');
      }, 2500);
    } else {
      setTimeout(() => showScreen('courtroom'), 2500);
    }

  } catch (error) {
    console.error('Error submitting argument:', error);
    alert('Error submitting argument. Please try again.');
    state.isWaitingForResponse = false;
    showScreen('courtroom');
  }
}

async function submitObjection() {
  const selectedType = document.querySelector('input[name="obj-type"]:checked');
  if (!selectedType) return;

  const objectionType = selectedType.value;
  let objectionText = objectionType;

  if (objectionType === 'custom') {
    objectionText = document.getElementById('custom-objection').value.trim();
    if (!objectionText) return;
  }

  try {
    const response = await fetch('/court/object', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.currentSession,
        objection_type: objectionType,
        objection_text: objectionText
      })
    });

    if (response.ok) {
      const data = await response.json();
      addTranscriptEntry('user', `[OBJECTION: ${objectionText}]`);
      if (data.judge_response) {
        addTranscriptEntry('judge', data.judge_response);
      }
      closeModal('objection-modal');
    }
  } catch (error) {
    console.error('Objection error:', error);
  }
}

async function submitDocumentRequest() {
  const docType = document.querySelector('input[name="doc-type"]:checked').value;
  const docSide = document.querySelector('input[name="doc-side"]:checked').value;

  try {
    state.isWaitingForResponse = true;
    const response = await fetch('/court/document', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.currentSession,
        document_type: docType,
        filed_by: docSide
      })
    });

    if (response.ok) {
      const data = await response.json();
      state.documents.push({
        id: state.documents.length,
        title: docType,
        content: data.document_content,
        filedBy: docSide,
        timestamp: new Date()
      });
      
      addTranscriptEntry('user', `[DOCUMENT PRODUCED: ${docType}]`);
      renderDocumentsList();
      closeModal('document-modal');
    }
  } catch (error) {
    console.error('Document error:', error);
  } finally {
    state.isWaitingForResponse = false;
  }
}

// ════════════════════════════════════════════════════════════
// TRANSCRIPT & UI UPDATES
// ════════════════════════════════════════════════════════════

function addTranscriptEntry(speaker, text) {
  const entry = {
    speaker,
    text,
    timestamp: new Date(),
    round: state.currentRound
  };
  state.transcript.push(entry);

  const container = document.getElementById('transcript');
  const entryEl = document.createElement('div');
  entryEl.className = 'transcript-entry';
  
  const speakerClass = `speaker-${speaker}`;
  const speakerLabel = {
    'judge': 'HON\'BLE BENCH',
    'opposing': 'OPPOSING COUNSEL',
    'user': 'YOUR SUBMISSION',
    'registrar': 'REGISTRAR'
  }[speaker] || speaker.toUpperCase();

  entryEl.innerHTML = `
    <div>
      <div class="speaker-pill ${speakerClass}">${speakerLabel}</div>
    </div>
    <div class="transcript-text">${text}</div>
  `;

  container.appendChild(entryEl);
  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}

function addConcession(text) {
  const list = document.getElementById('concessions-list');
  if (list.textContent.includes('No concessions')) {
    list.innerHTML = '';
  }
  
  const item = document.createElement('div');
  item.className = 'concession-item';
  item.innerHTML = `✓ ${text}`;
  list.appendChild(item);
  
  const count = state.concessions.length;
  document.getElementById('concession-count').textContent = count;
}

function updateWordCount() {
  const textarea = document.getElementById('argument-input');
  const count = textarea.value.length;
  document.getElementById('word-count').textContent = `${count} / 500`;
  
  if (count > 500) {
    textarea.value = textarea.value.substring(0, 500);
  }
}

function updateRoundIndicator() {
  document.getElementById('round-indicator').innerHTML = `
    <span class="material-symbols-outlined text-secondary text-sm">timer</span>
    <span class="font-mono text-primary text-sm font-bold">Round ${state.currentRound}</span>
  `;
}

function showTrapWarning(description) {
  const banner = document.getElementById('trap-banner');
  document.getElementById('trap-warning-text').textContent = description || 'Opposing counsel\'s last statement may contain a trap. Read carefully.';
  banner.classList.remove('hidden');
  
  setTimeout(() => {
    banner.classList.add('hidden');
  }, 8000);
}

function dismissTrap() {
  document.getElementById('trap-banner').classList.add('hidden');
}

// ════════════════════════════════════════════════════════════
// COURTROOM INITIALIZATION
// ════════════════════════════════════════════════════════════

function initializeCourtroom() {
  renderDocumentsList();
  updatePhaseHint();
  if (state.transcript.length === 0) {
    addTranscriptEntry('registrar', 'The court is now in session. Opening submissions begin. State your argument when ready.');
  }
}

function updatePhaseHint() {
  const hints = {
    0: 'Round 1 — Opening submissions',
    1: 'Round 2 — Main arguments',
    2: 'Round 3 — Counter-arguments',
    3: 'Round 4 — Rebuttal',
    4: 'Round 5 — Final submissions'
  };
  const maxRounds = state.setupData.Length === 'brief' ? 3 : state.setupData.Length === 'extended' ? 8 : 5;
  const hint = hints[state.currentRound] || `Round ${state.currentRound + 1} of ${maxRounds}`;
  document.getElementById('phase-hint').textContent = hint;
  document.getElementById('input-label').textContent = 
    state.currentRound === 0 ? 'YOUR OPENING STATEMENT' :
    state.currentRound === maxRounds - 1 ? 'YOUR CLOSING SUBMISSIONS' :
    'YOUR ARGUMENT';
}

function renderDocumentsList() {
  const list = document.getElementById('documents-list');
  if (state.documents.length === 0) {
    list.innerHTML = '<p class="text-primary/40 italic font-sans text-xs">None produced.</p>';
  } else {
    list.innerHTML = state.documents.map(doc => `
      <div onclick="viewDocument(${doc.id})" class="p-3 bg-white border border-outline-variant rounded-lg cursor-pointer hover:border-secondary text-xs">
        <p class="font-sans font-bold text-primary">${doc.title}</p>
        <p class="text-primary/50 text-[10px]">Filed by: ${doc.filedBy}</p>
      </div>
    `).join('');
  }
}

// ════════════════════════════════════════════════════════════
// MODAL MANAGEMENT
// ════════════════════════════════════════════════════════════

function openObjectionModal() {
  document.getElementById('objection-modal').classList.remove('hidden');
}

function openDocumentModal() {
  document.getElementById('document-modal').classList.remove('hidden');
}

function viewDocument(id) {
  const doc = state.documents.find(d => d.id === id);
  if (!doc) return;
  
  document.getElementById('doc-viewer-title').textContent = doc.title;
  document.getElementById('doc-viewer-meta').textContent = `Filed by: ${doc.filedBy === 'yours' ? 'Your Counsel' : 'Opposing Counsel'} — ${doc.timestamp.toLocaleString()}`;
  document.getElementById('doc-viewer-content').textContent = doc.content;
  document.getElementById('document-viewer-modal').classList.remove('hidden');
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.add('hidden');
}

function copyDocument() {
  const text = document.getElementById('doc-viewer-content').textContent;
  navigator.clipboard.writeText(text).then(() => {
    alert('Document copied to clipboard');
  });
}

// ════════════════════════════════════════════════════════════
// ANALYSIS SCREEN
// ════════════════════════════════════════════════════════════

async function renderAnalysis() {
  try {
    const response = await fetch(`/court/session/${state.currentSession}`);
    const sessionData = await response.json();

    // Parse analysis
    const analysis = sessionData.analysis || {};
    
    // Outcome and score
    document.getElementById('outcome-text').textContent = analysis.outcome || 'ANALYSIS PENDING';
    document.getElementById('outcome-reasoning').textContent = analysis.outcome_reasoning || 'Processing...';
    document.getElementById('score-display').textContent = analysis.score || '—';

    // Stats
    document.getElementById('stat-strong').textContent = analysis.strong_arguments_count || 0;
    document.getElementById('stat-weak').textContent = analysis.weak_arguments_count || 0;
    document.getElementById('stat-traps').textContent = analysis.traps_detected_count || 0;
    document.getElementById('stat-concessions').textContent = state.concessions.length;

    // Accordion sections
    const accordion = document.getElementById('analysis-accordion');
    accordion.innerHTML = '';

    const sections = analysis.sections || [
      { title: 'Argument Quality', content: 'Analysis generating...' },
      { title: 'Judge Perspective', content: 'Processing...' },
      { title: 'Weaknesses Identified', content: 'Analyzing...' }
    ];

    sections.forEach((section, idx) => {
      const item = document.createElement('div');
      item.className = 'accordion-item' + (idx === 0 ? ' open' : '');
      item.innerHTML = `
        <div class="accordion-header" onclick="toggleAccordion(this)">
          <div class="accordion-title">${section.title}</div>
          <span class="material-symbols-outlined accordion-icon">expand_more</span>
        </div>
        <div class="accordion-content">${section.content || 'No content available.'}</div>
      `;
      accordion.appendChild(item);
    });

    // Full transcript
    document.getElementById('full-transcript-text').textContent = state.transcript
      .map(e => `[${e.speaker.toUpperCase()}]\n${e.text}\n`)
      .join('\n');

    // Documents
    const docList = document.getElementById('analysis-documents-list');
    if (state.documents.length === 0) {
      docList.innerHTML = '<p class="text-primary/40 font-sans text-sm">No documents produced during this session.</p>';
    } else {
      docList.innerHTML = state.documents.map(doc => `
        <div class="clay-card p-5 rounded-xl cursor-pointer" onclick="viewDocument(${doc.id})">
          <h3 class="font-serif text-lg font-bold text-primary">${doc.title}</h3>
          <p class="text-primary/60 font-sans text-xs">Filed by ${doc.filedBy === 'yours' ? 'your counsel' : 'opposing counsel'}</p>
        </div>
      `).join('');
    }

  } catch (error) {
    console.error('Error rendering analysis:', error);
  }
}

function switchAnalysisTab(tab) {
  // Hide all
  document.getElementById('analysis-tab-content').style.display = 'none';
  document.getElementById('transcript-tab-content').style.display = 'none';
  document.getElementById('documents-tab-content').style.display = 'none';

  // Show target
  if (tab === 'analysis') {
    document.getElementById('analysis-tab-content').style.display = 'block';
  } else if (tab === 'transcript') {
    document.getElementById('transcript-tab-content').style.display = 'block';
  } else if (tab === 'documents') {
    document.getElementById('documents-tab-content').style.display = 'block';
  }

  // Update tab styling
  document.querySelectorAll('.analysis-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`tab-${tab}`).classList.add('active');
}

function toggleAccordion(header) {
  const item = header.parentElement;
  item.classList.toggle('open');
}

// ════════════════════════════════════════════════════════════
// SESSIONS MANAGEMENT
// ════════════════════════════════════════════════════════════

async function loadRecentSessions() {
  try {
    const response = await fetch('/court/sessions');
    const sessions = await response.json();
    
    const list = document.getElementById('recent-sessions-list');
    if (!sessions || sessions.length === 0) {
      list.innerHTML = '<div class="clay-card p-6 rounded-xl text-center text-primary/40 text-sm font-sans">No sessions yet.</div>';
      return;
    }

    list.innerHTML = sessions.slice(0, 3).map(session => `
      <div class="clay-card p-5 rounded-xl session-card" onclick="loadSessionForReview('${session.id}')">
        <h3 class="font-serif text-lg font-bold text-primary truncate">${session.case_title}</h3>
        <p class="text-primary/60 font-sans text-xs">${session.user_side === 'petitioner' ? 'Petitioner' : 'Respondent'}</p>
        <div class="session-meta">
          <div class="meta-item">
            <span class="material-symbols-outlined text-sm">timer</span>
            Round ${session.current_round}
          </div>
          <div class="meta-item">
            <span class="material-symbols-outlined text-sm">balance</span>
            ${session.bench_type || 'Division'}
          </div>
        </div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Error loading sessions:', error);
  }
}

async function loadAllSessions() {
  try {
    const response = await fetch('/court/sessions');
    const sessions = await response.json();
    
    const list = document.getElementById('all-sessions-list');
    if (!sessions || sessions.length === 0) {
      list.innerHTML = '<div class="clay-card p-8 rounded-xl text-center text-primary/40 font-sans">No sessions found. Start your first moot court.</div>';
      return;
    }

    list.innerHTML = sessions.map(session => `
      <div class="clay-card p-6 rounded-xl session-card" onclick="loadSessionForReview('${session.id}')">
        <h2 class="font-serif text-xl font-bold text-primary mb-2">${session.case_title}</h2>
        <div class="flex gap-6 mb-4 text-sm">
          <span class="font-sans"><strong>Your Role:</strong> ${session.user_side === 'petitioner' ? 'Petitioner' : 'Respondent'}</span>
          <span class="font-sans"><strong>Bench:</strong> ${session.bench_type || 'Division Bench'}</span>
        </div>
        <div class="flex gap-6 text-xs text-primary/60">
          <span>Rounds: ${session.current_round || 0}</span>
          <span>Status: ${session.is_completed ? 'Completed' : 'In Progress'}</span>
        </div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Error loading all sessions:', error);
  }
}

async function loadSessionForReview(sessionId) {
  try {
    const response = await fetch(`/court/session/${sessionId}`);
    const data = await response.json();

    state.currentSession = sessionId;
    state.currentRound = data.current_round;
    state.concessions = data.concessions || [];
    state.transcript = data.transcript || [];
    state.documents = data.documents || [];

    showScreen('analysis');
  } catch (error) {
    console.error('Error loading session:', error);
  }
}

function showImportFlow() {
  alert('Research session import feature coming soon. For now, start a new case directly.');
}

function confirmEndSession() {
  if (confirm('End this session and generate analysis? You cannot continue after this.')) {
    endSession();
  }
}

async function endSession() {
  try {
    const response = await fetch('/court/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.currentSession })
    });

    if (response.ok) {
      showScreen('loading');
      finishLoadingAnimation();
      setTimeout(() => showScreen('analysis'), 2000);
    }
  } catch (error) {
    console.error('Error ending session:', error);
    alert('Error ending session.');
  }
}

// ════════════════════════════════════════════════════════════
// LOADING ANIMATION
// ════════════════════════════════════════════════════════════

function finishLoadingAnimation() {
  for (let i = 1; i <= 4; i++) {
    setTimeout(() => {
      const pct = Math.min(100, 20 + i * 20);
      document.getElementById(`ls-${i}-bar`).style.width = `${pct}%`;
      document.getElementById(`ls-${i}-pct`).textContent = `${pct}%`;
    }, i * 400);
  }
}

// ════════════════════════════════════════════════════════════
// UTILITIES
// ════════════════════════════════════════════════════════════

function updateLobbyTime() {
  const now = new Date();
  const time = now.toLocaleTimeString('en-US', { 
    hour12: true, 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit' 
  });
  const element = document.getElementById('lobby-clock');
  if (element) element.textContent = time;
}

// ════════════════════════════════════════════════════════════
// PAGE LOAD HELPERS
// ════════════════════════════════════════════════════════════

document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.ctrlKey && state.currentScreen === 'courtroom') {
    submitArgument();
  }
});
