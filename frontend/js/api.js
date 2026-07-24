/* ==========================================================================
   SpiderBot Control - API client
   All network calls to the backend live here so app.js only deals with
   already-parsed data. This file is served from the PC brain (spider_brain,
   port 9000), so BASE_URL is left empty (same-origin requests).

   Verified against the public repo (github.com/madscience2728/SpiderBot,
   master) on 2026-07-13: spider_brain/server.py, robot_client.py,
   tools.py, brain.py, llm_brain.py; spider_robot/relay_server.py.

   Key facts that shape this file:
   - /step and /llm_step each run exactly ONE observe-decide-act cycle
     (server.py is explicit: "Deliberately step-by-step rather than a
     continuous autonomous loop for now"). There is no server-side loop to
     start/stop. app.js simulates a loop by calling these repeatedly on a
     client-side timer.
   - /status returns last_sensors and history (no mode/running flag),
     since there's no server-side loop state to report.
   - Relay /sensors returns ultrasonic_cm (float) and timestamp (float).
   - Relay /gait actions are: stand, sit, forward, backward, turn left,
     turn right (spaces, not underscores, for the turn actions).
   - There is NO battery endpoint anywhere in the repo yet. /manual/battery
     below will 501 until that's added on the Pi side.
   - Camera feed does NOT stream through this API -- /manual/camera just
     returns the URL of vilib's own MJPEG server running on the Pi
     directly (see patches/spider_robot/relay_server.py). The <img> tag in
     the dashboard connects straight to that URL.
   ========================================================================== */

const API_BASE = ""; // same-origin; change if the UI is ever hosted separately

async function apiCall(path, options = {}) {
  try {
    const res = await fetch(API_BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, status: res.status, error: data.detail || ("HTTP " + res.status) };
    }
    return { ok: true, status: res.status, data: data };
  } catch (err) {
    return { ok: false, status: 0, error: err.message || "network error" };
  }
}

const api = {
  getStatus: function () { return apiCall("/status"); },
  getBrainHealth: function () { return apiCall("/health"); },
  runStep: function () { return apiCall("/step", { method: "POST" }); },
  runLLMStep: function () { return apiCall("/llm_step", { method: "POST" }); },
  stopLoop: function () { return apiCall("/stop", { method: "POST" }); },

  getHealth: function () { return apiCall("/manual/health"); },
  getSensors: function () { return apiCall("/manual/sensors"); },
  getBattery: function () { return apiCall("/manual/battery"); },
  getCamera: function () { return apiCall("/manual/camera"); },
  sendGait: function (action) {
    return apiCall("/manual/gait", {
      method: "POST",
      body: JSON.stringify({ action: action }),
    });
  },
};