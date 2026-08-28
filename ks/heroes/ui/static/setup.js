(function () {
  "use strict";

  var STORAGE_KEY = "ks.setup.v1";
  var SESSION_DISMISS = "ks.setup.dismiss_welcome";

  var slugById = {
    heroes: "1-heroes",
    gear: "2-gear",
    troops: "3-troops",
    governor: "4-governor",
  };

  var slugByNumber = {
    1: "1-heroes",
    2: "2-gear",
    3: "3-troops",
    4: "4-governor",
  };

  function defaultInventoryPath() {
    var body = document.body;
    if (body && body.getAttribute("data-default-inventory")) {
      return body.getAttribute("data-default-inventory");
    }
    return "/inventory/heroes";
  }

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
    state = state || loadState();
    if (state.skipped || completedCount(state) >= 4) {
      el.textContent = "Setup complete";
      el.classList.add("is-complete");
      return;
    }
    var cur = Math.min(4, Math.max(1, state.current_step || 1));
    el.textContent = "Step " + cur + " of 4";
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

    var state = loadState();
    if (stepNumber > state.current_step) {
      state.current_step = stepNumber;
      saveState(state);
    }

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
        var s = loadState();
        s.skipped = true;
        saveState(s);
        window.location.href = defaultInventoryPath();
      });
    }

    state = loadState();
    if (state.completed[stepId] && nextLink) nextLink.hidden = false;
    refreshHeaderPill(state);
    applyStepperProgress(state);
  }

  function bindDonePage() {
    var state = loadState();
    stepIds().forEach(function (id) {
      state.completed[id] = true;
    });
    state.current_step = 5;
    saveState(state);
  }

  function redirectToResume() {
    var state = loadState();
    if (state.skipped || completedCount(state) >= 4) {
      window.location.replace(defaultInventoryPath());
      return;
    }
    var step = Math.min(4, Math.max(1, state.current_step || 1));
    var slug = slugByNumber[step] || slugById.heroes;
    if (completedCount(state) >= 4) {
      window.location.replace("/setup/done");
      return;
    }
    window.location.replace("/setup/" + slug);
  }

  function applyStepperProgress(state) {
    state = state || loadState();
    var items = document.querySelectorAll(".setup-stepper-item[data-step-id]");
    items.forEach(function (item) {
      var id = item.getAttribute("data-step-id");
      if (id && state.completed[id]) {
        item.classList.add("is-done");
      }
    });
  }

  function maybeShowWelcomeBanner() {
    var state = loadState();
    if (state.skipped || completedCount(state) >= 4) return;
    if (sessionStorage.getItem(SESSION_DISMISS)) return;
    var path = window.location.pathname || "";
    if (path.indexOf("/setup") === 0 || path.indexOf("/help") === 0) return;
    if (path !== "/" && path.indexOf("/inventory") !== 0) return;
    var banner = document.getElementById("setup-welcome");
    if (!banner) return;
    banner.hidden = false;
    var start = document.getElementById("setup-welcome-start");
    var dismiss = document.getElementById("setup-welcome-dismiss");
    if (start) {
      start.addEventListener("click", function () {
        sessionStorage.setItem(SESSION_DISMISS, "1");
        window.location.href = "/setup";
      });
    }
    if (dismiss) {
      dismiss.addEventListener("click", function () {
        sessionStorage.setItem(SESSION_DISMISS, "1");
        banner.hidden = true;
      });
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    refreshHeaderPill(loadState());
    bindInventoryNudgeByBody();
    maybeShowWelcomeBanner();
  });

  window.SetupPage = {
    initStep: bindStepPage,
    initDone: bindDonePage,
    redirectToResume: redirectToResume,
    markSetupStep: markStep,
  };
  window.markSetupStep = markStep;
})();
