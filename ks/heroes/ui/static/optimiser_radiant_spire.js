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
  var bonusEditEl = document.getElementById("opponent-bonus-edit");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("radiant-regen");
  var floorEl = document.getElementById("radiant-floor");
  var applyBtn = document.getElementById("opponent-apply");
  var ratioI = document.getElementById("opp-ratio-i");
  var ratioC = document.getElementById("opp-ratio-c");
  var ratioA = document.getElementById("opp-ratio-a");

  var TROOPS = ["infantry", "cavalry", "archers"];
  var BONUS_KEYS = [
    { key: "attack_pct", label: "Atk" },
    { key: "defense_pct", label: "Def" },
    { key: "lethality_pct", label: "Leth" },
    { key: "health_pct", label: "HP" },
  ];

  /** Last applied overrides (null = use YAML stub). Cleared on floor change. */
  var overrideRatioPct = null;
  var overrideBonuses = null;
  var fillingEditors = false;

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

  function ensureBonusEditors() {
    if (!bonusEditEl || bonusEditEl.childNodes.length) return;
    TROOPS.forEach(function (troop) {
      var box = document.createElement("div");
      box.className = "bonus-troop";
      var title = document.createElement("strong");
      title.textContent = troop;
      box.appendChild(title);
      BONUS_KEYS.forEach(function (spec) {
        var lab = document.createElement("label");
        lab.appendChild(document.createTextNode(spec.label));
        var inp = document.createElement("input");
        inp.type = "number";
        inp.step = "0.1";
        inp.min = "0";
        inp.dataset.troop = troop;
        inp.dataset.bonus = spec.key;
        lab.appendChild(inp);
        box.appendChild(lab);
      });
      bonusEditEl.appendChild(box);
    });
  }

  function readRatioPct() {
    return {
      infantry: Number(ratioI && ratioI.value),
      cavalry: Number(ratioC && ratioC.value),
      archers: Number(ratioA && ratioA.value),
    };
  }

  function readBonuses() {
    ensureBonusEditors();
    var out = {};
    TROOPS.forEach(function (troop) {
      out[troop] = {};
      BONUS_KEYS.forEach(function (spec) {
        var inp = bonusEditEl.querySelector(
          'input[data-troop="' + troop + '"][data-bonus="' + spec.key + '"]'
        );
        out[troop][spec.key] = Number(inp && inp.value) || 0;
      });
    });
    return out;
  }

  function fillEditorsFromOpponent(opp, floorMeta) {
    fillingEditors = true;
    ensureBonusEditors();
    var ratio =
      (overrideRatioPct && {
        infantry: overrideRatioPct.infantry / 100,
        cavalry: overrideRatioPct.cavalry / 100,
        archers: overrideRatioPct.archers / 100,
      }) ||
      (opp && opp.marches && opp.marches[0] && opp.marches[0].ratio) ||
      (floorMeta && floorMeta.enemy_ratio) ||
      {};
    if (ratioI) ratioI.value = String(Math.round((ratio.infantry || 0) * 100));
    if (ratioC) ratioC.value = String(Math.round((ratio.cavalry || 0) * 100));
    if (ratioA) ratioA.value = String(Math.round((ratio.archers || 0) * 100));

    var bonuses =
      overrideBonuses ||
      (opp && opp.bonuses) ||
      (floorMeta && floorMeta.enemy_bonuses) ||
      {};
    TROOPS.forEach(function (troop) {
      var row = bonuses[troop] || {};
      BONUS_KEYS.forEach(function (spec) {
        var inp = bonusEditEl.querySelector(
          'input[data-troop="' + troop + '"][data-bonus="' + spec.key + '"]'
        );
        if (inp) inp.value = String(Number(row[spec.key] || 0));
      });
    });
    fillingEditors = false;
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
        "Edit ratio / bonuses from the battle report, then Apply.";
    }
    fillEditorsFromOpponent(opp, data.floor);
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
      var chipRow = document.createElement("div");
      chipRow.className = "chip-row";
      var bonuses = march.bonuses || opp.bonuses || {};
      TROOPS.forEach(function (troop) {
        var b = bonuses[troop] || {};
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
        chipRow.appendChild(chip);
      });
      card.appendChild(chipRow);
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
        if (data.floor.overrides_applied) bits.push("overrides on");
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
    TROOPS.forEach(function (troop) {
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

  function buildUrl() {
    var floor = selectedFloor();
    var url = "/api/optimize/radiant-spire";
    var params = [];
    if (floor != null) {
      params.push("floor=" + encodeURIComponent(String(floor)));
    }
    if (floor != null && overrideRatioPct) {
      params.push("enemy_infantry=" + encodeURIComponent(String(overrideRatioPct.infantry)));
      params.push("enemy_cavalry=" + encodeURIComponent(String(overrideRatioPct.cavalry)));
      params.push("enemy_archers=" + encodeURIComponent(String(overrideRatioPct.archers)));
    }
    if (floor != null && overrideBonuses) {
      params.push(
        "enemy_bonuses=" + encodeURIComponent(JSON.stringify(overrideBonuses))
      );
    }
    if (params.length) url += "?" + params.join("&");
    return url;
  }

  async function load() {
    statusEl.textContent = "Solving marches…";
    summaryEl.hidden = true;
    marchesEl.innerHTML = "";
    if (opponentEl && !selectedFloor()) {
      opponentEl.hidden = true;
      if (opponentMarchesEl) opponentMarchesEl.innerHTML = "";
    }
    clearError();
    try {
      var res = await fetch(buildUrl(), { cache: "no-store" });
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

  function applyOpponentEdits() {
    if (fillingEditors) return;
    if (selectedFloor() == null) {
      showError("Select a floor before editing the opponent.");
      return;
    }
    var pct = readRatioPct();
    if (
      !Number.isFinite(pct.infantry) ||
      !Number.isFinite(pct.cavalry) ||
      !Number.isFinite(pct.archers)
    ) {
      showError("Opponent ratio I/C/A must be numbers.");
      return;
    }
    if (pct.infantry + pct.cavalry + pct.archers <= 0) {
      showError("Opponent ratio must sum to a positive value.");
      return;
    }
    overrideRatioPct = pct;
    overrideBonuses = readBonuses();
    load();
  }

  if (regenBtn) {
    regenBtn.addEventListener("click", function () {
      load();
    });
  }
  if (floorEl) {
    floorEl.addEventListener("change", function () {
      overrideRatioPct = null;
      overrideBonuses = null;
      load();
    });
  }
  if (applyBtn) {
    applyBtn.addEventListener("click", applyOpponentEdits);
  }
  load();
})();
