/* Coliseum single-march board — Event-lineups board chrome via OptimiserBoard. */
(function () {
  "use strict";

  var B = window.OptimiserBoard;
  if (!B) return;

  var statusEl = document.getElementById("coliseum-status");
  var errorEl = document.getElementById("coliseum-error");
  var summaryEl = document.getElementById("coliseum-summary");
  var scoreEl = document.getElementById("coliseum-score");
  var chipsEl = document.getElementById("governor-chips");
  var marchesEl = document.getElementById("coliseum-marches");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("coliseum-regen");

  function showError(msg) {
    errorEl.hidden = false;
    errorEl.textContent = msg;
    statusEl.textContent = "Failed.";
  }

  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  function render(data) {
    clearError();
    if (data.proxy_banner) {
      bannerEl.textContent = data.proxy_banner;
    }
    summaryEl.hidden = false;
    scoreEl.textContent =
      "Lineup proxy score: " + Number(data.lineup_score || 0).toFixed(0);

    var gov = data.governor || {};
    chipsEl.innerHTML = "";
    B.appendChip(chipsEl, "Governor weight 0 (heroes + gear primary)");
    ["infantry", "cavalry", "archers"].forEach(function (troop) {
      var atk = (gov.attack_pct || {})[troop] || 0;
      var defn = (gov.defense_pct || {})[troop] || 0;
      B.appendChip(
        chipsEl,
        troop + " gov Atk " + B.fmtPct(atk) + " / Def " + B.fmtPct(defn)
      );
    });

    marchesEl.innerHTML = "";
    var marches = data.marches || [];
    marches.forEach(function (march, idx) {
      if (!march) return;
      B.appendMarchBoard(marchesEl, {
        title: "March " + (idx + 1),
        meta:
          "Ratio " +
          B.fmtRatio(march.ratio) +
          " · cap " +
          (march.capacity || 0) +
          " · " +
          B.fmtCounts(march.counts) +
          " · Proxy " +
          Number(march.score || 0).toFixed(0),
        heroes: march.hero_names || [],
      });
    });

    statusEl.textContent =
      "Ready · " + marches.filter(Boolean).length + " march(es)";
  }

  async function load() {
    statusEl.textContent = "Solving march…";
    summaryEl.hidden = true;
    marchesEl.innerHTML = "";
    clearError();
    try {
      var res = await fetch("/api/optimize/coliseum", { cache: "no-store" });
      var body = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        showError(body.detail || ("Optimize failed: " + res.status));
        return;
      }
      render(body);
    } catch (err) {
      showError(String(err));
    }
  }

  if (regenBtn) {
    regenBtn.addEventListener("click", load);
  }
  load();
})();
