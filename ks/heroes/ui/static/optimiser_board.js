/* Shared Event-lineups board primitives for Mystic Trial (and others).
 *
 * Mirrors the formation board in optimiser_events.js: hero slots with
 * portraits/initials, board rows, and common formatters — so Radiant /
 * Coliseum / Molten look like Swordland/Bear marches instead of ad-hoc cards.
 *
 * Depends on app.js (window.safeUrl). Loaded after app.js on each page.
 */
(function (global) {
  "use strict";

  var safeUrl = global.safeUrl;

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

  function fmtCounts(counts) {
    counts = counts || {};
    return (
      "I " +
      (counts.infantry || 0) +
      " · C " +
      (counts.cavalry || 0) +
      " · A " +
      (counts.archers || 0)
    );
  }

  /**
   * @param {string} slotLabel
   * @param {string|object} hero
   * @param {{ onClick?: function, interactive?: boolean }} [opts]
   */
  function heroSlotEl(slotLabel, hero, opts) {
    opts = opts || {};
    var name = heroName(hero);
    var interactive = opts.interactive !== false && name && typeof opts.onClick === "function";
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
      row.appendChild(
        heroSlotEl(slotLabels ? slotLabels[i] : "", hero, opts)
      );
    });
    wrap.appendChild(row);
    return wrap;
  }

  /**
   * Append one Event-style march board (title + meta + hero row + optional extras).
   * @returns {HTMLElement} the board section
   */
  function appendMarchBoard(parent, spec) {
    spec = spec || {};
    var board = document.createElement("section");
    board.className = "panel board" + (spec.opponent ? " board-opponent" : "");

    if (spec.title) {
      var title = document.createElement("h2");
      title.className = "board-title";
      title.textContent = spec.title;
      board.appendChild(title);
    }
    if (spec.meta) {
      var meta = document.createElement("p");
      meta.className = "board-meta";
      meta.textContent = spec.meta;
      board.appendChild(meta);
    }

    var heroes = spec.heroes || [];
    if (heroes.length) {
      board.appendChild(
        boardRowEl(spec.rowLabel || "March", spec.slotLabels || null, heroes, {
          onClick: spec.onHeroClick,
          interactive: !!spec.onHeroClick,
        })
      );
    }

    if (typeof spec.after === "function") {
      spec.after(board);
    }

    parent.appendChild(board);
    return board;
  }

  function appendChip(parent, text) {
    var chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = text;
    parent.appendChild(chip);
    return chip;
  }

  global.OptimiserBoard = {
    heroName: heroName,
    heroSlug: heroSlug,
    portraitUrl: portraitUrl,
    initials: initials,
    fmtPct: fmtPct,
    fmtRatio: fmtRatio,
    fmtCounts: fmtCounts,
    heroSlotEl: heroSlotEl,
    boardRowEl: boardRowEl,
    appendMarchBoard: appendMarchBoard,
    appendChip: appendChip,
  };
})(typeof window !== "undefined" ? window : this);
