/* Radiant Spire dual-march proxy board for /optimiser/radiant-spire. */
(function () {
  "use strict";

  var statusEl = document.getElementById("radiant-status");
  var errorEl = document.getElementById("radiant-error");
  var summaryEl = document.getElementById("radiant-summary");
  var scoreEl = document.getElementById("radiant-score");
  var engineEl = document.getElementById("radiant-engine");
  var chipsEl = document.getElementById("governor-chips");
  var marchesEl = document.getElementById("radiant-marches");
  var opponentEl = document.getElementById("radiant-opponent");
  var opponentNoteEl = document.getElementById("opponent-note");
  var opponentMarchesEl = document.getElementById("opponent-marches");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("radiant-regen");
  var floorEl = document.getElementById("radiant-floor");

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

  function selectedFloor() {
    if (!floorEl) return null;
    var v = String(floorEl.value || "").trim();
    if (!v) return null;
    var n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
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

  function appendBonusChips(parent, bonuses) {
    var row = document.createElement("div");
    row.className = "chip-row";
    ["infantry", "cavalry", "archers"].forEach(function (troop) {
      var b = (bonuses && bonuses[troop]) || {};
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent =
        troop.slice(0, 3) +
        " Atk " +
        fmtPct(b.attack_pct) +
        " · Def " +
        fmtPct(b.defense_pct) +
        " · Leth " +
        fmtPct(b.lethality_pct) +
        " · HP " +
        fmtPct(b.health_pct);
      row.appendChild(chip);
    });
    parent.appendChild(row);
  }

  function renderOpponent(data) {
    if (!opponentEl || !opponentMarchesEl) return;
    var opp = data.opponent;
    if (!opp || !opp.marches || !opp.marches.length) {
      opponentEl.hidden = true;
      opponentMarchesEl.innerHTML = "";
      return;
    }
    opponentEl.hidden = false;
    if (opponentNoteEl) {
      opponentNoteEl.textContent =
        opp.note ||
        "Troop mix from floor stub; bonuses from battle report YAML (display only).";
    }
    opponentMarchesEl.innerHTML = "";
    opp.marches.forEach(function (march, idx) {
      if (!march) return;
      var card = document.createElement("article");
      card.className = "gov-card opponent";
      var h = document.createElement("h2");
      h.textContent = "Opponent march " + (idx + 1);
      card.appendChild(h);
      var heroes = document.createElement("p");
      heroes.textContent = (march.hero_names || ["AI", "AI", "AI"]).join(" · ");
      card.appendChild(heroes);
      var ratio = document.createElement("p");
      ratio.className = "muted";
      ratio.textContent =
        "Ratio " +
        fmtRatio(march.ratio) +
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
      appendBonusChips(card, march.bonuses || opp.bonuses);
      opponentMarchesEl.appendChild(card);
    });
  }

  function render(data) {
    clearError();
    if (data.proxy_banner) {
      bannerEl.textContent = data.proxy_banner;
    }
    summaryEl.hidden = false;
    var engine = data.engine || "proxy";
    if (engine === "mc") {
      scoreEl.textContent =
        "Lineup win-rate score: " + Number(data.lineup_score || 0).toFixed(3);
    } else {
      scoreEl.textContent =
        "Lineup proxy score: " + Number(data.lineup_score || 0).toFixed(0);
    }
    if (engineEl) {
      var bits = ["Engine: " + engine];
      if (data.floor && data.floor.floor != null) {
        bits.push("floor " + data.floor.floor);
        bits.push(
          "enemy scale ×" + Number(data.floor.enemy_power_scale || 0).toFixed(2)
        );
      }
      if (data.warnings && data.warnings.length) {
        bits.push(data.warnings.join("; "));
      }
      engineEl.hidden = false;
      engineEl.textContent = bits.join(" · ");
    }

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
      fmtPct(gov.set_attack_pct);
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
      heroes.textContent = (march.hero_names || []).join(" · ");
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
      var mc =
        march.breakdown && march.breakdown.mc ? march.breakdown.mc : null;
      if (mc) {
        score.textContent =
          "Win rate " +
          Number(mc.win_rate || 0).toFixed(3) +
          " · proxy " +
          Number((march.breakdown.proxy && march.breakdown.proxy.score) || 0).toFixed(0);
      } else {
        score.textContent = "Proxy " + Number(march.score || 0).toFixed(0);
      }
      card.appendChild(score);
      marchesEl.appendChild(card);
    });

    renderOpponent(data);

    statusEl.textContent =
      "Ready · " +
      (data.active_marches || marches.filter(Boolean).length) +
      " active marches · " +
      engine;
  }

  async function load() {
    statusEl.textContent = "Solving marches…";
    summaryEl.hidden = true;
    marchesEl.innerHTML = "";
    if (opponentEl) opponentEl.hidden = true;
    if (opponentMarchesEl) opponentMarchesEl.innerHTML = "";
    clearError();
    try {
      var floor = selectedFloor();
      var url = "/api/optimize/radiant-spire";
      if (floor != null) {
        url += "?floor=" + encodeURIComponent(String(floor));
      }
      var res = await fetch(url, { cache: "no-store" });
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
  if (floorEl) {
    floorEl.addEventListener("change", function () {
      load();
    });
  }
  load();
})();
