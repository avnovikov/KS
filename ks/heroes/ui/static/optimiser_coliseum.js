/* Coliseum — report the march like Event lineups (chip → one board). */
(function () {
  "use strict";

  var B = window.OptimiserBoard;
  if (!B) return;

  var statusEl = document.getElementById("coliseum-status");
  var errorEl = document.getElementById("coliseum-error");
  var scoreEl = document.getElementById("coliseum-score");
  var chipsEl = document.getElementById("governor-chips");
  var modeChipsEl = document.getElementById("mode-chips");
  var boardEl = document.getElementById("board");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("coliseum-regen");
  var gearSheet = B.bindGearSheet();

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
    if (scoreEl) {
      scoreEl.hidden = false;
      scoreEl.textContent =
        "Lineup proxy score: " + Number(data.lineup_score || 0).toFixed(0);
    }

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

    var march = (data.marches || []).filter(Boolean)[0] || null;
    var entries = march
      ? [
          {
            key: "march-0",
            label: "March 1",
            scoreText: "score " + Number(march.score || 0).toFixed(0),
          },
        ]
      : [];
    B.renderModeChips(modeChipsEl, entries, "march-0", function () {});

    if (!march) {
      boardEl.innerHTML = "";
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No feasible lineup for this roster.";
      boardEl.appendChild(empty);
    } else {
      B.renderMarchReport(boardEl, {
        title: "Coliseum · March",
        meta: B.marchReportMeta(
          march,
          "proxy " + Number(march.score || 0).toFixed(0)
        ),
        heroes: march.hero_names || [],
        onHeroClick: function (name) {
          var assignment = march.gear_assignment || {};
          gearSheet.open(name, "Coliseum · March", assignment[name]);
        },
      });
    }

    statusEl.textContent = "Ready · " + (march ? 1 : 0) + " march(es)";
  }

  async function load() {
    statusEl.textContent = "Solving march…";
    if (scoreEl) scoreEl.hidden = true;
    modeChipsEl.innerHTML = "";
    boardEl.innerHTML = "";
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

  if (regenBtn) regenBtn.addEventListener("click", load);
  load();
})();
