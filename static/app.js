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

let socket = null;
let reconnectDelay = 1000;

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
  const n = Math.max(0, Math.floor(ms));
  if (n < 1000) {
    el.innerHTML = `<span class="duration__ms-only">${n.toLocaleString()} ms</span>`;
    return;
  }
  el.innerHTML =
    `<span class="duration__human">${formatHuman(n)}</span>` +
    `<span class="duration__ms">${n.toLocaleString()} ms</span>`;
}

function applyState(msg) {
  const isRed = msg.value === RED;
  indicator.classList.toggle("indicator--red", isRed);
  indicator.classList.toggle("indicator--blue", !isRed);
  indicator.setAttribute(
    "aria-label",
    isRed ? "Current state: red" : "Current state: blue"
  );

  setDuration(totalRedEl, msg.total_red_ms);
  setDuration(longestRedEl, msg.longest_red_ms);
  setDuration(totalBlueEl, msg.total_blue_ms);
  setDuration(longestBlueEl, msg.longest_blue_ms);
  setDuration(currentStreakEl, msg.current_streak_ms);
  indicatorCol.classList.toggle("indicator-col--red", isRed);
  indicatorCol.classList.toggle("indicator-col--blue", !isRed);
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws`);

  socket.addEventListener("open", () => {
    statusEl.textContent = "Connected";
    switchBtn.disabled = false;
    reconnectDelay = 1000;
  });

  socket.addEventListener("message", (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "state") applyState(msg);
    } catch {
      /* ignore malformed */
    }
  });

  socket.addEventListener("close", () => {
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

connect();
