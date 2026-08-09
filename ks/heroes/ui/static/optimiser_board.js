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
      el.setAttribute("aria-label", name);
      el.addEventListener("click", function () {
        opts.onClick(name, hero);
      });
    }
    return el;
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
  };
})(typeof window !== "undefined" ? window : this);
