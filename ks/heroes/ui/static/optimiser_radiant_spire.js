/* Radiant Spire — report marches like Event lineups (chips → one board). */
(function () {
  "use strict";

  var B = window.OptimiserBoard;
  if (!B) return;

  var statusEl = document.getElementById("radiant-status");
  var errorEl = document.getElementById("radiant-error");
  var scoreEl = document.getElementById("radiant-score");
  var engineEl = document.getElementById("radiant-engine");
  var chipsEl = document.getElementById("governor-chips");
  var modeChipsEl = document.getElementById("mode-chips");
  var boardEl = document.getElementById("board");
  var opponentEditEl = document.getElementById("radiant-opponent-edit");
  var opponentNoteEl = document.getElementById("opponent-note");
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

  var overrideRatioPct = null;
  var overrideBonuses = null;
  var fillingEditors = false;
  var chosenKey = "you-0";

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

  function marchScoreText(march, opponent) {
    if (opponent) return "opponent";
    var mc = march.breakdown && march.breakdown.mc ? march.breakdown.mc : null;
    if (mc) return "win " + Number(mc.win_rate || 0).toFixed(3);
    return "score " + Number(march.score || 0).toFixed(0);
  }

  function buildEntries(data) {
    var entries = [];
    (data.marches || []).forEach(function (march, idx) {
      if (!march) return;
      entries.push({
        key: "you-" + idx,
        label: "March " + (idx + 1),
        scoreText: marchScoreText(march, false),
        march: march,
        opponent: false,
        title: "Radiant Spire · March " + (idx + 1),
      });
    });
    var opp = data.opponent;
    if (opp && opp.marches) {
      opp.marches.forEach(function (march, idx) {
        if (!march) return;
        entries.push({
          key: "opp-" + idx,
          label: "Opponent " + (idx + 1),
          scoreText: marchScoreText(march, true),
          march: march,
          opponent: true,
          bonuses: march.bonuses || opp.bonuses,
          title: "Radiant Spire · Opponent " + (idx + 1),
        });
      });
    }
    return entries;
  }

  function appendBonusChipRow(board, bonuses) {
    var row = document.createElement("div");
    row.className = "chip-row";
    TROOPS.forEach(function (troop) {
      var b = (bonuses && bonuses[troop]) || {};
      B.appendChip(
        row,
        troop.slice(0, 3) +
          " Atk " +
          B.fmtPct(b.attack_pct) +
          " · Def " +
          B.fmtPct(b.defense_pct) +
          " · Leth " +
          B.fmtPct(b.lethality_pct) +
          " · HP " +
          B.fmtPct(b.health_pct)
      );
    });
    board.appendChild(row);
  }

  function renderSelectedBoard(entries) {
    var entry = null;
    entries.forEach(function (e) {
      if (e.key === chosenKey) entry = e;
    });
    if (!entry) entry = entries[0] || null;
    if (!entry) {
      boardEl.innerHTML = "";
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No feasible lineup for this roster.";
      boardEl.appendChild(empty);
      return;
    }
    chosenKey = entry.key;
    var scoreLine = entry.opponent
      ? null
      : marchScoreText(entry.march, false).replace(/^score /, "proxy ");
    if (!entry.opponent && entry.march.breakdown && entry.march.breakdown.mc) {
      scoreLine =
        "win rate " +
        Number(entry.march.breakdown.mc.win_rate || 0).toFixed(3) +
        " · proxy " +
        Number(
          (entry.march.breakdown.proxy && entry.march.breakdown.proxy.score) || 0
        ).toFixed(0);
    } else if (!entry.opponent) {
      scoreLine = "proxy " + Number(entry.march.score || 0).toFixed(0);
    }

    B.renderMarchReport(boardEl, {
      title: entry.title,
      meta: B.marchReportMeta(entry.march, scoreLine),
      heroes: entry.march.hero_names || [],
      opponent: entry.opponent,
      after: entry.opponent
        ? function (board) {
            appendBonusChipRow(board, entry.bonuses);
          }
        : null,
    });
  }

  function render(data) {
    clearError();
    lastPayload = data;
    if (data.proxy_banner) {
      bannerEl.textContent = data.proxy_banner;
    }

    var engine = data.engine || "proxy";
    if (scoreEl) {
      scoreEl.hidden = false;
      if (engine === "mc") {
        scoreEl.textContent =
          "Lineup win-rate score: " + Number(data.lineup_score || 0).toFixed(3);
      } else {
        scoreEl.textContent =
          "Lineup proxy score: " + Number(data.lineup_score || 0).toFixed(0);
      }
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
    B.appendChip(
      chipsEl,
      "Set " +
        (gov.set_tier || "—") +
        " · Def +" +
        B.fmtPct(gov.set_defense_pct) +
        " · Atk +" +
        B.fmtPct(gov.set_attack_pct)
    );
    TROOPS.forEach(function (troop) {
      var atk = (gov.attack_pct || {})[troop] || 0;
      var defn = (gov.defense_pct || {})[troop] || 0;
      B.appendChip(
        chipsEl,
        troop + " gov Atk " + B.fmtPct(atk) + " / Def " + B.fmtPct(defn)
      );
    });

    var hasOpp = !!(data.opponent && data.opponent.marches && data.opponent.marches.length);
    if (opponentEditEl) {
      opponentEditEl.hidden = !hasOpp;
      if (hasOpp) {
        if (opponentNoteEl) {
          opponentNoteEl.textContent =
            data.opponent.note ||
            "Edit ratio / bonuses from the battle report, then Apply.";
        }
        fillEditorsFromOpponent(data.opponent, data.floor);
      }
    }

    var entries = buildEntries(data);
    var keys = entries.map(function (e) {
      return e.key;
    });
    if (keys.indexOf(chosenKey) === -1) chosenKey = keys[0] || "you-0";

    function chooseMarch(key) {
      chosenKey = key;
      B.renderModeChips(modeChipsEl, entries, chosenKey, chooseMarch);
      renderSelectedBoard(entries);
    }

    B.renderModeChips(modeChipsEl, entries, chosenKey, chooseMarch);
    renderSelectedBoard(entries);

    statusEl.textContent =
      "Ready · " +
      (data.active_marches || (data.marches || []).filter(Boolean).length) +
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
    if (scoreEl) scoreEl.hidden = true;
    if (engineEl) engineEl.hidden = true;
    modeChipsEl.innerHTML = "";
    boardEl.innerHTML = "";
    if (opponentEditEl && !selectedFloor()) opponentEditEl.hidden = true;
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

  if (regenBtn) regenBtn.addEventListener("click", load);
  if (floorEl) {
    floorEl.addEventListener("change", function () {
      overrideRatioPct = null;
      overrideBonuses = null;
      chosenKey = "you-0";
      load();
    });
  }
  if (applyBtn) applyBtn.addEventListener("click", applyOpponentEdits);
  load();
})();
