/* Shared Event-lineups board primitives for Mystic Trial (and others).
 *
 * Mirrors the formation board in optimiser_events.js: hero slots with
 * portraits/initials, board rows, mode-chips, and march reporting — so Radiant /
 * Coliseum / Molten report marches the same way Swordland/Bear do.
 *
 * Depends on app.js (window.safeUrl, window.escapeHtml). Loaded after app.js.
 */
(function (global) {
  "use strict";

  var safeUrl = global.safeUrl;
  var esc = global.escapeHtml || function (s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  };

  function heroName(hero) {
    if (hero == null) return "";
    if (typeof hero === "string") return hero;
    return hero.name == null ? "" : String(hero.name);
  }

  function heroSlug(name) {
    var slug = String(name).trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
    slug = slug.replace(/^-+/, "").replace(/-+$/, "");
    return slug || "hero";
  }

  function portraitUrl(hero) {
    var provided = safeUrl && safeUrl(hero && hero.icon_url);
    if (provided) return provided;
    var name = heroName(hero);
    if (!name) return "";
    return "/static/heroes/" + heroSlug(name) + ".webp";
  }

  function initials(name) {
    var parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
  }

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

  function fmtPoints(n) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  /** Same shape as Events `troopsLine` for a mystic march payload. */
  function troopsLine(march) {
    var t = (march && march.counts) || {};
    function n(v) {
      return v == null ? "—" : fmtPoints(v);
    }
    return (
      "I " +
      n(t.infantry) +
      " · C " +
      n(t.cavalry) +
      " · A " +
      n(t.archers) +
      " · cap " +
      n(march && march.capacity)
    );
  }

  function fmtCounts(counts) {
    return troopsLine({ counts: counts || {}, capacity: null }).replace(
      / · cap —$/,
      ""
    );
  }

  function heroSlotEl(slotLabel, hero, opts) {
    opts = opts || {};
    var name = heroName(hero);
    var interactive =
      opts.interactive !== false && name && typeof opts.onClick === "function";
    var el = document.createElement(interactive ? "button" : "div");
    if (interactive) el.type = "button";
    el.className = "hero-slot" + (name ? "" : " is-empty");

    var portrait = document.createElement("span");
    portrait.className = "portrait";
    portrait.textContent = name ? initials(name) : "—";
    if (name) {
      var img = document.createElement("img");
      img.alt = "";
      img.addEventListener("error", function () {
        img.hidden = true;
      });
      var url = portraitUrl(hero);
      if (url) img.src = url;
      portrait.appendChild(img);
    }
    el.appendChild(portrait);

    var nameEl = document.createElement("span");
    nameEl.className = "hero-slot-name";
    nameEl.textContent = name || "Empty";
    el.appendChild(nameEl);

    if (slotLabel) {
      var tag = document.createElement("span");
      tag.className = "slot-tag";
      tag.textContent = slotLabel;
      el.appendChild(tag);
    }

    if (interactive) {
      el.setAttribute("aria-label", name + " — gear");
      el.addEventListener("click", function () {
        opts.onClick(name, hero);
      });
    }
    return el;
  }

  var GEAR_SLOTS = [
    { key: "helmet", label: "Helm" },
    { key: "gloves", label: "Gloves" },
    { key: "chest", label: "Body" },
    { key: "boots", label: "Boots" },
  ];

  function pieceForSlot(pieces, slot) {
    return (
      (pieces || []).find(function (p) {
        return p.slot === slot;
      }) || null
    );
  }

  function renderGearGrid(pieces) {
    var cells = GEAR_SLOTS.map(function (spec) {
      var piece = pieceForSlot(pieces, spec.key);
      if (!piece) {
        return (
          '<div class="gear-cell"><div><div class="gear-slot-label">' +
          esc(spec.label) +
          '</div><div class="gear-meta">Empty</div></div></div>'
        );
      }
      var url = safeUrl && safeUrl(piece.icon_url);
      var img = url ? '<img src="' + esc(url) + '" alt="" />' : "";
      var bits = [piece.rarity || ""];
      if (piece.enhancement_level != null) bits.push("+" + piece.enhancement_level);
      if (piece.mastery_level != null) bits.push("M" + piece.mastery_level);
      if (piece.power != null) bits.push(fmtPoints(piece.power) + " pwr");
      return (
        '<div class="gear-cell">' +
        img +
        '<div><div class="gear-slot-label">' +
        esc(spec.label) +
        "</div>" +
        '<div class="gear-name">' +
        esc(piece.name || "—") +
        "</div>" +
        '<div class="gear-meta">' +
        esc(bits.filter(Boolean).join(" · ")) +
        "</div></div></div>"
      );
    });
    return '<div class="gear-grid">' + cells.join("") + "</div>";
  }

  /**
   * Wire #gear-detail-modal (see _gear_detail_modal.html). Returns open/close
   * helpers so Mystic pages can tap a hero and show assigned gear.
   */
  function bindGearSheet() {
    var modal = document.getElementById("gear-detail-modal");
    var modalTitle = document.getElementById("gear-modal-title");
    var modalSub = document.getElementById("gear-modal-sub");
    var modalBody = document.getElementById("gear-modal-body");
    var modalClose = document.getElementById("gear-modal-close");
    if (!modal || !modalTitle || !modalSub || !modalBody) {
      return { open: function () {}, close: function () {} };
    }

    function close() {
      modal.classList.remove("open");
      modal.hidden = true;
    }

    function open(name, contextLine, pieces) {
      modalTitle.textContent = name;
      modalSub.textContent = contextLine || "";
      modalBody.innerHTML = renderGearGrid(pieces);
      modal.hidden = false;
      modal.classList.add("open");
      if (modalClose && typeof modalClose.focus === "function") modalClose.focus();
    }

    if (typeof global.bindDialogDismiss === "function") {
      global.bindDialogDismiss(modal, modalClose, close);
    }

    return { open: open, close: close };
  }

  function boardRowEl(label, slotLabels, heroes, opts) {
    var wrap = document.createElement("div");
    wrap.className = "board-row";
    var head = document.createElement("div");
    head.className = "row-label";
    head.textContent = label;
    wrap.appendChild(head);
    var row = document.createElement("div");
    row.className = "hero-row";
    (heroes || []).forEach(function (hero, i) {
      row.appendChild(heroSlotEl(slotLabels ? slotLabels[i] : "", hero, opts));
    });
    wrap.appendChild(row);
    return wrap;
  }

  function appendChip(parent, text) {
    var chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = text;
    parent.appendChild(chip);
    return chip;
  }

  /* --- Swordland-style expedition contribution strip + table ---------------- */

  function fmtShare(n, family) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    if (family === "expedition") return Number(n).toFixed(1) + "%";
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  function totalsOf(row) {
    var totals = row && row.formation_totals;
    return totals && totals.power ? totals : null;
  }

  var CONQUEST_HEALTH_LABELS = ["Hero Health", "Escort Health"];
  var CONQUEST_COMBAT_SCALE = 10000;
  var CONQUEST_HEALTH_SCALE = 100000;

  function scoreWeight(label, total, family) {
    if (family !== "conquest") return total;
    var scale =
      CONQUEST_HEALTH_LABELS.indexOf(label) !== -1
        ? CONQUEST_HEALTH_SCALE
        : CONQUEST_COMBAT_SCALE;
    return total / scale;
  }

  function renderContributionStrip(row) {
    var totals = totalsOf(row);
    if (!totals) return "";
    var family = row.stat_family || totals.family || "expedition";
    var p = totals.power;
    var facts = [
      ["power", fmtShare(p.total, "conquest")],
      ["from hero", fmtShare(p.hero, "conquest")],
      ["from skills", fmtShare(p.skills, "conquest")],
      ["from gear", fmtShare(p.gear, "conquest")],
    ];
    Object.keys(totals.stats || {})
      .map(function (label) {
        return [label, totals.stats[label]];
      })
      .filter(function (pair) {
        return pair[1] && pair[1].total > 0;
      })
      .sort(function (a, b) {
        return (
          scoreWeight(b[0], b[1].total, family) -
          scoreWeight(a[0], a[1].total, family)
        );
      })
      .slice(0, 3)
      .forEach(function (pair) {
        facts.push([pair[0], fmtShare(pair[1].total, family)]);
      });
    var chips = facts
      .map(function (pair) {
        return (
          '<div class="fact"><div class="fact-k">' +
          esc(pair[0]) +
          '</div><div class="fact-v">' +
          esc(pair[1]) +
          "</div></div>"
        );
      })
      .join("");
    var flags = [];
    if (totals.estimated) flags.push("estimated");
    if (totals.skills_incomplete) flags.push("skills partial");
    var note = flags.length
      ? '<p class="contrib-note">' + esc(family + " · " + flags.join(" · ")) + "</p>"
      : '<p class="contrib-note">' + esc(family) + "</p>";
    return '<div class="contrib-strip">' + chips + "</div>" + note;
  }

  function contribSplit(share, fam) {
    if (!share) return "—";
    return (
      esc(fmtShare(share.total, fam)) +
      '<br><span class="contrib-split">' +
      esc(fmtShare(share.hero, fam)) +
      " hero · +" +
      esc(fmtShare(share.skills, fam)) +
      " skills · +" +
      esc(fmtShare(share.gear, fam)) +
      " gear</span>"
    );
  }

  function contribTableShell(family, totals, headHtml, bodyHtml, totalRowHtml, extraNote) {
    var flags = [];
    if (totals && totals.estimated) flags.push("estimated");
    if (totals && totals.skills_incomplete) flags.push("skills partial");
    var bits = ["each cell: total, then hero · skills delta (+) · gear delta (+)"];
    if (extraNote) bits.push(extraNote);
    if (flags.length) bits.push(flags.join(" · "));
    return (
      '<h3 class="section-title">Stat contributions · ' +
      esc(family) +
      "</h3>" +
      '<p class="contrib-note">' +
      esc(bits.join(" · ")) +
      "</p>" +
      '<div class="table-scroll"><table class="contrib-table"><thead>' +
      headHtml +
      "</thead><tbody>" +
      bodyHtml +
      totalRowHtml +
      "</tbody></table></div>"
    );
  }

  function genericStatName(label) {
    var parts = String(label).split(" ");
    return parts[parts.length - 1];
  }

  function unitOf(label) {
    var parts = String(label).split(" ");
    return parts.slice(0, parts.length - 1).join(" ");
  }

  var EXPEDITION_STAT_ORDER = ["Attack", "Defense", "Health", "Lethality"];

  function renderExpeditionContributionTable(row, names, contributions, family) {
    var perHero = {};
    var presentStats = [];
    names.forEach(function (name) {
      var stats = (contributions[name] && contributions[name].stats) || {};
      var unit = null;
      var byStat = {};
      Object.keys(stats).forEach(function (label) {
        var stat = genericStatName(label);
        if (unit === null) unit = unitOf(label);
        byStat[stat] = stats[label];
        if (presentStats.indexOf(stat) === -1) presentStats.push(stat);
      });
      perHero[name] = { unit: unit, byStat: byStat };
    });
    var order = EXPEDITION_STAT_ORDER.filter(function (s) {
      return presentStats.indexOf(s) !== -1;
    });

    var head =
      "<tr><th>hero</th><th>power</th><th>unit</th>" +
      order
        .map(function (s) {
          return "<th>" + esc(s) + "</th>";
        })
        .join("") +
      "</tr>";
    var body = names
      .map(function (name) {
        var c = contributions[name];
        var info = perHero[name];
        return (
          "<tr><td>" +
          esc(name) +
          "</td>" +
          "<td>" +
          contribSplit(c.power, "conquest") +
          "</td>" +
          "<td>" +
          esc(info.unit || "—") +
          "</td>" +
          order
            .map(function (s) {
              return "<td>" + contribSplit(info.byStat[s], family) + "</td>";
            })
            .join("") +
          "</tr>"
        );
      })
      .join("");

    var totals = totalsOf(row);
    var totalRow = "";
    if (totals) {
      var totalByStat = {};
      Object.keys(totals.stats || {}).forEach(function (label) {
        var stat = genericStatName(label);
        var share = totals.stats[label];
        var acc = totalByStat[stat] || { hero: 0, skills: 0, gear: 0, total: 0 };
        acc.hero += share.hero;
        acc.skills += share.skills;
        acc.gear += share.gear;
        acc.total += share.total;
        totalByStat[stat] = acc;
      });
      totalRow =
        '<tr class="contrib-total"><td>formation</td><td>' +
        esc(fmtShare(totals.power.total, "conquest")) +
        "</td><td>—</td>" +
        order
          .map(function (s) {
            var share = totalByStat[s];
            return (
              "<td>" + esc(share ? fmtShare(share.total, family) : "—") + "</td>"
            );
          })
          .join("") +
        "</tr>";
    }
    return contribTableShell(
      family,
      totals,
      head,
      body,
      totalRow,
      "unit is each hero's own troop"
    );
  }

  function renderContributionTable(row) {
    var contributions = (row && row.contributions) || null;
    if (!contributions) return "";
    var names = Object.keys(contributions).filter(function (n) {
      return contributions[n];
    });
    if (!names.length) return "";
    var family = row.stat_family || "expedition";
    return renderExpeditionContributionTable(row, names, contributions, family);
  }

  function appendContributionCards(boardEl, row) {
    if (!boardEl || !row) return;
    var strip = renderContributionStrip(row);
    if (strip) {
      var stripEl = document.createElement("div");
      stripEl.innerHTML = strip;
      // Insert strip before the march row when possible (Swordland order).
      var marchRow = boardEl.querySelector(".board-row");
      if (marchRow) boardEl.insertBefore(stripEl, marchRow);
      else boardEl.appendChild(stripEl);
    }
    var table = renderContributionTable(row);
    if (table) {
      var tableEl = document.createElement("div");
      tableEl.innerHTML = table;
      boardEl.appendChild(tableEl);
    }
  }

  /**
   * Events-style mode chips: pick one entry, show name + score line.
   * @param {HTMLElement} chipsEl
   * @param {Array<{key, label, scoreText, isError?}>} entries
   * @param {string} chosenKey
   * @param {function(string)} onChoose
   */
  function renderModeChips(chipsEl, entries, chosenKey, onChoose) {
    chipsEl.innerHTML = "";
    entries.forEach(function (entry) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className =
        "mode-chip" +
        (entry.key === chosenKey ? " on" : "") +
        (entry.isError ? " is-error" : "");
      chip.setAttribute("aria-pressed", entry.key === chosenKey ? "true" : "false");
      chip.innerHTML =
        '<span class="mode-name">' +
        esc(entry.label) +
        '</span><span class="mode-score">' +
        esc(entry.scoreText || "") +
        "</span>";
      chip.addEventListener("click", function () {
        onChoose(entry.key);
      });
      chipsEl.appendChild(chip);
    });
  }

  /**
   * Report one march exactly like Events Sword/Bear: title, meta, March row.
   * Clears `boardEl` then fills it.
   */
  function renderMarchReport(boardEl, spec) {
    boardEl.innerHTML = "";
    boardEl.classList.toggle("board-opponent", !!spec.opponent);

    var title = document.createElement("h2");
    title.className = "board-title";
    title.textContent = spec.title || "March";
    boardEl.appendChild(title);

    if (spec.meta) {
      var meta = document.createElement("p");
      meta.className = "board-meta";
      meta.textContent = spec.meta;
      boardEl.appendChild(meta);
    }

    var heroes = spec.heroes || [];
    if (!heroes.length) {
      var empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No heroes in this result.";
      boardEl.appendChild(empty);
      return;
    }

    boardEl.appendChild(
      boardRowEl(spec.rowLabel || "March", spec.slotLabels || null, heroes, {
        onClick: spec.onHeroClick,
        interactive: !!spec.onHeroClick,
      })
    );

    if (typeof spec.after === "function") {
      spec.after(boardEl);
    }

    if (spec.contributionRow) {
      appendContributionCards(boardEl, spec.contributionRow);
    }
  }

  /** Build Events-like meta: score · ratio · troopsLine. */
  function marchReportMeta(march, scoreText) {
    var bits = [];
    if (scoreText) bits.push(scoreText);
    if (march && march.ratio) bits.push("ratio " + fmtRatio(march.ratio));
    bits.push(troopsLine(march || {}));
    return bits.join(" · ");
  }

  function appendMarchBoard(parent, spec) {
    var board = document.createElement("section");
    board.className = "panel board" + (spec.opponent ? " board-opponent" : "");
    parent.appendChild(board);
    renderMarchReport(board, spec);
    return board;
  }

  global.OptimiserBoard = {
    heroName: heroName,
    heroSlug: heroSlug,
    portraitUrl: portraitUrl,
    initials: initials,
    fmtPct: fmtPct,
    fmtRatio: fmtRatio,
    fmtPoints: fmtPoints,
    fmtCounts: fmtCounts,
    troopsLine: troopsLine,
    marchReportMeta: marchReportMeta,
    heroSlotEl: heroSlotEl,
    boardRowEl: boardRowEl,
    appendChip: appendChip,
    renderModeChips: renderModeChips,
    renderMarchReport: renderMarchReport,
    appendMarchBoard: appendMarchBoard,
    appendContributionCards: appendContributionCards,
    renderContributionStrip: renderContributionStrip,
    renderContributionTable: renderContributionTable,
    renderGearGrid: renderGearGrid,
    bindGearSheet: bindGearSheet,
  };
})(typeof window !== "undefined" ? window : this);
