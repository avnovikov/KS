/* Molten Fort single-march proxy board for /optimiser/molten-fort. */
(function () {
  "use strict";

  var statusEl = document.getElementById("molten-status");
  var errorEl = document.getElementById("molten-error");
  var summaryEl = document.getElementById("molten-summary");
  var scoreEl = document.getElementById("molten-score");
  var chipsEl = document.getElementById("governor-chips");
  var marchesEl = document.getElementById("molten-marches");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("molten-regen");

  function fmtPct(n) {
    return Number(n || 0).toFixed(1) + "%";
  }

  function fmtRatio(ratio) {
    if (!ratio) return "—";
    return (
      Math.round((ratio.infantry || 0) * 100) +
      "/" +
      Math.round((ratio.cavalry || 0) * 100) +
      "/" +
      Math.round((ratio.archers || 0) * 100)
    );
  }

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
    var setChip = document.createElement("span");
    setChip.className = "chip";
    setChip.textContent =
      "Set " +
      (gov.set_tier || "—") +
      " · Def +" +
      fmtPct(gov.set_defense_pct) +
      " · Atk +" +
      fmtPct(gov.set_attack_pct) +
      " (in maps)";
    chipsEl.appendChild(setChip);
    ["infantry", "cavalry", "archers"].forEach(function (troop) {
      var chip = document.createElement("span");
      chip.className = "chip";
      var atk = (gov.attack_pct || {})[troop] || 0;
      var defn = (gov.defense_pct || {})[troop] || 0;
      chip.textContent = troop + " gov Atk " + fmtPct(atk) + " / Def " + fmtPct(defn);
      chipsEl.appendChild(chip);
    });

    marchesEl.innerHTML = "";
    var marches = data.marches || [];
    marches.forEach(function (march, idx) {
      if (!march) return;
      var card = document.createElement("article");
      card.className = "gov-card";
      var h = document.createElement("h2");
      h.textContent = "March " + (idx + 1);
      card.appendChild(h);
      var heroes = document.createElement("p");
      heroes.textContent =
        (march.hero_names || []).join(" · ") || "Governor-primary (no hero trio)";
      card.appendChild(heroes);
      var ratio = document.createElement("p");
      ratio.className = "muted";
      ratio.textContent =
        "Ratio " +
        fmtRatio(march.ratio) +
        " · cap " +
        (march.capacity || 0) +
        " · filled " +
        ((march.counts &&
          (march.counts.infantry || 0) +
            (march.counts.cavalry || 0) +
            (march.counts.archers || 0)) ||
          0);
      card.appendChild(ratio);
      var counts = document.createElement("p");
      counts.textContent =
        "I " +
        ((march.counts && march.counts.infantry) || 0) +
        " · C " +
        ((march.counts && march.counts.cavalry) || 0) +
        " · A " +
        ((march.counts && march.counts.archers) || 0);
      card.appendChild(counts);
      var score = document.createElement("p");
      score.textContent = "Proxy " + Number(march.score || 0).toFixed(0);
      card.appendChild(score);
      marchesEl.appendChild(card);
    });

    statusEl.textContent =
      "Ready · " +
      (data.active_marches || marches.filter(Boolean).length) +
      " active march";
  }

  async function load() {
    statusEl.textContent = "Solving march…";
    summaryEl.hidden = true;
    marchesEl.innerHTML = "";
    clearError();
    try {
      var res = await fetch("/api/optimize/molten-fort", { cache: "no-store" });
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
    regenBtn.addEventListener("click", function () {
      load();
    });
  }
  load();
})();
