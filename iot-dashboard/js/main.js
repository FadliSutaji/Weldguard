// ===== SHARED UTILITIES =====

// Clock
function startClock() {
  const el = document.getElementById('clock');
  const dateEl = document.getElementById('clock-date');
  if (!el) return;
  function tick() {
    const now = new Date();
    el.textContent = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    if (dateEl) {
      dateEl.textContent = now.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    }
  }
  tick();
  setInterval(tick, 1000);
}

// Toast notifications
function showToast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const icons = {
    success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" color="var(--green)"><polyline points="20 6 9 17 4 12"/></svg>`,
    danger:  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" color="var(--red)"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" color="var(--yellow)"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `${icons[type] || ''}<span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(20px)'; toast.style.transition = 'all 0.25s'; setTimeout(() => toast.remove(), 260); }, 3200);
}

// Animated counter
function animateCounter(el, target, duration = 1200, prefix = '', suffix = '') {
  if (!el) return;
  let start = 0;
  const step = Math.ceil(duration / target) > 0 ? Math.ceil(duration / target) : 1;
  const timer = setInterval(() => {
    start += Math.max(1, Math.ceil(target / 60));
    if (start >= target) { start = target; clearInterval(timer); }
    el.textContent = prefix + start + suffix;
  }, 1000 / 60);
}

// Modal helpers
function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add('open');
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove('open');
}

// Formatters
function fmtTime(date) {
  return date.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const COLORS = {
  orange: '#f97316', green: '#22c55e', red: '#ef4444',
  blue: '#3b82f6', cyan: '#06b6d4', yellow: '#eab308', purple:'#a855f7',
  muted: '#4a5980'
};

// Auto-detect backend URL based on current hostname
const _host = window.location.hostname || '127.0.0.1';
const API_BASE_URL = `http://${_host}:8000/api`;
const WS_URL = `ws://${_host}:8000/ws/updates`;

// Global Data
let STATIONS = [];
let INCIDENTS = [];
let WORKERS = [];

// Fetch Workers from Backend
async function fetchWorkers() {
  try {
    const res = await fetch(`${API_BASE_URL}/workers`);
    const data = await res.json();
    if (data.status === 'success') {
      WORKERS = data.data;
    }
    return WORKERS;
  } catch (err) {
    console.error("Gagal mengambil data pekerja", err);
    return [];
  }
}

// Send Relay Command (ON/OFF)
async function sendRelayCommand(stationId, command) {
  try {
    const res = await fetch(`${API_BASE_URL}/relay/${stationId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: command })
    });
    return await res.json();
  } catch (err) {
    console.error("Gagal mengirim perintah relay", err);
    return { status: "error", message: err.message };
  }
}

// Calculate KPIs
function calcKPIs() {
  const totalStations = STATIONS.length;
  const activeStations = STATIONS.filter(s => s.machine === 'ON').length;
  
  // Format today's date in local time YYYY-MM-DD
  const tzoffset = (new Date()).getTimezoneOffset() * 60000;
  const todayStr = (new Date(Date.now() - tzoffset)).toISOString().split('T')[0];
  
  const todayIncidents = INCIDENTS.filter(i => {
    return i.time && i.time.startsWith(todayStr);
  }).length;
  
  const safeStations = STATIONS.filter(s => s.status === 'safe').length;
  const safetyScore = totalStations ? Math.round((safeStations / totalStations) * 100) : 100;
  
  const activeWorkers = new Set(
    STATIONS.filter(s => s.machine === 'ON' && s.worker && s.worker !== 'Menunggu RFID...')
            .map(s => s.worker)
  ).size;

  return {
    totalStations,
    activeStations,
    todayIncidents,
    safetyScore,
    activeWorkers
  };
}

// WebSocket Connection
function connectWebSocket(onUpdate) {
  const ws = new WebSocket(WS_URL);
  
  ws.onopen = () => {
    const indicator = document.querySelector('.live-indicator');
    if (indicator) indicator.innerHTML = '<span class="live-dot"></span> WS CONNECTED';
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'init' || data.type === 'update') {
        const stationDict = data.stations || {};
        STATIONS = Object.keys(stationDict).map(id => {
          const s = stationDict[id];
          return {
            id: id,
            name: s.name,
            worker: s.worker,
            uid: s.uid,
            status: s.status,
            machine: s.machine,
            helm: s.apd_status?.welding_helmet ?? s.apd_status?.kacamata_las ?? false,
            kacamata_las: s.apd_status?.welding_helmet ?? s.apd_status?.kacamata_las ?? false
          };
        });
        
        INCIDENTS = data.incidents || [];
        INCIDENTS.sort((a, b) => new Date(b.time) - new Date(a.time));
        WORKERS = data.workers || [];
        
        if (onUpdate) onUpdate();
      }
    } catch (err) {
      console.error("Error parsing WS data", err);
    }
  };
  
  ws.onclose = () => {
    const indicator = document.querySelector('.live-indicator');
    if (indicator) indicator.innerHTML = '<span class="live-dot" style="background:var(--red)"></span> WS DISCONNECTED';
    setTimeout(() => connectWebSocket(onUpdate), 3000); // Reconnect
  };
}

function startDataPolling(onUpdate, interval = 2000) {
  connectWebSocket(onUpdate);
}

// Init on DOM load
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  // Close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });
  // Close modal buttons
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-close-modal');
      closeModal(id);
    });
  });
});
