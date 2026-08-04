/* Event lineups board (layout B) for /optimiser/events.
 *
 * Renders one screen at a time from a single GET /api/optimize: an event
 * segmented control, a grid of mode chips carrying that mode's points (or the
 * arena side's score), and a formation board for whichever chip is selected.
 * Tapping a hero opens the why + gear sheet — a bottom sheet on a phone, a
 * centred modal on a wide screen.
 *
 * One fetch serves every screen. /api/optimize solves sword, bear, both arena
 * sides and the Conquest formation in one go — several seconds of ILP — so
 * switching event or mode re-renders from the bundle already in hand rather
 * than re-solving.
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

  /* How each event is shaped inside the /api/optimize bundle. This is the
   * only place the difference is written down; everything below asks this
   * table rather than testing `=== "arena"`, which is what let Conquest join
   * without a fourth special case appearing in five functions.
   *
   *   "modes"  bundle[key].modes — a map of mode name to a points row that
   *            also carries troops, a capacity and a points breakdown.
   *   "sides"  bundle[key].attack / .defense — two scored 2F+3B formations.
   *   "single" bundle[key] *is* the row — one scored 2F+3B formation.
   *
   * An event with no entry falls back to "modes", the shape three of the
   * four have. */
  var EVENT_KIND = {
    sword: "modes",
    bear: "modes",
    arena: "sides",
    conquest: "single"
  };

  function kindOf(eventKey) {
    return EVENT_KIND[eventKey] || "modes";
  }

  /** True for the events whose rows carry an ILP `score` instead of
   *  `expected_personal_points`, and no troop counts at all: optimize_arena
   *  and optimize_conquest both score from the catalog, their roles YAML and
   *  gear, and neither one reads troops.yaml. Asking for a troops line on
   *  those boards would render "I — · C — · A — · cap —". */
  function isScored(eventKey) {
    return kindOf(eventKey) !== "modes";
  }

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

  /** app.js's shared origin check — see there for the rule and why it is not
   *  defined here. This file used to own it, which left hero_detail.js doing
   *  the structurally identical thing to the same `icon_url` field with no
   *  check at all. What it returns is still escaped before it reaches an
   *  attribute — see renderGearGrid. */
  var safeUrl = window.safeUrl;

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
   *  side, or the single Conquest formation. Arena sides are listed even
   *  when they failed, so a broken side can still be selected and read
   *  rather than vanishing; Conquest is listed on the same terms. */
  function entriesFor(eventKey) {
    if (!bundle) return [];
    var kind = kindOf(eventKey);
    if (kind === "sides") {
      var arena = bundle[eventKey] || {};
      return ARENA_SIDES.filter(function (side) {
        return arena[side];
      }).map(function (side) {
        return { key: side, label: side, row: arena[side] };
      });
    }
    if (kind === "single") {
      // One chip, so the score has somewhere to live and the board keeps one
      // model: every screen is "pick an entry, draw its row".
      var row = bundle[eventKey];
      return row ? [{ key: eventKey, label: "formation", row: row }] : [];
    }
    var modes = (bundle[eventKey] || {}).modes || {};
    return Object.keys(modes).map(function (mode) {
      return { key: mode, label: humanKey(mode), row: modes[mode] };
    });
  }

  /** A whole section the solver could not produce at all. */
  function sectionError(eventKey) {
    if (!bundle) return "";
    if (kindOf(eventKey) === "sides") {
      var arena = bundle[eventKey] || {};
      var parts = [];
      ARENA_SIDES.forEach(function (side) {
        var row = arena[side] || {};
        if (row.error) parts.push(side + ": " + row.error);
      });
      return parts.join(" · ");
    }
    // "modes" and "single" agree here: run_optimize_bundle gives a failed
    // section and a failed Conquest solve the same {status: "Error", error}
    // pair, the latter on the row itself.
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

  /** Hero names for a row in the same order the board places them: the
   *  formation slots (F1, F2, B1..B3) when the row has one, otherwise the
   *  heroes list order the sword/bear march uses. The contribution table
   *  and the board's own row-builder both need one hero list in one order. */
  function orderedHeroNames(row) {
    if (hasFormation(row)) {
      var f = row.formation;
      return ALL_SLOTS.map(function (s) {
        return f[s];
      }).filter(Boolean);
    }
    return (row.heroes || []).map(heroName).filter(Boolean);
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
    if (isScored(eventKey)) {
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

  /* --- stat contributions ---------------------------------------------------
   *
   * Every optimiser row carries the same three keys (see optimize_run.py):
   * `stat_family`, `formation_totals` and `contributions`. Conquest shares are
   * flat stat points and sum; expedition shares are percent points and also
   * sum — which is why the formatter takes the family rather than guessing
   * from magnitude.
   */

  function fmtShare(n, family) {
    if (n == null || !Number.isFinite(Number(n))) return "—";
    if (family === "expedition") return Number(n).toFixed(1) + "%";
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  /** The row's formation-level split, or null when the row is not Optimal. */
  function totalsOf(row) {
    var totals = row && row.formation_totals;
    return totals && totals.power ? totals : null;
  }

  /** Mirrors stat_contributions.contribution_strength's own per-family
   *  scale (combat / 10,000, health / 100,000): a stat's raw total is not a
   *  fair measure of how much it actually moves the ILP score. Health is
   *  naturally an order of magnitude bigger than Attack/Defense even on a
   *  lineup where Attack/Defense contribute more to the number that decides
   *  the formation — picking "top 3 by raw total" would show HP every time
   *  regardless of which stats the optimiser actually weighed heavier. */
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

  /** Chips: the power split, then the stats that most moved the score for
   *  that family — not simply the largest raw numbers (see scoreWeight). */
  function renderContributionStrip(row) {
    var totals = totalsOf(row);
    if (!totals) return "";
    var family = row.stat_family || totals.family || "conquest";
    var p = totals.power;
    var facts = [
      ["power", fmtShare(p.total, "conquest")],
      ["from hero", fmtShare(p.hero, "conquest")],
      ["from skills", fmtShare(p.skills, "conquest")],
      ["from gear", fmtShare(p.gear, "conquest")]
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
          '<div class="fact"><div class="fact-k">' + esc(pair[0]) +
          '</div><div class="fact-v">' + esc(pair[1]) + "</div></div>"
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
      esc(fmtShare(share.hero, fam)) + " hero · +" +
      esc(fmtShare(share.skills, fam)) + " skills · +" +
      esc(fmtShare(share.gear, fam)) + " gear" +
      "</span>"
    );
  }

  /** Wraps the assembled head/body/total rows in the shared table chrome —
   *  heading, note (with the estimated/skills-partial flags every family
   *  shares), and the scroll container. */
  function contribTableShell(family, totals, headHtml, bodyHtml, totalRowHtml, extraNote) {
    var flags = [];
    if (totals && totals.estimated) flags.push("estimated");
    if (totals && totals.skills_incomplete) flags.push("skills partial");
    var bits = ["each cell: total, then hero · skills delta (+) · gear delta (+)"];
    if (extraNote) bits.push(extraNote);
    if (flags.length) bits.push(flags.join(" · "));
    return (
      '<h3 class="section-title">Stat contributions · ' + esc(family) + "</h3>" +
      '<p class="contrib-note">' + esc(bits.join(" · ")) + "</p>" +
      '<div class="table-scroll"><table class="contrib-table"><thead>' +
      headHtml + "</thead><tbody>" + bodyHtml + totalRowHtml + "</tbody></table></div>"
    );
  }

  /** "Cavalry Attack" -> "Attack": the stat name shared across every troop. */
  function genericStatName(label) {
    var parts = String(label).split(" ");
    return parts[parts.length - 1];
  }

  /** "Cavalry Attack" -> "Cavalry": everything before the stat name. */
  function unitOf(label) {
    var parts = String(label).split(" ");
    return parts.slice(0, parts.length - 1).join(" ");
  }

  var EXPEDITION_STAT_ORDER = ["Attack", "Defense", "Health", "Lethality"];

  /** A hero's expedition contribution only ever carries its own troop's four
   *  labels ("Cavalry Attack", "Cavalry Defense", ...) — every other troop's
   *  columns would just be "—" for that hero. Collapse to one generic
   *  Attack/Defense/Health/Lethality column plus a Unit column naming which
   *  troop the numbers belong to, and sum same-stat labels across troops for
   *  the formation total (so "Attack" totals Infantry + Cavalry + Archer). */
  function renderExpeditionContributionTable(row, names, contributions, family) {
    var perHero = {};
    var presentStats = [];
    names.forEach(function (name) {
      var stats = contributions[name].stats || {};
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
      order.map(function (s) { return "<th>" + esc(s) + "</th>"; }).join("") +
      "</tr>";
    var body = names
      .map(function (name) {
        var c = contributions[name];
        var info = perHero[name];
        return (
          "<tr><td>" + esc(name) + "</td>" +
          "<td>" + contribSplit(c.power, "conquest") + "</td>" +
          "<td>" + esc(info.unit || "—") + "</td>" +
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
        esc(fmtShare(totals.power.total, "conquest")) + "</td><td>—</td>" +
        order
          .map(function (s) {
            var share = totalByStat[s];
            return "<td>" + esc(share ? fmtShare(share.total, family) : "—") + "</td>";
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

  /** Conquest labels (Hero Attack, Escort Health, …) are shared across every
   *  troop already, so every hero has the same columns — no collapsing
   *  needed, just the union of whatever labels are present. */
  /** Which of a formation row's placed names sit in FRONT_SLOTS / BACK_SLOTS,
   *  in slot order — [] for either when the row has no formation at all. */
  function frontBackNames(row, names) {
    var formation = row.formation || {};
    function inSlots(slots) {
      return slots
        .map(function (s) { return formation[s]; })
        .filter(function (n) { return n && names.indexOf(n) !== -1; });
    }
    return { front: inSlots(FRONT_SLOTS), back: inSlots(BACK_SLOTS) };
  }

  function renderConquestContributionTable(row, names, contributions, family) {
    var labels = [];
    names.forEach(function (name) {
      Object.keys(contributions[name].stats || {}).forEach(function (label) {
        if (labels.indexOf(label) === -1) labels.push(label);
      });
    });

    function heroRow(name) {
      var c = contributions[name];
      return (
        "<tr><td>" + esc(name) + "</td>" +
        "<td>" + contribSplit(c.power, "conquest") + "</td>" +
        labels
          .map(function (l) {
            return "<td>" + contribSplit((c.stats || {})[l], family) + "</td>";
          })
          .join("") +
        "</tr>"
      );
    }

    function subtotalRow(label, sectionNames) {
      var power = 0;
      var byLabel = {};
      labels.forEach(function (l) { byLabel[l] = 0; });
      sectionNames.forEach(function (name) {
        var c = contributions[name];
        power += c.power.total;
        labels.forEach(function (l) {
          var share = (c.stats || {})[l];
          if (share) byLabel[l] += share.total;
        });
      });
      return (
        '<tr class="contrib-total"><td>' + esc(label) + "</td><td>" +
        esc(fmtShare(power, "conquest")) + "</td>" +
        labels
          .map(function (l) { return "<td>" + esc(fmtShare(byLabel[l], family)) + "</td>"; })
          .join("") +
        "</tr>"
      );
    }

    var head =
      "<tr><th>hero</th><th>power</th>" +
      labels.map(function (l) { return "<th>" + esc(l) + "</th>"; }).join("") +
      "</tr>";

    var sections = frontBackNames(row, names);
    var body;
    if (sections.front.length || sections.back.length) {
      // Mirrors the survival model's own tau_F/tau_B split: a player reads
      // "is my front row actually tanky" without re-deriving it from one
      // flat five-hero list.
      var colspan = 2 + labels.length;
      var sectionHead = function (label) {
        return '<tr class="contrib-section"><td colspan="' + colspan + '">' + esc(label) + "</td></tr>";
      };
      body =
        sectionHead("Front") +
        sections.front.map(heroRow).join("") +
        subtotalRow("front", sections.front) +
        sectionHead("Back") +
        sections.back.map(heroRow).join("") +
        subtotalRow("back", sections.back);
    } else {
      body = names.map(heroRow).join("");
    }

    var totals = totalsOf(row);
    var totalRow = totals
      ? '<tr class="contrib-total"><td>formation</td><td>' +
        esc(fmtShare(totals.power.total, "conquest")) + "</td>" +
        labels
          .map(function (l) {
            var share = (totals.stats || {})[l];
            return "<td>" + esc(share ? fmtShare(share.total, family) : "—") + "</td>";
          })
          .join("") +
        "</tr>"
      : "";
    return contribTableShell(family, totals, head, body, totalRow, null);
  }

  /** One row per placed hero, plus a formation total row. */
  function renderContributionTable(row) {
    var contributions = (row && row.contributions) || null;
    if (!contributions) return "";
    var family = row.stat_family || "conquest";
    var names = orderedHeroNames(row).filter(function (n) {
      return contributions[n];
    });
    if (!names.length) return "";
    return family === "expedition"
      ? renderExpeditionContributionTable(row, names, contributions, family)
      : renderConquestContributionTable(row, names, contributions, family);
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
      appendText("p", "empty", row.error || "No optimal formation for this lineup.");
      return;
    }

    var meta = isScored(activeEvent)
      ? "score " + fmtScore(row.score)
      : fmtPoints(row.expected_personal_points) + " pts · " + troopsLine(row);
    var extra = isScored(activeEvent) ? "" : breakdownLine(row);
    appendText("p", "board-meta", extra ? meta + " · " + extra : meta);

    var strip = renderContributionStrip(row);
    if (strip) {
      var stripEl = document.createElement("div");
      stripEl.innerHTML = strip;
      boardEl.appendChild(stripEl);
    }

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
    } else {
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

    // Per-hero split lives on the board itself, not behind a tap into the
    // hero sheet — it's the number a player checks every time they look at
    // a lineup, not an occasional drill-down.
    var table = renderContributionTable(row);
    if (table) {
      var tableEl = document.createElement("div");
      tableEl.innerHTML = table;
      boardEl.appendChild(tableEl);
    }
  }

  function renderNote() {
    // Only a "modes" event can skip one: an infeasible arena side or
    // Conquest formation is the whole screen, and says so on the board.
    var errors =
      kindOf(activeEvent) === "modes" ? (bundle[activeEvent] || {}).mode_errors || {} : {};
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
      if (!res.ok) {
        // FastAPI answers an HTTPException with {"detail": "..."}, which is
        // what the user should read; an *unhandled* exception answers with
        // plain "Internal Server Error", which is the fallback below. Showing
        // the body raw put the JSON braces on screen the moment this endpoint
        // grew its first HTTPException — the two rescan endpoints already
        // have one.
        var failed = null;
        try {
          failed = JSON.parse(text);
        } catch (_) {
          failed = null;
        }
        throw new Error(window.detailOf(failed, text || res.statusText));
      }
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
