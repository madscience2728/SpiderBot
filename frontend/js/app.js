/* ==========================================================================
   SpiderBot Control - app logic
   Tab switching, polling, button wiring, and rendering. Kept as plain,
   readable DOM code (no framework) so it's easy to extend with new panels
   later (see the #panel-extra slot in index.html).

   Verified against the public repo on 2026-07-13 - see js/api.js header
   for the specifics. Biggest change from the first draft: /step and
   /llm_step are single cycles, not a server-side loop, so "AI Control"
   here just calls one of them repeatedly on a timer and stops on request.

   Camera feed added 2026-07-13: the <img> connects DIRECTLY to the Pi
   (vilib's own MJPEG server, not proxied through this app) -- see
   initCamera() below and INTEGRATION_NOTES.md.
   ========================================================================== */

var POLL_INTERVAL_MS = 2000;   // how often we refresh sensors/health when idle
var AUTO_STEP_DELAY_MS = 1000; // pause between cycles while the client-side loop runs
var GAIT_ACTIONS = ["stand", "sit", "forward", "backward", "turn left", "turn right"];

var state = {
  activeTab: "manual",
  autoLoopActive: false, // true while the client-side step timer is running
  autoLoopMode: "mock",  // "mock" | "llm"
  autoLoopTimer: null,
};

// ---------------------------------------------------------------------------
// Event log (bottom footer) - lightweight audit trail of UI actions/errors
// ---------------------------------------------------------------------------

function logEvent(msg, isError) {
  isError = isError || false;
  var el = document.getElementById("event-log");
  var line = document.createElement("div");
  var time = new Date().toLocaleTimeString();
  line.textContent = "[" + time + "] " + msg;
  if (isError) line.classList.add("err");
  el.prepend(line);
  while (el.children.length > 100) el.removeChild(el.lastChild);
}

// ---------------------------------------------------------------------------
// Status chip helpers
// ---------------------------------------------------------------------------

function setChip(id, chipState, value) {
  var chip = document.getElementById(id);
  chip.dataset.state = chipState; // "ok" | "warn" | "error" | "unknown"
  chip.querySelector(".value").textContent = value;
}

function updateBrainChip() {
  setChip(
    "chip-brain",
    state.autoLoopActive ? "ok" : "unknown",
    state.autoLoopActive ? (state.autoLoopMode + " loop running") : "idle"
  );
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

function initTabs() {
  var buttons = document.querySelectorAll(".toggle-btn");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tab = btn.dataset.tab;
      state.activeTab = tab;
      buttons.forEach(function (b) { b.classList.toggle("active", b === btn); });
      document.getElementById("panel-manual").classList.toggle("active", tab === "manual");
      document.getElementById("panel-ai").classList.toggle("active", tab === "ai");
    });
  });
}

// ---------------------------------------------------------------------------
// Sensor rendering (shared by the idle poll and by loop-step responses)
// ---------------------------------------------------------------------------

function renderSensorReading(sensors) {
  var el = document.getElementById("sensor-distance");
  if (sensors && typeof sensors.ultrasonic_cm === "number") {
    el.textContent = sensors.ultrasonic_cm.toFixed(1) + " cm";
  } else {
    el.textContent = "-- cm";
  }
}

// ---------------------------------------------------------------------------
// Manual control
// ---------------------------------------------------------------------------

function setManualLocked(locked) {
  document.querySelectorAll(".gait-btn").forEach(function (b) { b.disabled = locked; });
  document.getElementById("manual-lock-hint").hidden = !locked;
}

function initGaitButtons() {
  document.querySelectorAll(".gait-btn").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      var action = btn.dataset.action;
      if (GAIT_ACTIONS.indexOf(action) === -1) return;
      btn.disabled = true;
      var res = await api.sendGait(action);
      btn.disabled = state.autoLoopActive;
      if (res.ok) {
        logEvent("Sent gait command: " + action);
      } else if (res.status === 409) {
        logEvent("Gait command \"" + action + "\" rejected: robot busy", true);
      } else {
        logEvent("Gait command \"" + action + "\" failed: " + res.error, true);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Decision log
// ---------------------------------------------------------------------------

function addDecisionLogEntry(action, detail) {
  var list = document.getElementById("decision-log");
  var empty = list.querySelector(".empty");
  if (empty) empty.remove();

  var li = document.createElement("li");
  var time = new Date().toLocaleTimeString();
  li.innerHTML = "<span class=\"action\">" + action + "</span><span>" + (detail || "") + " - " + time + "</span>";
  list.prepend(li);

  while (list.children.length > 25) list.removeChild(list.lastChild);
}

// Seed the log with recent history from /status on page load (server keeps
// the last 10 actions taken, per server.py's _history[-10:]).
async function seedDecisionLogFromStatus() {
  var res = await api.getStatus();
  if (!res.ok) return;
  var d = res.data || {};
  if (d.last_sensors) renderSensorReading(d.last_sensors);
  if (Array.isArray(d.history)) {
    d.history.forEach(function (action) { addDecisionLogEntry(action, "from history"); });
  }
}

// ---------------------------------------------------------------------------
// AI control - client-side repeating loop over /step or /llm_step
// ---------------------------------------------------------------------------

function handleStepResult(mode, data) {
  if (data.sensors) renderSensorReading(data.sensors);

  if (mode === "mock" && data.action) {
    addDecisionLogEntry(data.action, "mock");
  } else if (mode === "llm") {
    if (data.tool_chosen) {
      addDecisionLogEntry(data.tool_chosen, "llm");
    } else if (data.reason) {
      addDecisionLogEntry("(no action)", data.reason);
    }
  }
}

async function autoLoopTick() {
  if (!state.autoLoopActive) return;

  var call = state.autoLoopMode === "llm" ? api.runLLMStep : api.runStep;
  var res = await call();

  if (res.ok) {
    handleStepResult(state.autoLoopMode, res.data || {});
  } else if (res.status === 409) {
    logEvent("Step skipped: previous step still in progress", false);
  } else {
    logEvent("Step failed: " + res.error, true);
  }

  if (state.autoLoopActive) {
    state.autoLoopTimer = setTimeout(autoLoopTick, AUTO_STEP_DELAY_MS);
  }
}

function initAiButtons() {
  document.getElementById("btn-ai-start").addEventListener("click", function () {
    if (state.autoLoopActive) return;
    var mode = document.querySelector('input[name="ai-mode"]:checked').value;
    state.autoLoopActive = true;
    state.autoLoopMode = mode;
    setManualLocked(true);
    updateBrainChip();
    var endpointName = mode === "llm" ? "llm_step" : "step";
    logEvent("Started client-side " + mode + " loop (one /" + endpointName + " call every " + AUTO_STEP_DELAY_MS + "ms)");
    autoLoopTick();
  });

  document.getElementById("btn-ai-stop").addEventListener("click", async function () {
    state.autoLoopActive = false;
    clearTimeout(state.autoLoopTimer);
    updateBrainChip();
    setManualLocked(false);
    var res = await api.stopLoop();
    if (res.ok) {
      logEvent("Loop stopped, robot sitting");
    } else {
      logEvent("Stop command failed: " + res.error, true);
    }
  });
}

// ---------------------------------------------------------------------------
// Camera feed
// The <img> connects directly to the Pi (vilib's own MJPEG server on port
// 9000, per relay_server.py's startup hook) rather than proxying frame
// bytes through the brain -- much simpler and more reliable for a
// continuous multipart stream. The brain only tells us the URL to use and
// whether the relay reports the camera as running.
// ---------------------------------------------------------------------------

function setCameraStatus(text, hasSignal) {
  document.getElementById("camera-status").textContent = text;
  document.getElementById("camera-placeholder").style.display = hasSignal ? "none" : "flex";
}

async function initCamera() {
  var img = document.getElementById("camera-feed");
  var reconnectBtn = document.getElementById("btn-camera-reconnect");
  var streamUrl = null;

  img.onload = function () { setCameraStatus("live", true); };
  img.onerror = function () { setCameraStatus("stream error - try Reconnect", false); };

  var res = await api.getCamera();
  if (!res.ok || !res.data || !res.data.stream_url) {
    setCameraStatus("unavailable (relay unreachable)", false);
    return;
  }

  streamUrl = res.data.stream_url;

  if (res.data.available === false) {
    setCameraStatus("camera not wired up on the Pi yet", false);
    return;
  }
  if (res.data.started === false) {
    setCameraStatus("camera present but not started", false);
    return;
  }

  setCameraStatus("connecting...", false);
  img.src = streamUrl;

  reconnectBtn.addEventListener("click", function () {
    if (!streamUrl) return;
    setCameraStatus("reconnecting...", false);
    img.src = streamUrl + "?t=" + Date.now();
  });
}

// ---------------------------------------------------------------------------
// Idle polling - health, connection, battery, and manual-tab sensor reading.
// Runs continuously regardless of tab/loop state so the header stays live.
// ---------------------------------------------------------------------------

async function pollHealth() {
  var results = await Promise.all([api.getBrainHealth(), api.getHealth()]);
  var brain = results[0];
  var relay = results[1];
  setChip("chip-connection", relay.ok ? "ok" : "error", relay.ok ? "online" : "offline");

  if (brain.ok && relay.ok) {
    setChip("chip-health", "ok", "healthy");
  } else if (brain.ok && !relay.ok) {
    setChip("chip-health", "warn", "brain up, Pi unreachable");
  } else {
    setChip("chip-health", "error", "unreachable");
  }
}

async function pollSensors() {
  // Only fetch fresh sensors here when the auto-loop isn't already doing it
  // via its own step responses -- avoids redundant calls to the relay.
  if (state.autoLoopActive) return;
  var res = await api.getSensors();
  if (res.ok) renderSensorReading(res.data);
}

// Robot HAT's pack is a 2x 18650 (2S) Li-ion battery, rated 6.0V (empty) to
// 8.4V (full) per SunFounder's own docs. Real Li-ion discharge isn't linear
// (voltage sags fast near both ends, flatter in the middle), so this is a
// simple linear approximation across that rated range -- good enough for an
// at-a-glance percentage, not a precise coulomb-counting fuel gauge.
var BATTERY_MIN_V = 6.0;
var BATTERY_MAX_V = 8.4;

function voltageToPercent(v) {
  var pct = ((v - BATTERY_MIN_V) / (BATTERY_MAX_V - BATTERY_MIN_V)) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

async function pollBattery() {
  var res = await api.getBattery();
  if (res.ok && res.data && typeof res.data.voltage === "number") {
    var v = res.data.voltage;
    var pct = voltageToPercent(v);
    // Color thresholds still key off raw voltage, mirroring Robot HAT V4's
    // own LED indicator (confirmed against SunFounder's official docs):
    // >7.6V both LEDs on (healthy), 7.15-7.6V one LED on (getting low),
    // <7.15V both off (critical).
    var label = v > 7.6 ? "ok" : (v >= 7.15 ? "warn" : "error");
    setChip("chip-battery", label, pct + "% (" + v.toFixed(2) + "V)");
  } else {
    setChip("chip-battery", "unknown", "n/a");
  }
}

async function pollIdle() {
  await Promise.all([pollHealth(), pollSensors(), pollBattery()]);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", function () {
  initTabs();
  initGaitButtons();
  initAiButtons();
  updateBrainChip();
  logEvent("Dashboard loaded");
  seedDecisionLogFromStatus();
  initCamera();
  pollIdle();
  setInterval(pollIdle, POLL_INTERVAL_MS);
});