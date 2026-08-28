(function () {
  "use strict";

  var STORAGE_KEY = "ks.setup.v1";

  function defaultState() {
    return {
      version: 1,
      skipped: false,
      current_step: 1,
      completed: {
        heroes: false,
        gear: false,
        troops: false,
        governor: false,
      },
      dismissed_banners: {},
    };
  }

  function loadState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState();
      var parsed = JSON.parse(raw);
      var base = defaultState();
      base.skipped = !!parsed.skipped;
      base.current_step = parsed.current_step || 1;
      if (parsed.completed && typeof parsed.completed === "object") {
        Object.keys(base.completed).forEach(function (key) {
          if (key in parsed.completed) base.completed[key] = !!parsed.completed[key];
        });
      }
      if (parsed.dismissed_banners && typeof parsed.dismissed_banners === "object") {
        base.dismissed_banners = parsed.dismissed_banners;
      }
      return base;
    } catch (_err) {
      return defaultState();
    }
  }

  function saveState(state) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    refreshHeaderPill(state);
  }

  function stepIds() {
    return ["heroes", "gear", "troops", "governor"];
  }

  function completedCount(state) {
    return stepIds().filter(function (id) {
      return state.completed[id];
    }).length;
  }

  function refreshHeaderPill(state) {
    var el = document.getElementById("setup-pill");
    if (!el) return;
    var done = completedCount(state);
    if (done >= 4) {
      el.textContent = "Setup complete";
      el.classList.add("is-complete");
      return;
    }
    el.textContent = "Setup " + done + "/4";
    el.classList.remove("is-complete");
  }

  function markStep(stepId) {
    var state = loadState();
    if (!(stepId in state.completed)) return state;
    state.completed[stepId] = true;
    var idx = stepIds().indexOf(stepId);
    if (idx >= 0 && state.current_step <= idx + 1) {
      state.current_step = Math.min(4, idx + 2);
    }
    saveState(state);
    return state;
  }

  function bindStepPage(stepNumber, stepId) {
    var markBtn = document.getElementById("setup-mark-done");
    var nextLink = document.getElementById("setup-next");
    var skipBtn = document.getElementById("setup-skip");

    function revealNext() {
      if (nextLink) nextLink.hidden = false;
    }

    if (markBtn) {
      markBtn.addEventListener("click", function () {
        markStep(stepId);
        revealNext();
        if (window.showToast) window.showToast("Step marked complete", true);
      });
    }

    if (skipBtn) {
      skipBtn.addEventListener("click", function () {
        var state = loadState();
        state.skipped = true;
        saveState(state);
        window.location.href = "/inventory/heroes";
      });
    }

    var state = loadState();
    if (state.completed[stepId] && nextLink) nextLink.hidden = false;
    refreshHeaderPill(state);
  }

  function bindDonePage() {
    var state = loadState();
    stepIds().forEach(function (id) {
      state.completed[id] = true;
    });
    state.current_step = 5;
    saveState(state);
  }

  function maybeRedirectToSetup() {
    var state = loadState();
    if (state.skipped || completedCount(state) >= 4) return;
    if (sessionStorage.getItem("ks.setup.dismiss_redirect")) return;
    var path = window.location.pathname || "";
    if (path.indexOf("/setup") === 0 || path.indexOf("/help") === 0) return;
    if (path === "/" || path.indexOf("/inventory") === 0) {
      sessionStorage.setItem("ks.setup.dismiss_redirect", "1");
      window.location.replace("/setup");
    }
  }

  function bindInventoryNudge(stepId, label) {
    var nudge = document.getElementById("setup-nudge");
    if (!nudge || !stepId) return;
    var state = loadState();
    if (state.skipped || state.completed[stepId]) return;
    if (state.dismissed_banners && state.dismissed_banners[stepId]) return;
    var text = document.getElementById("setup-nudge-text");
    var link = document.getElementById("setup-nudge-link");
    var dismiss = document.getElementById("setup-nudge-dismiss");
    if (text) text.textContent = "Setup: finish " + label + ". ";
    if (link && slugById[stepId]) link.href = "/setup/" + slugById[stepId];
    nudge.hidden = false;
    if (dismiss) {
      dismiss.addEventListener("click", function () {
        var s = loadState();
        s.dismissed_banners = s.dismissed_banners || {};
        s.dismissed_banners[stepId] = true;
        saveState(s);
        nudge.hidden = true;
      });
    }
  }

  var slugById = {
    heroes: "1-heroes",
    gear: "2-gear",
    troops: "3-troops",
    governor: "4-governor",
  };

  function bindInventoryNudgeByBody() {
    var stepId = document.body && document.body.getAttribute("data-setup-step");
    if (!stepId) return;
    var labels = {
      heroes: "Heroes",
      gear: "Gear",
      troops: "Troops",
      governor: "Governor charms",
    };
    bindInventoryNudge(stepId, labels[stepId] || stepId);
    var link = document.getElementById("setup-nudge-link");
    if (link && slugById[stepId]) link.href = "/setup/" + slugById[stepId];
  }

  document.addEventListener("DOMContentLoaded", function () {
    refreshHeaderPill(loadState());
    bindInventoryNudgeByBody();
    maybeRedirectToSetup();
  });

  window.SetupPage = {
    initStep: bindStepPage,
    initDone: bindDonePage,
    markSetupStep: markStep,
  };
  window.markSetupStep = markStep;
})();
