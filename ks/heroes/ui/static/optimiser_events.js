/* Event lineups board (layout B) for /optimiser/events.
 *
 * Renders one screen at a time from a single GET /api/optimize: an event
 * segmented control, a grid of mode chips carrying that mode's points (or the
 * arena side's score), and a formation board for whichever chip is selected.
 * Tapping a hero opens the why + gear sheet — a bottom sheet on a phone, a
 * centred modal on a wide screen.
 *
 * One fetch serves every screen. /api/optimize solves sword, bear and both
 * arena sides in one go — several seconds of ILP — so switching event or mode
 * re-renders from the bundle already in hand rather than re-solving.
 *
 * Text discipline: anything derived from the API reaches the DOM either via
 * `textContent` (single-node text — cannot inject) or through `esc()` (the
 * two places that assemble nested markup: the chips and the sheet body).
 * Hero names, mode keys, gear names and solver error strings all come from
 * config files and OCR, so none of them are trusted here. `esc()` and the
 * dialog-dismiss wiring are app.js's, which _layout.html loads first.
 */
(function () {
  "use strict";

  var boardEl = document.getElementById("board");
  var statusEl = document.getElementById("lineup-status");
  var chipsEl = document.getElementById("mode-chips");
  var noteEl = document.getElementById("mode-note");
  var sectionErrEl = document.getElementById("section-error");
  // All five are dereferenced unguarded below, so all five are checked here
  // rather than only the first: this file also loads on any page that
  // includes it, and a half-present shell must be inert, not half-rendered.
  if (!boardEl || !statusEl || !chipsEl || !noteEl || !sectionErrEl) return;

  var modal = document.getElementById("gear-detail-modal");
  var modalTitle = document.getElementById("gear-modal-title");
  var modalSub = document.getElementById("gear-modal-sub");
  var modalBody = document.getElementById("gear-modal-body");
  var modalClose = document.getElementById("gear-modal-close");

  var GEAR_SLOTS = [
    { key: "helmet", label: "Helm" },
    { key: "gloves", label: "Gloves" },
    { key: "chest", label: "Body" },
    { key: "boots", label: "Boots" }
  ];
  var ARENA_SIDES = ["attack", "defense"];
  var FRONT_SLOTS = ["F1", "F2"];
  var BACK_SLOTS = ["B1", "B2", "B3"];
  var ALL_SLOTS = FRONT_SLOTS.concat(BACK_SLOTS);

  function slice(list) {
    return Array.prototype.slice.call(list);
  }

  var eventButtons = slice(document.querySelectorAll("[data-event]"));
  var regenButtons = slice(document.querySelectorAll("[data-regen]"));

  /** Event labels come off the markup so the page has exactly one copy. */
  var eventLabels = {};
  eventButtons.forEach(function (btn) {
    eventLabels[btn.dataset.event] = String(btn.textContent).trim();
  });

  var bundle = null;
  var activeEvent = eventButtons.length ? eventButtons[0].dataset.event : "sword";
  /** Per-event chip selection, so switching events and back keeps the pick. */
  var chosen = {};

  /* --- helpers -------------------------------------------------------------- */

  /** app.js's shared escaper — see there for why it is not defined here. */
  var esc = window.escapeHtml;

  /** A same-origin path, or "" for anything else.
   *
   *  Every URL that reaches this is a path: ensure_all_icons emits
   *  /gear-icons/<id>.png, hero portraits are /static/heroes/<slug>.webp. So
   *  refusing everything else costs nothing and leaves a rule that can be
   *  stated in one line — which the previous version could not: it rejected
   *  "//host/x" as off-site while allowing "https://host/x", which is off-site
   *  too.
   *
   *  Both "//host/x" and "/\host/x" start with "/" and are why this is not
   *  just `charAt(0) === "/"`: WHATWG parses a backslash in the authority of a
   *  special scheme exactly like a slash, so both are protocol-relative URLs
   *  wearing a path's clothes.
   *
   *  This is an origin check, not an escaping one. What it returns is still
   *  escaped before it reaches an attribute — see renderGearGrid. */
  function safeUrl(u) {
    if (!u) return "";
    var s = String(u);
    if (s.charAt(0) !== "/") return "";
    if (s.charAt(1) === "/" || s.charAt(1) === "\\") return "";
    return s;
  }

  /** Comma-grouped integer. Pinned to en-US like every other grouped number
   *  in this UI (troops.js's totals, the Gear XP planner's XP and level
   *  numbers): a bare toLocaleString() follows the browser's locale, so the
   *  same 1,200 points would render "1.200" on one machine and "1 200" on
   *  another while the page beside it stayed on commas. */
  function fmtPoints(n) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  function fmtScore(n) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    return Number(n).toFixed(1);
  }

  function humanKey(key) {
    return String(key).replace(/_/g, " ");
  }

  function heroName(hero) {
    if (hero == null) return "";
    if (typeof hero === "string") return hero;
    return hero.name == null ? "" : String(hero.name);
  }

  /** Mirrors ks/heroes/ui/hero_icons.py:hero_slug, which named the files in
   *  /static/heroes. Diverging would silently fall back to initials. */
  function heroSlug(name) {
    var slug = String(name).trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
    slug = slug.replace(/^-+/, "").replace(/-+$/, "");
    return slug || "hero";
  }

  function portraitUrl(hero) {
    var provided = safeUrl(hero && hero.icon_url);
    if (provided) return provided;
    return "/static/heroes/" + heroSlug(heroName(hero)) + ".webp";
  }

  function initials(name) {
    var parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
  }

  function troopsLine(row) {
    var t = row.troops || {};
    function n(v) {
      return v == null ? "—" : fmtPoints(v);
    }
    return (
      "I " + n(t.infantry) + " · C " + n(t.cavalry) + " · A " + n(t.archers) +
      " · cap " + n(row.effective_capacity)
    );
  }

  function breakdownLine(row) {
    var bd = row.breakdown || {};
    return ["combat", "occupation", "first_control", "loot"]
      .filter(function (k) {
        return bd[k] != null;
      })
      .map(function (k) {
        return humanKey(k) + " " + fmtPoints(bd[k]);
      })
      .join(" · ");
  }

  /* --- reading the bundle --------------------------------------------------- */

  /** [{key, label, row}] for the active event: one per mode, or per arena
   *  side. Arena sides are listed even when they failed, so a broken side
   *  can still be selected and read rather than vanishing. */
  function entriesFor(eventKey) {
    if (!bundle) return [];
    if (eventKey === "arena") {
      var arena = bundle.arena || {};
      return ARENA_SIDES.filter(function (side) {
        return arena[side];
      }).map(function (side) {
        return { key: side, label: side, row: arena[side] };
      });
    }
    var modes = (bundle[eventKey] || {}).modes || {};
    return Object.keys(modes).map(function (mode) {
      return { key: mode, label: humanKey(mode), row: modes[mode] };
    });
  }

  /** A whole section the solver could not produce at all. */
  function sectionError(eventKey) {
    if (!bundle) return "";
    if (eventKey === "arena") {
      var arena = bundle.arena || {};
      var parts = [];
      ARENA_SIDES.forEach(function (side) {
        var row = arena[side] || {};
        if (row.error) parts.push(side + ": " + row.error);
      });
      return parts.join(" · ");
    }
    var section = bundle[eventKey] || {};
    if (section.status === "Error" || section.error) {
      return section.error || "unknown error";
    }
    return "";
  }

  function rowIsOk(row) {
    return !row.status || row.status === "Optimal";
  }

  function hasFormation(row) {
    var f = row.formation;
    if (!f) return false;
    return ALL_SLOTS.some(function (s) {
      return !!f[s];
    });
  }

  function heroesByName(row) {
    var map = {};
    (row.heroes || []).forEach(function (hero) {
      var name = heroName(hero);
      if (name) map[name] = hero;
    });
    return map;
  }

  function explainFor(row, name) {
    if (row.explanations && row.explanations[name]) return row.explanations[name];
    var hero = (row.heroes || []).find(function (h) {
      return heroName(h) === name;
    });
    return (hero && hero.explain) || null;
  }

  /* --- the sheet ------------------------------------------------------------ */

  function pieceForSlot(pieces, slot) {
    return (pieces || []).find(function (p) {
      return p.slot === slot;
    }) || null;
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
      var url = safeUrl(piece.icon_url);
      // esc() here is not belt-and-braces: safeUrl is an *origin* check, and
      // `/x.png" onerror="alert(1)` is a perfectly good same-origin path that
      // closes this attribute if it goes in raw.
      var img = url ? '<img src="' + esc(url) + '" alt="" />' : "";
      var bits = [piece.rarity || ""];
      if (piece.enhancement_level != null) bits.push("+" + piece.enhancement_level);
      if (piece.mastery_level != null) bits.push("M" + piece.mastery_level);
      if (piece.power != null) bits.push(fmtPoints(piece.power) + " pwr");
      return (
        '<div class="gear-cell">' +
        img +
        '<div><div class="gear-slot-label">' + esc(spec.label) + "</div>" +
        '<div class="gear-name">' + esc(piece.name || "—") + "</div>" +
        '<div class="gear-meta">' +
        esc(bits.filter(Boolean).join(" · ")) +
        "</div></div></div>"
      );
    });
    return '<div class="gear-grid">' + cells.join("") + "</div>";
  }

  function alternateLine(loo) {
    return (loo.alternate_lineup || loo.replacement_heroes || []).join(", ");
  }

  function renderWhy(explain) {
    if (!explain) return '<p class="empty">No explanation recorded for this hero.</p>';
    // Either half stands alone: an arena explanation may carry a slot with
    // no role, and the slot is the more useful of the two on a formation
    // board. Nesting it inside `if (explain.role)` dropped it silently.
    var head = [];
    if (explain.slot) head.push(esc(explain.slot));
    if (explain.role) head.push(esc(humanKey(explain.role)));
    var role = head.length ? '<p class="why-role">' + head.join(" · ") + "</p>" : "";
    var fits = (explain.fits_because || [])
      .map(function (bullet) {
        return "<li>" + esc(bullet) + "</li>";
      })
      .join("");
    var loo = explain.leave_one_out || {};
    var marginal = "";
    if (loo.critical) {
      marginal =
        '<p class="why-marginal critical">Critical — no feasible lineup without this hero</p>';
    } else if (loo.inconclusive) {
      marginal =
        '<p class="why-marginal critical">Leave-one-out inconclusive (status ' +
        esc(loo.status || "?") +
        ")</p>";
    } else if (loo.marginal_points != null || loo.marginal_score != null) {
      var cost =
        loo.marginal_points != null
          ? fmtPoints(loo.marginal_points) + " pts"
          : fmtScore(loo.marginal_score) + " score";
      var alt = alternateLine(loo);
      marginal =
        '<p class="why-marginal">Removing costs ' +
        esc(cost) +
        (alt ? " · alternate lineup: " + esc(alt) : "") +
        "</p>";
    }
    return '<div class="why">' + role + (fits ? "<ul>" + fits + "</ul>" : "") + marginal + "</div>";
  }

  function openHeroSheet(name, entry) {
    if (!modal) return;
    modalTitle.textContent = name;
    var assignment = entry.row.gear_assignment || {};
    var context = [eventLabels[activeEvent] || activeEvent, entry.label];
    var explain = explainFor(entry.row, name);
    if (explain && explain.slot) context.push(explain.slot);
    modalSub.textContent = context.join(" · ");
    modalBody.innerHTML = renderWhy(explain) + renderGearGrid(assignment[name]);
    modal.hidden = false;
    modal.classList.add("open");
    if (modalClose && typeof modalClose.focus === "function") modalClose.focus();
  }

  function closeHeroSheet() {
    if (!modal) return;
    modal.classList.remove("open");
    modal.hidden = true;
  }

  /* --- rendering ------------------------------------------------------------ */

  function chipScoreText(eventKey, entry) {
    if (eventKey === "arena") {
      if (!rowIsOk(entry.row)) return entry.row.status || "unavailable";
      return "score " + fmtScore(entry.row.score);
    }
    return fmtPoints(entry.row.expected_personal_points) + " pts";
  }

  function renderChips(entries) {
    chipsEl.innerHTML = "";
    entries.forEach(function (entry) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "mode-chip" + (entry.key === chosen[activeEvent] ? " on" : "");
      if (!rowIsOk(entry.row)) chip.className += " is-error";
      chip.setAttribute("aria-pressed", entry.key === chosen[activeEvent] ? "true" : "false");
      chip.innerHTML =
        '<span class="mode-name">' + esc(entry.label) + "</span>" +
        '<span class="mode-score">' + esc(chipScoreText(activeEvent, entry)) + "</span>";
      chip.addEventListener("click", function () {
        chosen[activeEvent] = entry.key;
        render();
      });
      chipsEl.appendChild(chip);
    });
  }

  function heroSlotEl(slotLabel, hero, entry) {
    var name = heroName(hero);
    var el = document.createElement(name ? "button" : "div");
    if (name) el.type = "button";
    el.className = "hero-slot" + (name ? "" : " is-empty");

    var portrait = document.createElement("span");
    portrait.className = "portrait";
    portrait.textContent = name ? initials(name) : "—";
    if (name) {
      var img = document.createElement("img");
      img.alt = "";
      // A hero with no artwork on disk must read as a filled slot, not as the
      // browser's broken-image glyph: drop the <img> and let the initials
      // underneath stand in.
      img.addEventListener("error", function () {
        img.hidden = true;
      });
      img.src = portraitUrl(hero);
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

    if (name) {
      el.setAttribute("aria-label", name + " — why and gear");
      el.addEventListener("click", function () {
        openHeroSheet(name, entry);
      });
    }
    return el;
  }

  function boardRowEl(label, slotLabels, heroes, entry) {
    var wrap = document.createElement("div");
    wrap.className = "board-row";
    var head = document.createElement("div");
    head.className = "row-label";
    head.textContent = label;
    wrap.appendChild(head);
    var row = document.createElement("div");
    row.className = "hero-row";
    heroes.forEach(function (hero, i) {
      row.appendChild(heroSlotEl(slotLabels ? slotLabels[i] : "", hero, entry));
    });
    wrap.appendChild(row);
    return wrap;
  }

  function appendText(tag, className, text) {
    var el = document.createElement(tag);
    el.className = className;
    el.textContent = text;
    boardEl.appendChild(el);
    return el;
  }

  function renderBoard(entry) {
    boardEl.innerHTML = "";
    if (!entry) {
      appendText("p", "empty", "No feasible lineup for this roster.");
      return;
    }
    var row = entry.row;
    // h2: the page's own <h1> is server-rendered and names the screen, so a
    // document had no heading at all during the multi-second first solve.
    appendText("h2", "board-title", (eventLabels[activeEvent] || activeEvent) + " · " + entry.label);

    if (!rowIsOk(row)) {
      appendText("p", "board-meta", "status: " + (row.status || "—"));
      appendText("p", "empty", row.error || "No optimal formation for this side.");
      return;
    }

    var meta =
      activeEvent === "arena"
        ? "score " + fmtScore(row.score)
        : fmtPoints(row.expected_personal_points) + " pts · " + troopsLine(row);
    var extra = activeEvent === "arena" ? "" : breakdownLine(row);
    appendText("p", "board-meta", extra ? meta + " · " + extra : meta);

    if (hasFormation(row)) {
      var f = row.formation;
      // The formation holds names; the hero entries hold whatever else the
      // API knows about them (an icon_url, when one is ever attached).
      var byName = heroesByName(row);
      function placed(slots) {
        return slots.map(function (s) {
          var name = f[s] || "";
          return byName[name] || name;
        });
      }
      boardEl.appendChild(boardRowEl("Front", FRONT_SLOTS, placed(FRONT_SLOTS), entry));
      boardEl.appendChild(boardRowEl("Back", BACK_SLOTS, placed(BACK_SLOTS), entry));
      return;
    }

    // No F/B structure (the sword/bear events march three heroes together).
    var heroes = (row.heroes || []).filter(function (hero) {
      return heroName(hero);
    });
    if (!heroes.length) {
      appendText("p", "empty", "No heroes in this result.");
      return;
    }
    boardEl.appendChild(boardRowEl("March", null, heroes, entry));
  }

  function renderNote() {
    var errors =
      activeEvent === "arena" ? {} : (bundle[activeEvent] || {}).mode_errors || {};
    var skipped = Object.keys(errors);
    if (!skipped.length) {
      noteEl.hidden = true;
      noteEl.textContent = "";
      return;
    }
    // Un-hidden before the text is written, for the same reason app.js's
    // toast is: a screen reader routinely misses a mutation to a hidden node.
    noteEl.hidden = false;
    noteEl.textContent = "Skipped as infeasible: " + skipped.map(humanKey).join(", ");
  }

  function render() {
    if (!bundle) return;
    eventButtons.forEach(function (btn) {
      var on = btn.dataset.event === activeEvent;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });

    var failure = sectionError(activeEvent);
    if (failure) {
      sectionErrEl.hidden = false;
      sectionErrEl.textContent = failure;
    } else {
      sectionErrEl.hidden = true;
      sectionErrEl.textContent = "";
    }

    var entries = entriesFor(activeEvent);
    var keys = entries.map(function (e) {
      return e.key;
    });
    if (keys.indexOf(chosen[activeEvent]) === -1) chosen[activeEvent] = keys[0];
    renderChips(entries);
    renderNote();
    renderBoard(
      entries.filter(function (e) {
        return e.key === chosen[activeEvent];
      })[0]
    );
  }

  /* --- loading -------------------------------------------------------------- */

  /** app.js's shared writer, bound to this page's status paragraph. The
   *  argument order is (text, kind) — this file used to take them the other
   *  way round from the Gear XP planner's identical copy. */
  function setStatus(text, kind) {
    window.setStatusLine(statusEl, text, kind);
  }

  function applyStatus(data) {
    var errors = data.errors || {};
    var keys = Object.keys(errors);
    var warnings = data.warnings || [];
    if (keys.length) {
      setStatus(
        keys
          .map(function (k) {
            return k + ": " + errors[k];
          })
          .join(" · "),
        "err"
      );
    } else if (warnings.length) {
      setStatus(warnings.join(" · "), "warn");
    } else {
      setStatus("Updated from the current heroes, gear and troops.", "ok");
    }
  }

  async function loadOptimize() {
    regenButtons.forEach(function (btn) {
      btn.disabled = true;
    });
    // "Recomputing" is a lie on the first load, when nothing has been
    // computed yet — and that first solve is the slow one.
    setStatus(bundle ? "Recomputing lineups…" : "Solving lineups…", "");
    try {
      var res = await fetch("/api/optimize", { cache: "no-store" });
      var text = await res.text();
      if (!res.ok) throw new Error(text || res.statusText);
      bundle = JSON.parse(text);
      render();
      applyStatus(bundle);
    } catch (err) {
      var message = String((err && err.message) || err);
      setStatus(message, "err");
      if (typeof window.showToast === "function") window.showToast(message, false);
    } finally {
      regenButtons.forEach(function (btn) {
        btn.disabled = false;
      });
    }
  }

  /* --- wiring --------------------------------------------------------------- */

  eventButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activeEvent = btn.dataset.event;
      render();
    });
  });

  regenButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      loadOptimize();
    });
  });

  // Close button + backdrop click + Escape, from app.js — the same three
  // triggers hero_detail.js wires, previously spelled out in both files.
  window.bindDialogDismiss(modal, modalClose, closeHeroSheet);

  loadOptimize();
})();
