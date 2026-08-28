/* Coliseum — stage·round input first; Generate solves; opponent overrides via GET/PUT (2 marches). */
(function () {
  "use strict";

  var B = window.OptimiserBoard;
  if (!B) return;

  var statusEl = document.getElementById("coliseum-status");
  var errorEl = document.getElementById("coliseum-error");
  var scoreEl = document.getElementById("coliseum-score");
  var engineEl = document.getElementById("coliseum-engine");
  var chipsEl = document.getElementById("governor-chips");
  var modeChipsEl = document.getElementById("mode-chips");
  var boardEl = document.getElementById("board");
  var opponentEditEl = document.getElementById("coliseum-opponent-edit");
  var opponentNoteEl = document.getElementById("opponent-note");
  var heroEditEl = document.getElementById("opponent-hero-edit");
  var troopEditEl = document.getElementById("opponent-troop-edit");
  var bonusEditEl = document.getElementById("opponent-bonus-edit");
  var bannerEl = document.getElementById("proxy-banner");
  var regenBtn = document.getElementById("coliseum-regen");
  var regenInlineBtn = document.getElementById("coliseum-regen-inline");
  var stageEl = document.getElementById("coliseum-stage");
  var roundEl = document.getElementById("coliseum-round");
  var eventTierEl = document.getElementById("coliseum-event-tier");
  var eventSizeEl = document.getElementById("coliseum-event-march-size");
  var eventTroopsApplyBtn = document.getElementById("coliseum-event-troops-apply");
  var applyBtn = document.getElementById("opponent-apply");
  var copyOtherBtn = document.getElementById("opponent-copy-other");

  var TROOPS = ["infantry", "cavalry", "archers"];
  var TROOP_LABEL = { infantry: "Infantry", cavalry: "Cavalry", archers: "Archers" };
  var BONUS_KEYS = [
    { key: "attack_pct", label: "Atk" },
    { key: "defense_pct", label: "Def" },
    { key: "lethality_pct", label: "Leth" },
    { key: "health_pct", label: "HP" },
  ];

  var fillingEditors = false;
  var chosenKey = "opp-0";
  var catalogNames = [];
  var catalogByTroop = { infantry: [], cavalry: [], archers: [] };
  var classHeroPicker = null;
  var lastOptimizeData = null;
  var opponentLoadSeq = 0;
  var generating = false;
  var gearSheet = B.bindGearSheet();

  function syncGenerateEnabled() {
    var ok = !!selectedStageRound() && !generating;
    [regenBtn, regenInlineBtn].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = !ok;
      btn.title = ok
        ? "Generate marches for this stage · round"
        : generating
          ? "Solving…"
          : "Set stage and round first, then Generate";
    });
  }

  function parsePositiveInt(el) {
    if (!el) return null;
    var v = String(el.value || "").trim();
    if (!v) return null;
    var n = Number(v);
    if (!Number.isFinite(n) || n < 1 || Math.floor(n) !== n) return null;
    return n;
  }

  /** Both stage and round required for opponent panel / MC stub. */
  function selectedStageRound() {
    var stage = parsePositiveInt(stageEl);
    var round = parsePositiveInt(roundEl);
    if (stage == null || round == null) return null;
    return { stage: stage, round: round };
  }

  function isOpponentKey(key) {
    return String(key || "").indexOf("opp-") === 0;
  }

  function opponentSlotFromKey(key) {
    var m = /^opp-(\d+)$/.exec(String(key || ""));
    return m ? Number(m[1]) : null;
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

  function emptyMarch() {
    return {
      hero_names: ["", "", ""],
      hero_level: null,
      gear_enhancement: null,
      levels: { infantry: 6, cavalry: 6, archers: 6 },
      counts: { infantry: 0, cavalry: 0, archers: 0 },
      bonuses: {
        infantry: {
          attack_pct: 0,
          defense_pct: 0,
          lethality_pct: 0,
          health_pct: 0,
        },
        cavalry: {
          attack_pct: 0,
          defense_pct: 0,
          lethality_pct: 0,
          health_pct: 0,
        },
        archers: {
          attack_pct: 0,
          defense_pct: 0,
          lethality_pct: 0,
          health_pct: 0,
        },
      },
    };
  }

  function normalizeMarches(marches) {
    var out = [emptyMarch(), emptyMarch()];
    if (!Array.isArray(marches)) return out;
    for (var i = 0; i < 2; i++) {
      if (marches[i]) out[i] = marches[i];
    }
    return out;
  }


  function fillEventTroops(data) {
    var pet = (data && data.player_event_troops) || {};
    if (eventTierEl && pet.tier != null) eventTierEl.value = String(pet.tier);
    if (eventSizeEl && pet.march_size != null) {
      eventSizeEl.value = String(pet.march_size);
    }
  }

  function readEventTroopsBody() {
    var tier = Number(eventTierEl && eventTierEl.value);
    var size = Number(eventSizeEl && eventSizeEl.value);
    if (!Number.isFinite(tier) || tier < 1 || tier > 11 || Math.floor(tier) !== tier) {
      return { error: "Troop tier must be an integer 1–11." };
    }
    if (!Number.isFinite(size) || size < 1 || Math.floor(size) !== size) {
      return { error: "March size must be an integer >= 1." };
    }
    return { body: { tier: tier, march_size: size } };
  }

  function eventTroopsPutUrl(sr) {
    return (
      "/api/mystic-trial/coliseum-event-troops/" +
      encodeURIComponent(String(sr.stage)) +
      "/" +
      encodeURIComponent(String(sr.round))
    );
  }

  async function putEventTroops(sr, body) {
    var res = await fetch(eventTroopsPutUrl(sr), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    var payload = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      throw new Error(payload.detail || "Save event troops failed: " + res.status);
    }
    fillEventTroops(payload);
    return payload;
  }

  async function saveEventTroops() {
    var sr = selectedStageRound();
    if (!sr) {
      showError("Enter stage and round before saving event troops.");
      return;
    }
    var checked = readEventTroopsBody();
    if (checked.error) {
      showError(checked.error);
      return;
    }
    statusEl.textContent = "Saving event troops…";
    try {
      await putEventTroops(sr, checked.body);
      statusEl.textContent =
        "Event troops saved (T" +
        checked.body.tier +
        " · " +
        checked.body.march_size +
        "). Press Generate when ready.";
      clearError();
    } catch (err) {
      showError(String(err && err.message ? err.message : err));
    }
  }

  function ingestCatalog(data) {
    if (Array.isArray(data.catalog_hero_names) && data.catalog_hero_names.length) {
      catalogNames = data.catalog_hero_names.slice();
    }
    if (data.catalog_by_troop && typeof data.catalog_by_troop === "object") {
      catalogByTroop = {
        infantry: (data.catalog_by_troop.infantry || []).slice(),
        cavalry: (data.catalog_by_troop.cavalry || []).slice(),
        archers: (data.catalog_by_troop.archers || []).slice(),
      };
    }
  }

  function ensureHeroEditors() {
    if (!heroEditEl) return;
    var pickerHost = heroEditEl.querySelector(".class-hero-picker-host");
    if (!pickerHost) {
      heroEditEl.innerHTML = "";
      pickerHost = document.createElement("div");
      pickerHost.className = "class-hero-picker-host";
      heroEditEl.appendChild(pickerHost);
      var shared = document.createElement("div");
      shared.className = "opponent-heroes-shared";
      var levelLab = document.createElement("label");
      levelLab.appendChild(document.createTextNode("Hero level"));
      var levelInp = document.createElement("input");
      levelInp.type = "number";
      levelInp.min = "1";
      levelInp.step = "1";
      levelInp.dataset.field = "hero_level";
      levelLab.appendChild(levelInp);
      shared.appendChild(levelLab);
      var gearLab = document.createElement("label");
      gearLab.appendChild(document.createTextNode("Gold gear +"));
      var gearInp = document.createElement("input");
      gearInp.type = "number";
      gearInp.min = "0";
      gearInp.step = "1";
      gearInp.dataset.field = "gear_enhancement";
      gearLab.appendChild(gearInp);
      shared.appendChild(gearLab);
      heroEditEl.appendChild(shared);
    }
    if (!classHeroPicker) {
      classHeroPicker = B.mountClassHeroPicker(pickerHost, {
        byTroop: catalogByTroop,
        selected: ["", "", ""],
      });
    } else {
      classHeroPicker.refresh(catalogByTroop);
    }
  }

  function readHeroEdits() {
    ensureHeroEditors();
    var names = classHeroPicker
      ? classHeroPicker.getSelection()
      : ["", "", ""];
    var levelInp = heroEditEl.querySelector('input[data-field="hero_level"]');
    var gearInp = heroEditEl.querySelector(
      'input[data-field="gear_enhancement"]'
    );
    var heroLevel = Number(levelInp && levelInp.value);
    var gearEnh = Number(gearInp && gearInp.value);
    return {
      hero_names: names,
      hero_level: Number.isFinite(heroLevel) ? Math.floor(heroLevel) : null,
      gear_enhancement: Number.isFinite(gearEnh) ? Math.floor(gearEnh) : null,
    };
  }

  function ensureTroopEditors() {
    if (!troopEditEl || troopEditEl.childNodes.length) return;
    TROOPS.forEach(function (troop) {
      var box = document.createElement("div");
      box.className = "troop-count-box";
      var title = document.createElement("strong");
      title.textContent = TROOP_LABEL[troop] || troop;
      box.appendChild(title);

      var levelLab = document.createElement("label");
      levelLab.appendChild(document.createTextNode("Level"));
      var levelInp = document.createElement("input");
      levelInp.type = "number";
      levelInp.min = "1";
      levelInp.max = "11";
      levelInp.step = "1";
      levelInp.dataset.troop = troop;
      levelInp.dataset.field = "level";
      levelLab.appendChild(levelInp);
      box.appendChild(levelLab);

      var countLab = document.createElement("label");
      countLab.appendChild(document.createTextNode("Count"));
      var countInp = document.createElement("input");
      countInp.type = "number";
      countInp.min = "0";
      countInp.step = "1";
      countInp.dataset.troop = troop;
      countInp.dataset.field = "count";
      countLab.appendChild(countInp);
      box.appendChild(countLab);

      troopEditEl.appendChild(box);
    });
  }

  function ensureBonusEditorsIn(container) {
    if (!container || container.childNodes.length) return;
    TROOPS.forEach(function (troop) {
      var box = document.createElement("div");
      box.className = "bonus-troop";
      var title = document.createElement("strong");
      title.textContent = TROOP_LABEL[troop] || troop;
      box.appendChild(title);
      BONUS_KEYS.forEach(function (spec) {
        var lab = document.createElement("label");
        lab.appendChild(document.createTextNode(spec.label));
        var inp = document.createElement("input");
        inp.type = "number";
        inp.step = "any";
        inp.min = "0";
        inp.dataset.troop = troop;
        inp.dataset.bonus = spec.key;
        inp.title =
          "Percent-points or game total (e.g. 160.2 / 60.2 / 0.602); shown as entered";
        lab.appendChild(inp);
        box.appendChild(lab);
      });
      container.appendChild(box);
    });
  }

  function ensureBonusEditors() {
    ensureBonusEditorsIn(bonusEditEl);
  }

  function readTroopEdits() {
    ensureTroopEditors();
    var levels = {};
    var counts = {};
    TROOPS.forEach(function (troop) {
      var levelInp = troopEditEl.querySelector(
        'input[data-troop="' + troop + '"][data-field="level"]'
      );
      var countInp = troopEditEl.querySelector(
        'input[data-troop="' + troop + '"][data-field="count"]'
      );
      levels[troop] = Number(levelInp && levelInp.value);
      counts[troop] = Number(countInp && countInp.value);
    });
    return { levels: levels, counts: counts };
  }

  function readBonusesFrom(container) {
    ensureBonusEditorsIn(container);
    var out = {};
    TROOPS.forEach(function (troop) {
      out[troop] = {};
      BONUS_KEYS.forEach(function (spec) {
        var inp = container.querySelector(
          'input[data-troop="' + troop + '"][data-bonus="' + spec.key + '"]'
        );
        out[troop][spec.key] = Number(inp && inp.value) || 0;
      });
    });
    return out;
  }

  function fillBonusesInto(container, bonuses) {
    ensureBonusEditorsIn(container);
    var bonusSrc = bonuses || {};
    TROOPS.forEach(function (troop) {
      var row = bonusSrc[troop] || {};
      BONUS_KEYS.forEach(function (spec) {
        var inp = container.querySelector(
          'input[data-troop="' + troop + '"][data-bonus="' + spec.key + '"]'
        );
        if (inp) inp.value = String(Number(row[spec.key] || 0));
      });
    });
  }

  function readBonuses() {
    return readBonusesFrom(bonusEditEl);
  }

  function fillEditorsFromMarch(march, bonuses) {
    fillingEditors = true;
    ensureHeroEditors();
    ensureTroopEditors();
    ensureBonusEditors();

    var names = (march && march.hero_names) || ["", "", ""];
    if (classHeroPicker) {
      classHeroPicker.setSelection(names);
    }
    var levelInp = heroEditEl.querySelector('input[data-field="hero_level"]');
    var gearInp = heroEditEl.querySelector(
      'input[data-field="gear_enhancement"]'
    );
    if (levelInp) {
      levelInp.value =
        march && march.hero_level != null ? String(march.hero_level) : "";
    }
    if (gearInp) {
      gearInp.value =
        march && march.gear_enhancement != null
          ? String(march.gear_enhancement)
          : "";
    }

    var levels = (march && march.levels) || {};
    var counts = (march && march.counts) || {};
    TROOPS.forEach(function (troop) {
      var levelTroop = troopEditEl.querySelector(
        'input[data-troop="' + troop + '"][data-field="level"]'
      );
      var countInp = troopEditEl.querySelector(
        'input[data-troop="' + troop + '"][data-field="count"]'
      );
      if (levelTroop) levelTroop.value = String(Number(levels[troop] || 6));
      if (countInp) countInp.value = String(Math.round(Number(counts[troop] || 0)));
    });

    var bonusSrc = bonuses || (march && march.bonuses) || {};
    fillBonusesInto(bonusEditEl, bonusSrc);
    fillingEditors = false;
  }

  function syncEditorsToSelection(entries) {
    var entry = null;
    (entries || []).forEach(function (e) {
      if (e.key === chosenKey) entry = e;
    });
    if (entry && entry.opponent) {
      fillEditorsFromMarch(entry.march, entry.bonuses);
      if (opponentNoteEl) {
        opponentNoteEl.textContent =
          "Editing " +
          entry.label +
          " — pick one Inf / Cav / Arch hero (portrait grid), shared level & gold gear +, troops, bonuses. Apply saves.";
      }
      var slot = opponentSlotFromKey(chosenKey);
      if (copyOtherBtn && slot != null) {
        var other = slot === 0 ? 1 : 0;
        copyOtherBtn.hidden = false;
        copyOtherBtn.textContent = "Copy to Opponent " + (other + 1);
      }
    } else {
      if (opponentNoteEl) {
        opponentNoteEl.textContent =
          "Select an opponent march below. Pick Infantry / Cavalry / Archers from the portrait grid, then hero level, gold gear +, troop counts, and bonuses.";
      }
      if (copyOtherBtn) copyOtherBtn.hidden = true;
    }
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
        title: "Coliseum · March " + (idx + 1),
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
          title: "Coliseum · Opponent " + (idx + 1),
        });
      });
    }
    return entries;
  }

  function fmtBonus(n) {
    var x = Number(n);
    if (!Number.isFinite(x)) return "—";
    if (Math.abs(x - Math.round(x)) < 1e-9) return String(Math.round(x));
    var s = x.toFixed(6).replace(/\.?0+$/, "");
    return s || "0";
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
          fmtBonus(b.attack_pct) +
          " · Def " +
          fmtBonus(b.defense_pct) +
          " · Leth " +
          fmtBonus(b.lethality_pct) +
          " · HP " +
          fmtBonus(b.health_pct)
      );
    });
    board.appendChild(row);
  }

  function appendTroopChipRow(board, march) {
    var row = document.createElement("div");
    row.className = "chip-row";
    var levels = (march && march.levels) || {};
    var counts = (march && march.counts) || {};
    TROOPS.forEach(function (troop) {
      var levelBit =
        levels[troop] != null ? " T" + String(levels[troop]) + " · " : " ";
      B.appendChip(
        row,
        troop.slice(0, 3) + levelBit + B.fmtPoints(counts[troop] || 0)
      );
    });
    board.appendChild(row);
  }

  function contributionRowFromMarch(march) {
    var b = (march && march.breakdown) || {};
    if (!b.contributions || !b.formation_totals) return null;
    return {
      stat_family: b.stat_family || "expedition",
      contributions: b.contributions,
      formation_totals: b.formation_totals,
      heroes: march.heroes || [],
    };
  }

  function marchHeroesForBoard(march) {
    if (march && march.heroes && march.heroes.length) return march.heroes;
    return (march && march.hero_names) || [];
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
      heroes: marchHeroesForBoard(entry.march),
      opponent: entry.opponent,
      contributionRow: entry.opponent
        ? null
        : contributionRowFromMarch(entry.march),
      onHeroClick: entry.opponent
        ? null
        : function (name) {
            var assignment = (entry.march && entry.march.gear_assignment) || {};
            gearSheet.open(name, entry.title, assignment[name]);
          },
      after: entry.opponent
        ? function (board) {
            appendTroopChipRow(board, entry.march);
            appendBonusChipRow(board, entry.bonuses);
          }
        : null,
    });
  }

  function render(data, opts) {
    opts = opts || {};
    clearError();
    ingestCatalog(data);
    if (data.proxy_banner && bannerEl) {
      bannerEl.textContent = data.proxy_banner;
    }

    var engine = data.engine || (opts.draft ? "input" : "proxy");
    if (scoreEl) {
      if (opts.draft) {
        scoreEl.hidden = true;
      } else {
        scoreEl.hidden = false;
        if (engine === "mc") {
          var marches = data.marches || [];
          var mcCount = 0;
          var activeCount = 0;
          marches.forEach(function (m) {
            if (!m) return;
            activeCount += 1;
            if (m.breakdown && m.breakdown.mc) mcCount += 1;
          });
          var label =
            mcCount > 0 && mcCount < activeCount
              ? "Partial lineup win-rate (MC marches only): "
              : "Lineup win-rate score: ";
          scoreEl.textContent =
            label + Number(data.lineup_score || 0).toFixed(3);
        } else {
          scoreEl.textContent =
            "Lineup proxy score: " + Number(data.lineup_score || 0).toFixed(0);
        }
      }
    }
    if (engineEl) {
      if (opts.draft) {
        var srDraft = selectedStageRound();
        engineEl.hidden = false;
        engineEl.textContent = srDraft
          ? "Input · stage " + srDraft.stage + " · round " + srDraft.round
          : "Input";
      } else {
        var bits = ["Engine: " + engine];
        var sr = selectedStageRound();
        if (sr) {
          bits.push("stage " + sr.stage + " · round " + sr.round);
        }
        if (data.floor && data.floor.floor != null) {
          bits.push(
            "enemy scale ×" + Number(data.floor.enemy_power_scale || 0).toFixed(2)
          );
          if (data.floor.overrides_applied) bits.push("overrides on");
        }
        if (data.opponent && data.opponent.saved) bits.push("saved opponents");
        if (data.floor && data.floor.enemy_proxy) bits.push("enemy proxy");
        if (data.warnings && data.warnings.length) {
          bits.push(data.warnings.join("; "));
        }
        engineEl.hidden = false;
        engineEl.textContent = bits.join(" · ");
      }
    }

    chipsEl.innerHTML = "";
    if (!opts.draft) {
      B.appendChip(chipsEl, "Governor weight 0 (heroes + gear primary)");
    }

    var hasOpp = !!(
      data.opponent &&
      data.opponent.marches &&
      data.opponent.marches.length
    );
    if (opponentEditEl) {
      opponentEditEl.hidden = !hasOpp;
      if (hasOpp) {
        ensureTroopEditors();
        ensureBonusEditors();
        ensureHeroEditors();
      }
    }

    var entries = buildEntries(data);
    var keys = entries.map(function (e) {
      return e.key;
    });
    if (keys.indexOf(chosenKey) === -1) {
      chosenKey = keys.filter(isOpponentKey)[0] || keys[0] || "opp-0";
    }

    function chooseMarch(key) {
      chosenKey = key;
      clearError();
      B.renderModeChips(modeChipsEl, entries, chosenKey, chooseMarch);
      renderSelectedBoard(entries);
      syncEditorsToSelection(entries);
    }

    B.renderModeChips(modeChipsEl, entries, chosenKey, chooseMarch);
    renderSelectedBoard(entries);
    syncEditorsToSelection(entries);

    if (opts.draft) {
      statusEl.textContent =
        "Edit opponent overrides, Apply to save, then press Generate.";
    } else {
      statusEl.textContent =
        "Ready · " +
        (data.active_marches || (data.marches || []).filter(Boolean).length) +
        " active marches · " +
        engine;
    }
  }

  function buildUrl() {
    var url = "/api/optimize/coliseum";
    var sr = selectedStageRound();
    if (!sr) return url;
    return (
      url +
      "?stage=" +
      encodeURIComponent(String(sr.stage)) +
      "&round=" +
      encodeURIComponent(String(sr.round))
    );
  }

  function opponentsGetUrl(sr) {
    return (
      "/api/mystic-trial/coliseum-opponents/" +
      encodeURIComponent(String(sr.stage)) +
      "/" +
      encodeURIComponent(String(sr.round))
    );
  }

  async function loadOpponentDraft() {
    var sr = selectedStageRound();
    lastOptimizeData = null;
    if (!sr) {
      if (opponentEditEl) opponentEditEl.hidden = true;
      modeChipsEl.innerHTML = "";
      boardEl.innerHTML = "";
      if (scoreEl) scoreEl.hidden = true;
      if (engineEl) engineEl.hidden = true;
      chipsEl.innerHTML = "";
      statusEl.textContent =
        "Enter stage & round, set opponent overrides, then press Generate.";
      return;
    }
    var seq = ++opponentLoadSeq;
    statusEl.textContent =
      "Loading opponent overrides for stage " +
      sr.stage +
      " · round " +
      sr.round +
      "…";
    if (scoreEl) scoreEl.hidden = true;
    clearError();
    try {
      var res = await fetch(opponentsGetUrl(sr), { cache: "no-store" });
      var body = await res.json().catch(function () {
        return {};
      });
      if (seq !== opponentLoadSeq) return;
      if (!res.ok) {
        showError(body.detail || "Load opponents failed: " + res.status);
        return;
      }
      ingestCatalog(body);
      fillEventTroops(body);
      chosenKey = "opp-0";
      render(
        {
          catalog_hero_names: catalogNames,
          catalog_by_troop: catalogByTroop,
          marches: [],
          opponent: {
            saved: true,
            marches: normalizeMarches(body.marches),
          },
          engine: "input",
          governor: {},
        },
        { draft: true }
      );
    } catch (err) {
      if (seq !== opponentLoadSeq) return;
      showError(String(err));
    }
  }

  async function generate() {
    var sr = selectedStageRound();
    if (!sr) {
      showError("Set stage and round before Generate.");
      syncGenerateEnabled();
      return;
    }
    if (generating) return;
    var troopsCheck = readEventTroopsBody();
    if (troopsCheck.error) {
      showError(troopsCheck.error);
      syncGenerateEnabled();
      return;
    }
    generating = true;
    syncGenerateEnabled();
    statusEl.textContent = "Saving event troops & solving…";
    if (scoreEl) scoreEl.hidden = true;
    if (engineEl) engineEl.hidden = true;
    modeChipsEl.innerHTML = "";
    boardEl.innerHTML = "";
    clearError();
    try {
      await putEventTroops(sr, troopsCheck.body);
      statusEl.textContent = "Solving marches…";
      var res = await fetch(buildUrl(), { cache: "no-store" });
      var body = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        showError(body.detail || "Optimize failed: " + res.status);
        return;
      }
      lastOptimizeData = body;
      if (!isOpponentKey(chosenKey)) chosenKey = "you-0";
      render(body);
    } catch (err) {
      showError(String(err));
    } finally {
      generating = false;
      syncGenerateEnabled();
    }
  }

  function readValidatedMarchBody() {
    var heroes = readHeroEdits();
    if (
      heroes.hero_level != null &&
      (!Number.isFinite(heroes.hero_level) || heroes.hero_level < 1)
    ) {
      return { error: "Hero level must be an integer >= 1." };
    }
    if (
      heroes.gear_enhancement != null &&
      (!Number.isFinite(heroes.gear_enhancement) || heroes.gear_enhancement < 0)
    ) {
      return { error: "Gold gear + must be an integer >= 0." };
    }
    var troops = readTroopEdits();
    var bad = null;
    TROOPS.forEach(function (troop) {
      var level = troops.levels[troop];
      var count = troops.counts[troop];
      if (
        !Number.isFinite(level) ||
        level < 1 ||
        level > 11 ||
        Math.floor(level) !== level
      ) {
        bad = "Troop level must be an integer 1–11 (" + troop + ").";
      } else if (
        !Number.isFinite(count) ||
        count < 0 ||
        Math.floor(count) !== count
      ) {
        bad = "Troop count must be a non-negative whole number (" + troop + ").";
      }
    });
    if (bad) return { error: bad };
    var total =
      troops.counts.infantry + troops.counts.cavalry + troops.counts.archers;
    if (total <= 0) {
      return { error: "Opponent troop counts must sum to a positive value." };
    }
    return {
      body: {
        hero_names: heroes.hero_names,
        hero_level: heroes.hero_level,
        gear_enhancement: heroes.gear_enhancement,
        levels: troops.levels,
        counts: troops.counts,
        bonuses: readBonuses(),
      },
    };
  }

  async function putOpponentSlot(sr, slot, body) {
    var putUrl =
      "/api/mystic-trial/coliseum-opponents/" +
      encodeURIComponent(String(sr.stage)) +
      "/" +
      encodeURIComponent(String(sr.round)) +
      "/" +
      encodeURIComponent(String(slot));
    var res = await fetch(putUrl, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    var payload = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      throw new Error(payload.detail || "Save failed: " + res.status);
    }
    return payload;
  }

  function refreshAfterOpponentSave(payload) {
    var marches = normalizeMarches(payload.marches);
    if (lastOptimizeData) {
      lastOptimizeData.opponent = { saved: true, marches: marches };
      render(lastOptimizeData);
      statusEl.textContent =
        "Opponent saved. Press Generate again to rescore with the new overrides.";
      return;
    }
    render(
      {
        catalog_hero_names: catalogNames,
        marches: [],
        opponent: { saved: true, marches: marches },
        engine: "input",
        governor: {},
      },
      { draft: true }
    );
    statusEl.textContent =
      "Opponent saved. Press Generate when ready.";
  }

  async function applyOpponentEdits() {
    if (fillingEditors) return;
    var sr = selectedStageRound();
    if (!sr) {
      showError("Enter stage and round before editing the opponent.");
      return;
    }
    if (!isOpponentKey(chosenKey)) {
      showError("Select an opponent march below, then Apply.");
      return;
    }
    var slot = opponentSlotFromKey(chosenKey);
    if (slot == null) {
      showError("Select an opponent march below, then Apply.");
      return;
    }

    var checked = readValidatedMarchBody();
    if (checked.error) {
      showError(checked.error);
      return;
    }

    statusEl.textContent = "Saving opponent…";
    try {
      var payload = await putOpponentSlot(sr, slot, checked.body);
      refreshAfterOpponentSave(payload);
    } catch (err) {
      showError(String(err && err.message ? err.message : err));
    }
  }

  async function copyOpponentToOther() {
    if (fillingEditors) return;
    var sr = selectedStageRound();
    if (!sr) {
      showError("Enter stage and round before copying.");
      return;
    }
    if (!isOpponentKey(chosenKey)) {
      showError("Select an opponent march below, then copy.");
      return;
    }
    var slot = opponentSlotFromKey(chosenKey);
    if (slot == null) {
      showError("Select an opponent march below, then copy.");
      return;
    }
    var other = slot === 0 ? 1 : 0;
    var checked = readValidatedMarchBody();
    if (checked.error) {
      showError(checked.error);
      return;
    }

    statusEl.textContent = "Copying to Opponent " + (other + 1) + "…";
    try {
      await putOpponentSlot(sr, slot, checked.body);
      var payload = await putOpponentSlot(sr, other, checked.body);
      chosenKey = "opp-" + other;
      refreshAfterOpponentSave(payload);
    } catch (err) {
      showError(String(err && err.message ? err.message : err));
    }
  }

  function onStageRoundChange() {
    chosenKey = "opp-0";
    syncGenerateEnabled();
    loadOpponentDraft();
  }

  if (regenBtn) regenBtn.addEventListener("click", generate);
  if (regenInlineBtn) regenInlineBtn.addEventListener("click", generate);
  if (stageEl) stageEl.addEventListener("change", onStageRoundChange);
  if (roundEl) roundEl.addEventListener("change", onStageRoundChange);
  if (stageEl) stageEl.addEventListener("input", onStageRoundChange);
  if (roundEl) roundEl.addEventListener("input", onStageRoundChange);
  if (eventTroopsApplyBtn) eventTroopsApplyBtn.addEventListener("click", saveEventTroops);
  if (applyBtn) applyBtn.addEventListener("click", applyOpponentEdits);
  if (copyOtherBtn) copyOtherBtn.addEventListener("click", copyOpponentToOther);

  syncGenerateEnabled();
  statusEl.textContent =
    "Enter stage & round, set opponent overrides, then press Generate.";
})();
