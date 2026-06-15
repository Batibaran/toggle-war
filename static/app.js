const RED = 0;
const BLUE = 1;

const indicator = document.getElementById("indicator");
const switchBtn = document.getElementById("switch");
const statusEl = document.getElementById("status");

const indicatorCol = document.querySelector(".indicator-col");
const currentStreakEl = document.getElementById("current-streak");

const totalRedEl = document.getElementById("total-red");
const longestRedEl = document.getElementById("longest-red");

const totalBlueEl = document.getElementById("total-blue");
const longestBlueEl = document.getElementById("longest-blue");

const totalTimeEl = document.getElementById("total-time"); let socket = null;

let reconnectDelay = 1000;
let cooldownTimer = null;
let suppressReconnect = false;

const TOKEN_KEY = "toggleWarToken";

const authForm = document.getElementById("auth-form");
const authUsername = document.getElementById("auth-username");
const authPassword = document.getElementById("auth-password");
const registerBtn = document.getElementById("register-btn");
const logoutBtn = document.getElementById("logout-btn");
const authAccount = document.getElementById("auth-account");
const accountName = document.getElementById("account-name");
const authError = document.getElementById("auth-error");

const playerStats = document.getElementById("player-stats");
const psTotal = document.getElementById("ps-total");
const psRed = document.getElementById("ps-red");
const psBlue = document.getElementById("ps-blue");
const psSince = document.getElementById("ps-since");
const psLast = document.getElementById("ps-last");

function showCooldown() {
  switchBtn.disabled = true;
  statusEl.textContent = "Slow down…";
  clearTimeout(cooldownTimer);
  cooldownTimer = setTimeout(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      switchBtn.disabled = false;
      statusEl.textContent = "Connected";
    }
  }, 1000);
}

function formatHuman(ms) {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (min < 60) return remSec ? `${min}m ${remSec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin ? `${hr}h ${remMin}m` : `${hr}h`;
}

function setDuration(el, ms) {
  if (!el) return;

  const n = Math.max(0, Math.floor(ms));
  el.innerHTML =
    `<span class="duration__human">${formatHuman(n)}</span>` +
    `<span class="duration__ms">${n.toLocaleString()} ms</span>`;
}

function setFavicon(color) {
  let link = document.getElementById('favicon');
  if (!link) {
    link = document.createElement('link');
    link.id = 'favicon';
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="${color}"/></svg>`;
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function applyState(msg) {
  const isRed = msg.value === RED;
  indicator.classList.toggle("indicator--red", isRed);
  indicator.classList.toggle("indicator--blue", !isRed);
  indicator.setAttribute(
    "aria-label",
    isRed ? "Current state: red" : "Current state: blue",
  );

  const totalTimeMs = Number(msg.total_red_ms || 0) + Number(msg.total_blue_ms || 0);

  setDuration(totalTimeEl, totalTimeMs);
  setDuration(totalRedEl, msg.total_red_ms);
  setDuration(longestRedEl, msg.longest_red_ms);
  setDuration(totalBlueEl, msg.total_blue_ms);
  setDuration(longestBlueEl, msg.longest_blue_ms);
  setDuration(currentStreakEl, msg.current_streak_ms);
  indicatorCol.classList.toggle("indicator-col--red", isRed);
  indicatorCol.classList.toggle("indicator-col--blue", !isRed);

  setFavicon(isRed ? '#c62828' : '#1565c0');
}

function formatDate(iso, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return withTime ? d.toLocaleString() : d.toLocaleDateString();
}

function applyUserStats(msg) {
  psTotal.textContent = Number(msg.toggle_count || 0).toLocaleString();
  psRed.textContent = Number(msg.toggles_to_red || 0).toLocaleString();
  psBlue.textContent = Number(msg.toggles_to_blue || 0).toLocaleString();
  psSince.textContent = formatDate(msg.member_since);
  psLast.textContent = formatDate(msg.last_active, true);
}

function setLoggedIn(username, stats) {
  accountName.textContent = username;
  authForm.hidden = true;
  authAccount.hidden = false;
  authError.textContent = "";
  playerStats.hidden = false;
  if (stats) applyUserStats(stats);
}

function setLoggedOut() {
  authForm.hidden = false;
  authAccount.hidden = true;
  playerStats.hidden = true;
  authPassword.value = "";
}

function reconnect() {
  if (
    socket &&
    (socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING)
  ) {
    suppressReconnect = true;
    socket.close();
  }
  reconnectDelay = 1000;
  connect();
}

async function submitAuth(path) {
  const username = authUsername.value.trim();
  const password = authPassword.value;
  authError.textContent = "";
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      authError.textContent = data.error || "Something went wrong.";
      return;
    }
    localStorage.setItem(TOKEN_KEY, data.token);
    setLoggedIn(data.username, data.stats);
    reconnect();
  } catch {
    authError.textContent = "Network error.";
  }
}

async function logout() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    try {
      await fetch("/api/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      /* best effort */
    }
  }
  localStorage.removeItem(TOKEN_KEY);
  setLoggedOut();
  reconnect();
}

async function checkSession() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    setLoggedOut();
    return;
  }
  try {
    const res = await fetch("/api/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      setLoggedIn(data.username, data.stats);
    } else {
      localStorage.removeItem(TOKEN_KEY);
      setLoggedOut();
    }
  } catch {
    setLoggedOut();
  }
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const token = localStorage.getItem(TOKEN_KEY);
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  socket = new WebSocket(`${protocol}//${location.host}/ws${query}`);

  socket.addEventListener("open", () => {
    statusEl.textContent = "Connected";
    switchBtn.disabled = false;
    reconnectDelay = 1000;
  });

  socket.addEventListener("message", (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "state") applyState(msg);
      if (msg.type === "rate_limited") showCooldown();
      if (msg.type === "user_stats") applyUserStats(msg);
    } catch {
      /* ignore malformed */
    }
  });

  socket.addEventListener("close", () => {
    if (suppressReconnect) {
      suppressReconnect = false;
      return;
    }
    switchBtn.disabled = true;
    statusEl.textContent = "Reconnecting…";
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
  });

  socket.addEventListener("error", () => {
    socket.close();
  });
}

switchBtn.addEventListener("click", () => {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "toggle" }));
  }
});

authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth("/api/login");
});
registerBtn.addEventListener("click", () => submitAuth("/api/register"));
logoutBtn.addEventListener("click", logout);

checkSession();
connect();
