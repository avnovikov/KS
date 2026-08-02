/* Executable coverage for the Event lineups board's client logic.
 *
 * The whole screen — the event segmented control, the mode chips, the
 * formation board, the hero sheet, the escaping and every error path — is
 * built in the browser from one GET /api/optimize. None of that is visible to
 * a page-render test, and a source grep cannot tell whether any of it works.
 *
 * So this does what tests/js/inventory_harness.js does for the inventory
 * table: stands up a fake DOM and a recordable fetch, then runs the *real,
 * unmodified* sources — ks/heroes/ui/static/app.js (which publishes the
 * shared escapeHtml and bindDialogDismiss the board depends on) and
 * ks/heroes/ui/static/optimiser_events.js — injected at the markers below by
 * tests/test_heroes_optimiser_events_js.py.
 *
 * Protocol: a single line "@@RESULTS@@<json>" on stdout, holding
 * {checks: [{name, ok, detail}], data: {...}}. Anything that throws is
 * reported as a failing check rather than a silent non-zero exit.
 */

// Captured before anything is stubbed: node has console.log, jsc has print.
var EMIT = typeof print === "function" ? print : console.log.bind(console);

var checks = [];
var data = {};

function check(name, ok, detail) {
  checks.push({ name: name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });
}

function record(key, value) {
  data[key] = value;
}

/* --- fake DOM -------------------------------------------------------------- */

/**
 * Minimal element.
 *
 * `className` and `classList` are two views of one list, as in a real DOM:
 * the script sets `className` on the chips it builds and calls
 * `classList.toggle` on the event segments, and a harness where those two
 * drifted would let a real bug through.
 *
 * `innerHTML` and `textContent` both clear the child list when written, which
 * is what makes `el.innerHTML = ""` followed by `appendChild` behave the way
 * the script assumes.
 */
function El(tag) {
  this.tag = String(tag).toLowerCase();
  this.attrs = {};
  this.dataset = {};
  this.listeners = {};
  this.children = [];
  this.parent = null;
  this.hidden = false;
  this.disabled = false;
  this.focused = 0;
  this._classes = [];
  this._html = "";
  this._text = "";
}

Object.defineProperty(El.prototype, "className", {
  get: function () {
    return this._classes.join(" ");
  },
  set: function (value) {
    this._classes = String(value)
      .split(/\s+/)
      .filter(Boolean);
  },
});

Object.defineProperty(El.prototype, "innerHTML", {
  get: function () {
    return this._html;
  },
  set: function (value) {
    this._html = String(value);
    this._text = "";
    this.children = [];
  },
});

Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    return this._text;
  },
  set: function (value) {
    this._text = String(value);
    this._html = "";
    this.children = [];
  },
});

El.prototype._classIndex = function (name) {
  return this._classes.indexOf(name);
};

El.prototype.getAttribute = function (name) {
  return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
};
El.prototype.setAttribute = function (name, value) {
  this.attrs[name] = String(value);
};
El.prototype.removeAttribute = function (name) {
  delete this.attrs[name];
};
El.prototype.addEventListener = function (type, fn) {
  (this.listeners[type] = this.listeners[type] || []).push(fn);
};
El.prototype.fire = function (type, event) {
  (this.listeners[type] || []).slice().forEach(function (fn) {
    fn(event || { type: type });
  });
};
El.prototype.appendChild = function (child) {
  var at = this.children.indexOf(child);
  if (at !== -1) this.children.splice(at, 1);
  this.children.push(child);
  child.parent = this;
  return child;
};
El.prototype.focus = function () {
  this.focused += 1;
};

Object.defineProperty(El.prototype, "classList", {
  get: function () {
    var self = this;
    return {
      add: function (name) {
        if (self._classIndex(name) === -1) self._classes.push(name);
      },
      remove: function (name) {
        var at = self._classIndex(name);
        if (at !== -1) self._classes.splice(at, 1);
      },
      toggle: function (name, force) {
        var on = force === undefined ? self._classIndex(name) === -1 : !!force;
        if (on) this.add(name);
        else this.remove(name);
        return on;
      },
      contains: function (name) {
        return self._classIndex(name) !== -1;
      },
    };
  },
});

/* --- page builder ---------------------------------------------------------- */

/** Ids and data-attributes are transcribed from optimiser_events.html; if the
 *  template renames one, the script stops finding it and the suites fail. */
var EVENT_SEGMENTS = [
  { key: "sword", label: "Swordland" },
  { key: "bear", label: "Bear Trap" },
  { key: "arena", label: "Arena" },
];

/**
 * Build the Event lineups page and install it over the globals the script
 * reaches for. Each suite gets its own, so no state leaks between scenarios.
 *
 * @param {Object} spec {bundle} the JSON GET /api/optimize replies with, or
 *        {status, body} to make that call fail.
 */
function makePage(spec) {
  function el(tag, id, className) {
    var node = new El(tag);
    if (id) node.attrs.id = id;
    if (className) node.className = className;
    return node;
  }

  var boardEl = el("section", "board", "panel board");
  var statusEl = el("p", "lineup-status", "status-line");
  var chipsEl = el("div", "mode-chips");
  var noteEl = el("p", "mode-note", "mode-note");
  noteEl.hidden = true;
  var sectionErrEl = el("p", "section-error", "banner-err");
  sectionErrEl.hidden = true;

  var modal = el("div", "gear-detail-modal", "modal-backdrop sheet");
  modal.hidden = true;
  var modalTitle = el("h2", "gear-modal-title");
  var modalSub = el("div", "gear-modal-sub", "modal-sub");
  var modalBody = el("div", "gear-modal-body", "modal-body");
  var modalClose = el("button", "gear-modal-close", "modal-close");

  var eventButtons = EVENT_SEGMENTS.map(function (seg, i) {
    var btn = new El("button");
    btn.className = i === 0 ? "seg on" : "seg";
    btn.dataset.event = seg.key;
    btn.textContent = seg.label;
    btn.setAttribute("aria-pressed", i === 0 ? "true" : "false");
    return btn;
  });

  var regenBtn = new El("button");
  regenBtn.attrs.id = "regen-btn";
  regenBtn.dataset.regen = "all";
  regenBtn.textContent = "Regenerate";

  var byId = {
    board: boardEl,
    "lineup-status": statusEl,
    "mode-chips": chipsEl,
    "mode-note": noteEl,
    "section-error": sectionErrEl,
    "gear-detail-modal": modal,
    "gear-modal-title": modalTitle,
    "gear-modal-sub": modalSub,
    "gear-modal-body": modalBody,
    "gear-modal-close": modalClose,
  };

  var documentListeners = {};
  globalThis.document = {
    getElementById: function (id) {
      return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null;
    },
    querySelectorAll: function (selector) {
      if (selector === "[data-event]") return eventButtons.slice();
      if (selector === "[data-regen]") return [regenBtn];
      throw new Error("harness: unsupported selector " + selector);
    },
    createElement: function (tag) {
      return new El(tag);
    },
    addEventListener: function (type, fn) {
      (documentListeners[type] = documentListeners[type] || []).push(fn);
    },
  };

  /* --- recordable fetch --------------------------------------------------- */

  var calls = [];
  var replies = [];
  var pendingResolve = null;

  function replyFor() {
    var reply = replies.length ? replies.shift() : spec;
    var ok = reply.status === undefined ? true : reply.status >= 200 && reply.status < 300;
    var body =
      reply.body !== undefined ? reply.body : JSON.stringify(reply.bundle === undefined ? {} : reply.bundle);
    return {
      ok: ok,
      status: reply.status === undefined ? 200 : reply.status,
      statusText: reply.statusText || "",
      text: function () {
        return Promise.resolve(body);
      },
    };
  }

  globalThis.fetch = function (url, options) {
    calls.push({ url: url, cache: (options || {}).cache });
    var res = replyFor();
    if (pendingResolve === "hold") {
      return new Promise(function (resolve) {
        pendingResolve = function () {
          resolve(res);
        };
      });
    }
    return Promise.resolve(res);
  };

  /* --- window ------------------------------------------------------------- */

  var toasts = [];
  globalThis.window = {
    addEventListener: function () {},
    showToast: function (message, ok) {
      toasts.push({ msg: String(message), ok: !!ok });
    },
  };

  /* --- driver ------------------------------------------------------------- */

  function childrenWithClass(node, name) {
    return node.children.filter(function (child) {
      return child.classList.contains(name);
    });
  }

  return {
    boardEl: boardEl,
    statusEl: statusEl,
    chipsEl: chipsEl,
    noteEl: noteEl,
    sectionErrEl: sectionErrEl,
    modal: modal,
    modalTitle: modalTitle,
    modalSub: modalSub,
    modalBody: modalBody,
    modalClose: modalClose,
    regenBtn: regenBtn,
    calls: calls,
    toasts: toasts,

    /** Queue the reply for the *next* fetch, overriding the suite default. */
    queueReply: function (reply) {
      replies.push(reply);
    },
    holdNextFetch: function () {
      pendingResolve = "hold";
    },
    releaseFetch: function () {
      var fn = pendingResolve;
      pendingResolve = null;
      if (typeof fn === "function") fn();
    },

    eventButton: function (key) {
      for (var i = 0; i < eventButtons.length; i++) {
        if (eventButtons[i].dataset.event === key) return eventButtons[i];
      }
      return null;
    },
    eventButtons: eventButtons,

    chips: function () {
      return chipsEl.children.slice();
    },
    chipText: function (i) {
      return chipsEl.children[i] ? chipsEl.children[i].innerHTML : "";
    },
    selectedChip: function () {
      var on = chipsEl.children.filter(function (chip) {
        return chip.classList.contains("on");
      });
      return on.length === 1 ? on[0] : null;
    },

    boardTitle: function () {
      var t = childrenWithClass(boardEl, "board-title");
      return t.length ? t[0].textContent : "";
    },
    boardMeta: function () {
      var m = childrenWithClass(boardEl, "board-meta");
      return m.length ? m[0].textContent : "";
    },
    boardEmpty: function () {
      var e = childrenWithClass(boardEl, "empty");
      return e.length ? e[0].textContent : "";
    },
    /** [{label, slots: [{name, tag, portraitInitials, imgSrc, el, img}]}] */
    rows: function () {
      return childrenWithClass(boardEl, "board-row").map(function (rowEl) {
        var label = childrenWithClass(rowEl, "row-label")[0];
        var heroRow = childrenWithClass(rowEl, "hero-row")[0];
        var slots = (heroRow ? heroRow.children : []).map(function (slot) {
          var portrait = childrenWithClass(slot, "portrait")[0];
          var nameEl = childrenWithClass(slot, "hero-slot-name")[0];
          var tagEl = childrenWithClass(slot, "slot-tag")[0];
          var img = portrait && portrait.children.length ? portrait.children[0] : null;
          return {
            el: slot,
            tag: slot.tag,
            empty: slot.classList.contains("is-empty"),
            name: nameEl ? nameEl.textContent : "",
            slotTag: tagEl ? tagEl.textContent : "",
            initials: portrait ? portrait.textContent : "",
            img: img,
            imgSrc: img ? img.src : "",
            ariaLabel: slot.getAttribute("aria-label"),
          };
        });
        return { label: label ? label.textContent : "", slots: slots };
      });
    },
    slot: function (name) {
      var found = null;
      this.rows().forEach(function (row) {
        row.slots.forEach(function (slot) {
          if (slot.name === name) found = slot;
        });
      });
      return found;
    },

    pressEscape: function () {
      (documentListeners.keydown || []).slice().forEach(function (fn) {
        fn({ key: "Escape" });
      });
    },
    clickBackdrop: function () {
      modal.fire("click", { target: modal });
    },
    clickInsideModal: function () {
      modal.fire("click", { target: modalBody });
    },
    sheetOpen: function () {
      return !modal.hidden && modal.classList.contains("open");
    },
  };
}

/** Drain the microtask queue so awaited fetch continuations have all run. */
async function settle() {
  for (var i = 0; i < 80; i++) await Promise.resolve();
}

/* --- the units under test, injected verbatim by the pytest runner ---------- */

/** Runs ks/heroes/ui/static/app.js, which publishes showToast, escapeHtml
 *  and bindDialogDismiss. */
function loadSharedAppJs() {
// @@APP_JS@@
}

/** Runs ks/heroes/ui/static/optimiser_events.js against whatever makePage()
 *  installed. */
function loadBoardScript() {
// @@OPTIMISER_EVENTS_JS@@
}

/** app.js first, then the page script — the load order _layout.html produces.
 *  The harness's own showToast stub is restored afterwards so toasts stay
 *  inspectable; app.js's real one is covered by the troops harness. */
async function boot(page) {
  var stub = globalThis.window.showToast;
  loadSharedAppJs();
  globalThis.window.showToast = stub;
  loadBoardScript();
  await settle();
  return page;
}

/* --- fixtures --------------------------------------------------------------- */

function loo(points, alternates) {
  return {
    baseline_points: 26152.4,
    points_without: 26152.4 - points,
    marginal_points: points,
    critical: false,
    inconclusive: false,
    alternate_lineup: alternates,
    replacement_heroes: alternates,
    status: "Optimal",
  };
}

/** The two leave_one_out shapes explain.py can emit besides a plain marginal
 *  cost. Neither was reachable from any fixture until they were added here,
 *  so both branches of renderWhy went unexecuted. */
function criticalLoo() {
  return {
    baseline_points: 26152.4,
    marginal_points: null,
    critical: true,
    inconclusive: false,
    status: "Infeasible",
  };
}

function inconclusiveLoo(status) {
  return {
    baseline_points: 26152.4,
    marginal_points: null,
    critical: false,
    inconclusive: true,
    status: status,
  };
}

function eventHero(name, role, points) {
  return {
    name: name,
    reason: "role=" + role,
    explain: {
      role: role,
      fits_because: ["Satisfies required defense widget", "Mode strength score=121.0"],
      leave_one_out: loo(points, ["Amadeus", "Howard"]),
    },
  };
}

function eventMode(names, points) {
  return {
    recommended_mode: "garrison",
    heroes: names.map(function (n, i) {
      return eventHero(n, i === 0 ? "defense_widget" : "infantry_support", 220 + i);
    }),
    troops: { infantry: 33858, cavalry: 17051, archers: 29386 },
    effective_capacity: 80295,
    expected_personal_points: points,
    breakdown: { combat: 1902.4, occupation: 24000, first_control: 50, loot: 200 },
    gear_assignment: {
      Hilde: [
        {
          slot: "helmet",
          piece_id: "p1",
          name: "Judicator's Armet",
          rarity: "mythic",
          enhancement_level: 51,
          mastery_level: 2,
          power: 152100,
          icon_url: "/gear-icons/p1.png",
        },
        { slot: "boots", piece_id: "p2", name: "Warden Greaves", rarity: "epic", power: 41000 },
      ],
    },
  };
}

function arenaSide(side, formation) {
  var explanations = {};
  Object.keys(formation).forEach(function (slot) {
    explanations[formation[slot]] = {
      role: slot.charAt(0) === "F" ? "front_fighter" : "back_dps",
      slot: slot,
      fits_because: ["Placed " + slot, "arena base score=131.0"],
      leave_one_out: {
        baseline_score: 636.3,
        marginal_score: 64.4,
        critical: false,
        inconclusive: false,
        alternate_lineup: ["Howard"],
        status: "Optimal",
      },
    };
  });
  return {
    side: side,
    formation: formation,
    heroes: Object.keys(formation).map(function (s) {
      return formation[s];
    }),
    score: side === "attack" ? 636.4 : 588.1,
    gear_assignment: null,
    reasons: {},
    status: "Optimal",
    explanations: explanations,
  };
}

function goodBundle() {
  return {
    errors: {},
    warnings: [],
    heroes_dir: "/tmp/heroes",
    sword: {
      label: "Swordland",
      event: "swordland",
      status: "ok",
      modes: {
        garrison: eventMode(["Hilde", "Howard", "Saul"], 26152.46),
        rally_lead: eventMode(["Amadeus", "Jabel", "Diana"], 18110.2),
      },
    },
    bear: {
      label: "Bear Trap",
      status: "ok",
      modes: { solo: eventMode(["Helga", "Chenko", "Marlin"], 9000.4) },
    },
    arena: {
      attack: arenaSide("attack", {
        F1: "Helga",
        F2: "Amadeus",
        B1: "Chenko",
        B2: "Jabel",
        B3: "Diana",
      }),
      defense: arenaSide("defense", {
        F1: "Howard",
        F2: "Helga",
        B1: "Saul",
        B2: "Jabel",
        B3: "Diana",
      }),
    },
  };
}

/* --- suites ----------------------------------------------------------------- */

async function suiteFirstRender() {
  var d = makePage({ bundle: goodBundle() });
  await boot(d);

  check("the board loads itself from /api/optimize", d.calls.length === 1, JSON.stringify(d.calls));
  check(
    "and asks for a fresh answer rather than a cached one",
    d.calls[0] && d.calls[0].cache === "no-store",
    JSON.stringify(d.calls[0])
  );
  check("Swordland is the event the page opens on", d.boardTitle().indexOf("Swordland") === 0, d.boardTitle());
  check("one chip per mode of that event", d.chips().length === 2, "chips=" + d.chips().length);
  check(
    "the first mode is selected for the user",
    d.selectedChip() === d.chips()[0],
    d.chips()
      .map(function (c) {
        return c.className;
      })
      .join(" | ")
  );
  check(
    "and says so for assistive tech",
    d.chips()[0].getAttribute("aria-pressed") === "true" &&
      d.chips()[1].getAttribute("aria-pressed") === "false",
    d.chips()
      .map(function (c) {
        return c.getAttribute("aria-pressed");
      })
      .join(",")
  );
  check("each chip carries its own points", d.chipText(0).indexOf("pts") !== -1, d.chipText(0));
  check(
    "the chip names the mode, underscores unpicked",
    d.chipText(1).indexOf("rally lead") !== -1,
    d.chipText(1)
  );
  record("first_chip_html", d.chipText(0));
  check(
    "the board titles the selected mode, not just the event",
    d.boardTitle() === "Swordland · garrison",
    d.boardTitle()
  );
  check(
    "the board meta carries the points",
    d.boardMeta().indexOf("pts") !== -1 && d.boardMeta().indexOf("152") !== -1,
    d.boardMeta()
  );
  check(
    "and the troops line the brief asks for",
    d.boardMeta().indexOf("I ") !== -1 &&
      d.boardMeta().indexOf("C ") !== -1 &&
      d.boardMeta().indexOf("A ") !== -1 &&
      d.boardMeta().indexOf("cap") !== -1,
    d.boardMeta()
  );
  check(
    "and the points breakdown behind them",
    d.boardMeta().indexOf("combat") !== -1 && d.boardMeta().indexOf("occupation") !== -1,
    d.boardMeta()
  );
  record("sword_board_meta", d.boardMeta());

  var rows = d.rows();
  check("a non-arena mode is one row, not a Front/Back split", rows.length === 1, "rows=" + rows.length);
  check("labelled March", rows.length === 1 && rows[0].label === "March", rows.length ? rows[0].label : "");
  check(
    "holding the mode's three heroes in order",
    rows.length === 1 &&
      rows[0].slots
        .map(function (s) {
          return s.name;
        })
        .join(",") === "Hilde,Howard,Saul",
    rows.length
      ? rows[0].slots
          .map(function (s) {
            return s.name;
          })
          .join(",")
      : ""
  );
  check(
    "every hero is a real button, so it is reachable without a pointer",
    rows[0].slots.every(function (s) {
      return s.tag === "button";
    }),
    rows[0].slots
      .map(function (s) {
        return s.tag;
      })
      .join(",")
  );
  check(
    "and is labelled for a screen reader",
    rows[0].slots[0].ariaLabel === "Hilde — why and gear",
    String(rows[0].slots[0].ariaLabel)
  );
  check(
    "portraits come from /static/heroes/<slug>.webp",
    d.slot("Hilde").imgSrc === "/static/heroes/hilde.webp",
    d.slot("Hilde").imgSrc
  );
  check(
    "with initials underneath for a hero with no artwork",
    d.slot("Hilde").initials === "HI",
    d.slot("Hilde").initials
  );
  check(
    "a portrait that fails to load is dropped rather than left as a broken image",
    (function () {
      var slot = d.slot("Howard");
      var before = slot.img.hidden;
      slot.img.fire("error");
      return before === false && slot.img.hidden === true;
    })(),
    "hidden=" + d.slot("Howard").img.hidden
  );
  check("the status line reports success", d.statusEl.classList.contains("ok"), d.statusEl.className);
  check(
    "and says what it recomputed from",
    d.statusEl.textContent.indexOf("heroes, gear and troops") !== -1,
    d.statusEl.textContent
  );
  check("no section error banner on a clean bundle", d.sectionErrEl.hidden === true, d.sectionErrEl.textContent);
  check("and no skipped-modes note", d.noteEl.hidden === true, d.noteEl.textContent);
}

async function suiteModeAndEventSwitching() {
  var d = makePage({ bundle: goodBundle() });
  await boot(d);

  d.chips()[1].fire("click");
  check(
    "tapping a chip moves the board to that mode",
    d.boardTitle() === "Swordland · rally lead",
    d.boardTitle()
  );
  check("and moves the selection with it", d.selectedChip() === d.chips()[1], d.selectedChip() ? d.selectedChip().className : "none");
  check(
    "the chip that lost it says so too",
    d.chips()[0].getAttribute("aria-pressed") === "false",
    d.chips()[0].getAttribute("aria-pressed")
  );
  check(
    "switching modes costs no extra request — one bundle serves every screen",
    d.calls.length === 1,
    "calls=" + d.calls.length
  );
  check(
    "and the board shows that mode's heroes",
    d.slot("Amadeus") !== null && d.slot("Hilde") === null,
    d.rows()[0].slots
      .map(function (s) {
        return s.name;
      })
      .join(",")
  );

  d.eventButton("bear").fire("click");
  check("tapping Bear Trap switches event", d.boardTitle().indexOf("Bear Trap") === 0, d.boardTitle());
  check("the event segment is marked selected", d.eventButton("bear").classList.contains("on"), d.eventButton("bear").className);
  check(
    "and the one it left is not",
    !d.eventButton("sword").classList.contains("on") &&
      d.eventButton("sword").getAttribute("aria-pressed") === "false",
    d.eventButton("sword").className + " " + d.eventButton("sword").getAttribute("aria-pressed")
  );
  check("its own modes replace the chips", d.chips().length === 1, "chips=" + d.chips().length);
  check("still without refetching", d.calls.length === 1, "calls=" + d.calls.length);

  d.eventButton("sword").fire("click");
  check(
    "going back restores the mode that was picked, not the first one",
    d.boardTitle() === "Swordland · rally lead",
    d.boardTitle()
  );
}

async function suiteArenaFormation() {
  var d = makePage({ bundle: goodBundle() });
  await boot(d);
  d.eventButton("arena").fire("click");

  check("arena chips are the two sides", d.chips().length === 2, "chips=" + d.chips().length);
  check(
    "carrying a score rather than points",
    d.chipText(0).indexOf("score") !== -1 && d.chipText(0).indexOf("pts") === -1,
    d.chipText(0)
  );
  check("attack is the side the board opens on", d.boardTitle() === "Arena · attack", d.boardTitle());
  check("the meta is the side's score", d.boardMeta().indexOf("636.4") !== -1, d.boardMeta());

  var rows = d.rows();
  check("arena keeps a Front row and a Back row", rows.length === 2, "rows=" + rows.length);
  check("named Front and Back", rows.length === 2 && rows[0].label === "Front" && rows[1].label === "Back", rows.map(function (r) { return r.label; }).join(","));
  check(
    "Front holds F1 and F2",
    rows[0].slots
      .map(function (s) {
        return s.slotTag + "=" + s.name;
      })
      .join(",") === "F1=Helga,F2=Amadeus",
    rows[0].slots
      .map(function (s) {
        return s.slotTag + "=" + s.name;
      })
      .join(",")
  );
  check(
    "Back holds B1..B3",
    rows[1].slots
      .map(function (s) {
        return s.slotTag + "=" + s.name;
      })
      .join(",") === "B1=Chenko,B2=Jabel,B3=Diana",
    rows[1].slots
      .map(function (s) {
        return s.slotTag + "=" + s.name;
      })
      .join(",")
  );
  record("arena_back_row", rows[1].slots.map(function (s) { return s.slotTag + "=" + s.name; }).join(","));

  d.chips()[1].fire("click");
  check("the defense side is its own board", d.boardTitle() === "Arena · defense", d.boardTitle());
  check(
    "with its own formation",
    d.rows()[0].slots[0].name === "Howard",
    d.rows()[0].slots[0].name
  );
}

async function suiteHeroSheet() {
  var d = makePage({ bundle: goodBundle() });
  await boot(d);

  check("the sheet starts closed", d.sheetOpen() === false, "hidden=" + d.modal.hidden);
  d.slot("Hilde").el.fire("click");
  check("tapping a hero opens it", d.sheetOpen() === true, "hidden=" + d.modal.hidden + " " + d.modal.className);
  check("titled with the hero", d.modalTitle.textContent === "Hilde", d.modalTitle.textContent);
  check(
    "sub-titled with the lineup it came from",
    d.modalSub.textContent === "Swordland · garrison",
    d.modalSub.textContent
  );
  check(
    "the close button takes focus, so the keyboard lands inside the sheet",
    d.modalClose.focused === 1,
    "focused=" + d.modalClose.focused
  );
  var body = d.modalBody.innerHTML;
  record("sheet_body", body);
  check("the why block explains the role", body.indexOf("defense_widget".replace("_", " ")) !== -1, body.slice(0, 200));
  check(
    "and lists why the solver picked this hero",
    body.indexOf("Satisfies required defense widget") !== -1,
    body.slice(0, 300)
  );
  check(
    "and what dropping them would cost",
    body.indexOf("Removing costs") !== -1 && body.indexOf("alternate lineup: Amadeus, Howard") !== -1,
    body
  );
  check("the gear grid names all four slots", ["Helm", "Gloves", "Body", "Boots"].every(function (label) {
    return body.indexOf(">" + label + "<") !== -1;
  }), body);
  check("an assigned piece is named", body.indexOf("Judicator&#39;s Armet") !== -1, body);
  check(
    "with its rarity, enhancement, mastery and power",
    body.indexOf("mythic · +51 · M2 · ") !== -1 && body.indexOf(" pwr") !== -1,
    body
  );
  check("and its icon", body.indexOf('src="/gear-icons/p1.png"') !== -1, body);
  check(
    "an unassigned slot reads Empty rather than being omitted",
    (body.match(/Empty/g) || []).length === 2,
    String((body.match(/Empty/g) || []).length)
  );

  d.modalClose.fire("click");
  check("Close closes it", d.sheetOpen() === false, "hidden=" + d.modal.hidden);

  d.slot("Howard").el.fire("click");
  check("a second hero reopens it with their own detail", d.modalTitle.textContent === "Howard", d.modalTitle.textContent);
  check(
    "a hero with no gear assigned still gets the four empty slots",
    (d.modalBody.innerHTML.match(/Empty/g) || []).length === 4,
    String((d.modalBody.innerHTML.match(/Empty/g) || []).length)
  );
  d.pressEscape();
  check("Escape closes it", d.sheetOpen() === false, "hidden=" + d.modal.hidden);

  d.slot("Saul").el.fire("click");
  d.clickInsideModal();
  check("a tap inside the sheet does not dismiss it", d.sheetOpen() === true, "hidden=" + d.modal.hidden);
  d.clickBackdrop();
  check("a tap on the backdrop does", d.sheetOpen() === false, "hidden=" + d.modal.hidden);

  d.eventButton("arena").fire("click");
  d.slot("Helga").el.fire("click");
  check(
    "an arena hero's sheet names their formation slot",
    d.modalSub.textContent === "Arena · attack · F1",
    d.modalSub.textContent
  );
  check(
    "and their arena reasoning, scored rather than pointed",
    d.modalBody.innerHTML.indexOf("64.4 score") !== -1,
    d.modalBody.innerHTML
  );
}

async function suiteEscaping() {
  var hostile = '<img src=x onerror="alert(1)">';
  var bundle = goodBundle();
  var mode = eventMode([hostile, "Howard", "Saul"], 1234);
  mode.heroes[0].explain.fits_because = ['Chosen because "<b>reasons</b>"'];
  mode.gear_assignment = {};
  mode.gear_assignment[hostile] = [
    {
      slot: "helmet",
      name: "<script>bad()</" + "script>",
      rarity: "<i>mythic</i>",
      power: 10,
      icon_url: "javascript:alert(1)",
    },
  ];
  bundle.sword.modes = {};
  bundle.sword.modes['evil" onmouseover="x'] = mode;

  var d = makePage({ bundle: bundle });
  await boot(d);

  var chip = d.chipText(0);
  record("hostile_chip_html", chip);
  check("a hostile mode name cannot break out of the chip markup", chip.indexOf('onmouseover="x') === -1, chip);
  check("it is escaped instead", chip.indexOf("evil&quot; onmouseover=&quot;x") !== -1, chip);

  var slot = d.slot(hostile);
  check("a hostile hero name still renders as a slot", slot !== null, "missing");
  check(
    "and lands as text, never as markup",
    slot.el.children[1].textContent === hostile && slot.el.children[1].innerHTML === "",
    slot.el.children[1].textContent + " | " + slot.el.children[1].innerHTML
  );
  check(
    "the portrait URL is slugified, not interpolated raw",
    slot.imgSrc === "/static/heroes/img-src-x-onerror-alert-1.webp",
    slot.imgSrc
  );

  slot.el.fire("click");
  var body = d.modalBody.innerHTML;
  record("hostile_sheet_body", body);
  check("the sheet escapes the hero's bullets", body.indexOf("<b>reasons</b>") === -1, body);
  check(
    "keeping the text visible in escaped form",
    body.indexOf("&lt;b&gt;reasons&lt;/b&gt;") !== -1,
    body
  );
  check("and escapes a hostile gear name", body.indexOf("<script>bad()") === -1, body);
  check(
    "a javascript: icon URL is dropped rather than rendered",
    body.indexOf("javascript:") === -1 && body.indexOf("<img") === -1,
    body
  );
  check(
    "the hero's own name in the sheet title is text, not markup",
    d.modalTitle.textContent === hostile && d.modalTitle.innerHTML === "",
    d.modalTitle.textContent
  );

  // The chip's second line is API-derived too: a non-Optimal arena side puts
  // its raw `status` string there.
  var bundleStatus = goodBundle();
  bundleStatus.arena.defense.status = 'Broken" onmouseover="x';
  var dStatus = makePage({ bundle: bundleStatus });
  await boot(dStatus);
  dStatus.eventButton("arena").fire("click");
  check(
    "a hostile solver status cannot break out of the chip either",
    dStatus.chipText(1).indexOf('onmouseover="x') === -1 &&
      dStatus.chipText(1).indexOf("Broken&quot; onmouseover=&quot;x") !== -1,
    dStatus.chipText(1)
  );

  /* The gear icon is the only place a safeUrl-approved value reaches an HTML
     *attribute*, and the two obviously-bad URLs above never get that far —
     safeUrl rejects them before esc() is reached, so they prove nothing about
     the escape. `/x.png" onerror="alert(1)` is the case that matters: a
     perfectly good same-origin path that closes the src attribute if it goes
     in raw. All four gear slots are loaded so each cell renders one. */
  var bundle2 = goodBundle();
  bundle2.sword.modes.garrison.gear_assignment.Hilde = [
    { slot: "helmet", name: "A", icon_url: "//evil.example/x.png" },
    { slot: "gloves", name: "B", icon_url: "/\\evil.example/x.png" },
    { slot: "chest", name: "C", icon_url: "https://evil.example/x.png" },
    { slot: "boots", name: "D", icon_url: '/x.png" onerror="alert(1)' },
  ];
  var d2 = makePage({ bundle: bundle2 });
  await boot(d2);
  d2.slot("Hilde").el.fire("click");
  var gear = d2.modalBody.innerHTML;
  record("hostile_gear_html", gear);
  check(
    "a protocol-relative icon URL is refused",
    gear.indexOf("//evil.example") === -1,
    gear
  );
  check(
    "so is its backslash spelling, which a browser parses the same way",
    gear.indexOf("evil.example") === -1,
    gear
  );
  check(
    "and an absolute off-site URL, since every icon the app makes is a path",
    gear.indexOf("https:") === -1,
    gear
  );
  check(
    "a same-origin path that would close the src attribute is escaped, not waved through",
    gear.indexOf('src="/x.png&quot; onerror=&quot;alert(1)"') !== -1,
    gear
  );
  check(
    "so no onerror handler ever reaches the markup",
    gear.indexOf('onerror="alert') === -1,
    gear
  );

  /* The `&` in esc(). Dropping it from app.js killed no check anywhere, and
     it is the one replacement whose absence *re-enables* the other four: an
     attacker who cannot write `"` writes `&quot;` instead, and a browser
     decodes that back to a quote when it parses the attribute. Same
     same-origin path as the case above, spelled the other way, so it is the
     escape and nothing else that is being tested. */
  var bundle3 = goodBundle();
  bundle3.sword.modes.garrison.gear_assignment.Hilde = [
    { slot: "helmet", name: "Ampersand & Co", icon_url: "/x.png&quot; onerror=&quot;alert(1)" },
  ];
  var d3 = makePage({ bundle: bundle3 });
  await boot(d3);
  d3.slot("Hilde").el.fire("click");
  var amp = d3.modalBody.innerHTML;
  record("ampersand_gear_html", amp);
  check(
    "an entity-spelled quote in a URL cannot re-open the attribute it sits in",
    amp.indexOf('src="/x.png&amp;quot; onerror=&amp;quot;alert(1)"') !== -1,
    amp
  );
  check(
    "and a bare & in a name is escaped rather than starting an entity",
    amp.indexOf("Ampersand &amp; Co") !== -1,
    amp
  );
}

async function suiteLeaveOneOutBranches() {
  var bundle = goodBundle();
  var mode = bundle.sword.modes.garrison;
  mode.heroes[0].explain.leave_one_out = criticalLoo();
  mode.heroes[1].explain.leave_one_out = inconclusiveLoo('Undefined" onmouseover="x');
  var d = makePage({ bundle: bundle });
  await boot(d);

  d.slot("Hilde").el.fire("click");
  check(
    "a hero the lineup cannot do without is called out by name",
    d.modalBody.innerHTML.indexOf("Critical — no feasible lineup without this hero") !== -1,
    d.modalBody.innerHTML
  );
  check(
    "in the critical style, not the ordinary cost line",
    d.modalBody.innerHTML.indexOf('class="why-marginal critical"') !== -1,
    d.modalBody.innerHTML
  );
  check(
    "and without inventing a cost the solver never computed",
    d.modalBody.innerHTML.indexOf("Removing costs") === -1,
    d.modalBody.innerHTML
  );

  d.slot("Howard").el.fire("click");
  check(
    "an inconclusive leave-one-out says so rather than reading as free",
    d.modalBody.innerHTML.indexOf("Leave-one-out inconclusive (status") !== -1,
    d.modalBody.innerHTML
  );
  check(
    "carrying the solver's status, escaped like everything else it returns",
    d.modalBody.innerHTML.indexOf('onmouseover="x') === -1 &&
      d.modalBody.innerHTML.indexOf("Undefined&quot; onmouseover=&quot;x") !== -1,
    d.modalBody.innerHTML
  );

  // A slot with no role: the head line used to render only inside
  // `if (explain.role)`, so the slot went missing with it.
  var bundle2 = goodBundle();
  bundle2.arena.attack.explanations.Helga = {
    slot: "F1",
    fits_because: ["Placed F1"],
    leave_one_out: {},
  };
  var d2 = makePage({ bundle: bundle2 });
  await boot(d2);
  d2.eventButton("arena").fire("click");
  d2.slot("Helga").el.fire("click");
  check(
    "a formation slot is shown even when the solver named no role",
    d2.modalBody.innerHTML.indexOf('class="why-role">F1</p>') !== -1,
    d2.modalBody.innerHTML
  );
}

async function suitePartialFailure() {
  var bundle = goodBundle();
  bundle.errors = { sword: "sword broken" };
  bundle.sword = { label: "Swordland", modes: {}, status: "Error", error: "sword broken" };
  bundle.sword.mode_errors = undefined;

  var d = makePage({ bundle: bundle });
  await boot(d);

  check("a failed section is named, not blanked", d.sectionErrEl.hidden === false, "hidden=" + d.sectionErrEl.hidden);
  check("with the solver's own message", d.sectionErrEl.textContent === "sword broken", d.sectionErrEl.textContent);
  check("its chips are gone", d.chips().length === 0, "chips=" + d.chips().length);
  check(
    "and the board says so rather than showing a stale lineup",
    d.boardEmpty().indexOf("No feasible lineup") !== -1,
    d.boardEmpty()
  );
  check("the status line reports the error", d.statusEl.classList.contains("err"), d.statusEl.className);
  check("naming the section", d.statusEl.textContent.indexOf("sword: sword broken") !== -1, d.statusEl.textContent);

  d.eventButton("bear").fire("click");
  check(
    "the sections that did work are still usable",
    d.boardTitle() === "Bear Trap · solo" && d.rows().length === 1,
    d.boardTitle()
  );
  check("and their banner is cleared", d.sectionErrEl.hidden === true, d.sectionErrEl.textContent);
}

async function suiteArenaSideFailure() {
  var bundle = goodBundle();
  bundle.arena.defense = {
    side: "defense",
    status: "Error",
    formation: {},
    heroes: [],
    score: null,
    reasons: {},
    error: "no feasible defense",
  };
  var d = makePage({ bundle: bundle });
  await boot(d);
  d.eventButton("arena").fire("click");

  check("a broken arena side is still listed", d.chips().length === 2, "chips=" + d.chips().length);
  check("and flagged on its chip", d.chips()[1].classList.contains("is-error"), d.chips()[1].className);
  check(
    "the chip says what state it is in instead of a fake score",
    d.chipText(1).indexOf("Error") !== -1,
    d.chipText(1)
  );
  check("the working side is unaffected", d.boardTitle() === "Arena · attack", d.boardTitle());

  d.chips()[1].fire("click");
  check("selecting it shows the reason", d.boardEmpty() === "no feasible defense", d.boardEmpty());
  check("and no hero slots", d.rows().length === 0, "rows=" + d.rows().length);
  check("the banner names the side", d.sectionErrEl.textContent.indexOf("defense: no feasible defense") !== -1, d.sectionErrEl.textContent);
}

async function suiteWarningsAndSkippedModes() {
  var bundle = goodBundle();
  bundle.warnings = ["gear icons unavailable: boom"];
  bundle.sword.mode_errors = { rally_join: "infeasible", solo: "infeasible" };
  var d = makePage({ bundle: bundle });
  await boot(d);

  check("a warning is surfaced", d.statusEl.textContent.indexOf("gear icons unavailable") !== -1, d.statusEl.textContent);
  check("as a warning, not an error", d.statusEl.classList.contains("warn") && !d.statusEl.classList.contains("err"), d.statusEl.className);
  check("infeasible modes are named rather than silently missing", d.noteEl.hidden === false, "hidden=" + d.noteEl.hidden);
  check(
    "listing each one",
    d.noteEl.textContent.indexOf("rally join") !== -1 && d.noteEl.textContent.indexOf("solo") !== -1,
    d.noteEl.textContent
  );
  d.eventButton("bear").fire("click");
  check("and the note clears on an event that skipped nothing", d.noteEl.hidden === true, d.noteEl.textContent);
}

async function suiteRequestFailure() {
  /* The envelope FastAPI actually sends. This fixture used to hand back the
     bare string, which made "surfaces the server's reason" pass against a
     page that showed whatever bytes arrived — braces and all, the moment
     /api/optimize raised its first HTTPException. */
  var d = makePage({
    status: 404,
    body: JSON.stringify({ detail: "heroes inventory not configured" }),
  });
  await boot(d);

  check("a failed request surfaces the server's reason", d.statusEl.textContent === "heroes inventory not configured", d.statusEl.textContent);
  check(
    "unwrapped from the JSON envelope, not printed as the raw body",
    d.statusEl.textContent.indexOf("detail") === -1 &&
      d.statusEl.textContent.indexOf("{") === -1,
    d.statusEl.textContent
  );
  check("as an error", d.statusEl.classList.contains("err"), d.statusEl.className);
  check("and raises it through the shared toast", d.toasts.length === 1 && d.toasts[0].ok === false, JSON.stringify(d.toasts));
  check("the board is left empty rather than half-drawn", d.rows().length === 0, "rows=" + d.rows().length);

  // FastAPI's *validation* errors put a list of objects in `detail`, which is
  // the half of the envelope rule that is easy to lose.
  d.queueReply({
    status: 422,
    statusText: "Unprocessable Entity",
    body: JSON.stringify({ detail: [{ loc: ["body", "x"], msg: "nope" }] }),
  });
  d.regenBtn.fire("click");
  await settle();
  check(
    "a non-string detail is never printed as [object Object]",
    d.statusEl.textContent.indexOf("object Object") === -1,
    d.statusEl.textContent
  );

  d.queueReply({ bundle: goodBundle() });
  d.regenBtn.fire("click");
  await settle();
  check("Regenerate retries", d.calls.length === 3, "calls=" + d.calls.length);
  check("and a later success replaces the error", d.boardTitle() === "Swordland · garrison", d.boardTitle());
  check("clearing the status", d.statusEl.classList.contains("ok"), d.statusEl.className);
}

async function suiteRegenerateLockout() {
  var d = makePage({ bundle: goodBundle() });
  await boot(d);
  check("the control is usable once loaded", d.regenBtn.disabled === false, "disabled=" + d.regenBtn.disabled);

  d.holdNextFetch();
  d.regenBtn.fire("click");
  await settle();
  check("a recompute in flight disables the control", d.regenBtn.disabled === true, "disabled=" + d.regenBtn.disabled);
  check("and says so on the status line", d.statusEl.textContent === "Recomputing lineups…", d.statusEl.textContent);
  check("without firing a second request", d.calls.length === 2, "calls=" + d.calls.length);

  d.releaseFetch();
  await settle();
  check("finishing re-enables it", d.regenBtn.disabled === false, "disabled=" + d.regenBtn.disabled);

  // The lockout is on the regenerate controls only. The board is still
  // rendered from the bundle already in hand, so tapping a chip mid-refresh
  // has to keep working — and the arriving bundle must not yank the user
  // back to the mode they were on when they pressed the button.
  d.holdNextFetch();
  d.regenBtn.fire("click");
  await settle();
  d.chips()[1].fire("click");
  check(
    "the board still switches mode while a refresh is open",
    d.boardTitle() === "Swordland · rally lead",
    d.boardTitle()
  );
  d.releaseFetch();
  await settle();
  check(
    "and the arriving bundle keeps the mode chosen during the wait",
    d.boardTitle() === "Swordland · rally lead",
    d.boardTitle()
  );

  d.queueReply({ status: 500, body: "boom" });
  d.holdNextFetch();
  d.regenBtn.fire("click");
  await settle();
  d.releaseFetch();
  await settle();
  check("and so does failing", d.regenBtn.disabled === false, "disabled=" + d.regenBtn.disabled);
  check("which is reported, not swallowed", d.statusEl.textContent === "boom", d.statusEl.textContent);
}

async function suiteEmptyRoster() {
  var bundle = goodBundle();
  bundle.sword.modes = {};
  var d = makePage({ bundle: bundle });
  await boot(d);
  check("an event with no feasible mode shows no chips", d.chips().length === 0, "chips=" + d.chips().length);
  check(
    "and says so on the board instead of rendering nothing",
    d.boardEmpty().indexOf("No feasible lineup") !== -1,
    d.boardEmpty()
  );
  check("with no section-error banner, because nothing failed", d.sectionErrEl.hidden === true, d.sectionErrEl.textContent);
}

async function suiteMissingFormationSlot() {
  var bundle = goodBundle();
  delete bundle.arena.attack.formation.B3;
  var d = makePage({ bundle: bundle });
  await boot(d);
  d.eventButton("arena").fire("click");
  var back = d.rows()[1];
  check("a hole in the formation still renders its slot", back.slots.length === 3, "slots=" + back.slots.length);
  check("marked empty", back.slots[2].empty === true, back.slots[2].name);
  check("and not clickable", back.slots[2].tag === "div", back.slots[2].tag);
}

/** Names chosen to exercise every branch of hero_slug: spaces, punctuation,
 *  surrounding whitespace, non-ASCII, and a name that slugifies to nothing.
 *  tests/test_heroes_optimiser_events_js.py compares the URLs recorded here
 *  against ks/heroes/ui/hero_icons.py's own hero_slug — the function that
 *  named the files in /static/heroes. */
var SLUG_NAMES = [
  "Amadeus",
  "Yeon Woo",
  "Sgt. Reginald III",
  "O'Brien",
  "  Hilde  ",
  "###",
  "Ünïcode Name",
];

async function suiteSlugContract() {
  var bundle = goodBundle();
  bundle.sword.modes = { garrison: eventMode(SLUG_NAMES, 100) };
  var d = makePage({ bundle: bundle });
  await boot(d);

  var urls = {};
  d.rows()[0].slots.forEach(function (slot) {
    urls[slot.name] = slot.imgSrc;
  });
  record("slug_urls", JSON.stringify(urls));
  check(
    "every hero in the lineup gets a portrait URL",
    Object.keys(urls).length === SLUG_NAMES.length,
    JSON.stringify(urls)
  );
  check(
    "a name that slugifies to nothing still resolves somewhere",
    urls["###"] === "/static/heroes/hero.webp",
    urls["###"]
  );
  // One initial from each of the first two words — not two from the first,
  // which is what a single-word name gets and is easy to conflate.
  check(
    "a two-word name takes one initial from each word",
    d.slot("Yeon Woo").initials === "YW",
    d.slot("Yeon Woo").initials
  );
  check(
    "punctuation does not shift which letters those are",
    d.slot("Sgt. Reginald III").initials === "SR",
    d.slot("Sgt. Reginald III").initials
  );
  check(
    "and a one-word name takes its first two letters",
    d.slot("Amadeus").initials === "AM",
    d.slot("Amadeus").initials
  );
}

async function suiteApiPortraits() {
  var bundle = goodBundle();
  var mode = bundle.sword.modes.garrison;
  mode.heroes[0].icon_url = "/hero-icons/hilde.svg?v=7";
  mode.heroes[1].icon_url = "javascript:alert(1)";
  var d = makePage({ bundle: bundle });
  await boot(d);

  check(
    "an icon URL the API supplies wins over the static slug path",
    d.slot("Hilde").imgSrc === "/hero-icons/hilde.svg?v=7",
    d.slot("Hilde").imgSrc
  );
  check(
    "but only if it is one the page would serve",
    d.slot("Howard").imgSrc === "/static/heroes/howard.webp",
    d.slot("Howard").imgSrc
  );
}

/* A browser strips every ASCII tab, LF and CR out of a URL *before* it parses
   it, so "/<tab>/evil.example/x.png" is fetched as "//evil.example/x.png" —
   the protocol-relative URL safeUrl exists to refuse, smuggled past a
   charAt(1) that sees a tab where the slash will be. Same class as the
   backslash spelling the function already closed, one layer further out. */
async function suiteWhitespaceSmuggledOrigins() {
  var SMUGGLED = [
    ["a tab", "/\t/evil.example/x.png"],
    ["a newline", "/\n/evil.example/x.png"],
    ["a carriage return", "/\r/evil.example/x.png"],
  ];
  for (var i = 0; i < SMUGGLED.length; i++) {
    var label = SMUGGLED[i][0];
    var url = SMUGGLED[i][1];
    var bundle = goodBundle();
    bundle.sword.modes.garrison.heroes[0].icon_url = url;
    var d = makePage({ bundle: bundle });
    await boot(d);
    check(
      "a protocol-relative URL hidden behind " + label + " is refused",
      d.slot("Hilde").imgSrc === "/static/heroes/hilde.webp",
      d.slot("Hilde").imgSrc
    );
  }

  // Control: the same path without the separator is exactly what safeUrl is
  // meant to allow, so the check above cannot be passing by rejecting
  // everything.
  var ok = goodBundle();
  ok.sword.modes.garrison.heroes[0].icon_url = "/evil.example/x.png";
  var dOk = makePage({ bundle: ok });
  await boot(dOk);
  check(
    "while an ordinary same-origin path with no separator is still served",
    dOk.slot("Hilde").imgSrc === "/evil.example/x.png",
    dOk.slot("Hilde").imgSrc
  );
}

/* Every grouped number on this board is pinned to en-US, so the same 1,200
   points does not render "1.200" for one user and "1 200" for another while
   the Gear XP planner beside it stays on commas. toLocaleString is swapped
   for a sentinel that fires when the locale argument is omitted — the same
   technique tests/js/troops_editor_harness.js uses, which was defending one
   of the four call sites in this UI. */
async function suiteLocale() {
  var original = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (locale) {
    if (locale === undefined) return "LOCALE-DEFAULT";
    return original.call(this, locale);
  };
  try {
    var d = makePage({ bundle: goodBundle() });
    await boot(d);
    // fmtPoints reaches the screen twice over: the chip's score line and the
    // board's points/troops/breakdown meta.
    var shown = d.chipText(0) + " | " + d.boardMeta();
    record("locale_rendered", shown);
    // Holds on any engine: the sentinel only proves that *some* locale was
    // passed, which is the fix. Whether the result is comma-grouped depends
    // on the engine having Intl, which the Python side checks separately.
    check(
      "the board pins its grouping instead of following the viewer's locale",
      shown.indexOf("LOCALE-DEFAULT") === -1,
      shown
    );
  } finally {
    Number.prototype.toLocaleString = original;
  }
}

/* --- run -------------------------------------------------------------------- */

/* Each suite is caught on its own: a scenario that throws must not take the
 * ones after it down with it, or a single regression would report as "the
 * harness stopped running" and hide everything it never reached. */
(async function main() {
  var suites = [
    suiteFirstRender,
    suiteModeAndEventSwitching,
    suiteArenaFormation,
    suiteHeroSheet,
    suiteEscaping,
    suiteLeaveOneOutBranches,
    suitePartialFailure,
    suiteArenaSideFailure,
    suiteWarningsAndSkippedModes,
    suiteRequestFailure,
    suiteRegenerateLockout,
    suiteEmptyRoster,
    suiteMissingFormationSlot,
    suiteSlugContract,
    suiteApiPortraits,
    suiteWhitespaceSmuggledOrigins,
    suiteLocale,
  ];
  var threw = [];
  for (var i = 0; i < suites.length; i++) {
    try {
      await suites[i]();
    } catch (err) {
      threw.push(suites[i].name + ": " + String((err && err.stack) || err));
    }
  }
  check("harness ran to completion", threw.length === 0, threw.join("\n"));
  EMIT("@@RESULTS@@" + JSON.stringify({ checks: checks, data: data }));
})();
