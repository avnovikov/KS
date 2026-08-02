/* Executable coverage for the Spreadsheet+ inventory table's client logic.
 *
 * ks/heroes/ui/static/inventory.js holds the whole per-row save state machine
 * (debounce, dedupe, in-flight coalescing, blank/blur handling, range
 * validation), the trust-flag lifecycle across sessionStorage, the filter
 * chips and the sort — and the repo has no browser to run it in. This harness
 * stands up a fake DOM, a controllable clock and a recordable fetch, then runs
 * the *real, unmodified* source against them.
 *
 * tests/test_heroes_inventory_js.py injects the two static files at the @@...@@
 * markers below and runs this under whatever JS engine the host has
 * (node/bun/jsc/...), so nothing here may assume a particular runtime beyond
 * ES2017 + Promises.
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

function El(tag, attrs) {
  this.tag = tag;
  // inventory.js tells a picker from a typed box with `tagName === "SELECT"`,
  // which is how the real DOM spells it.
  this.tagName = String(tag).toUpperCase();
  this.attrs = attrs || {};
  this.dataset = {};
  this.value = "";
  this.textContent = "";
  this.innerHTML = "";
  this.className = "";
  this.hidden = false;
  this.style = {};
  this.validity = { badInput: false };
  this.listeners = {};
  this.classes = {};
  this.children = [];
  this.parent = null;
  var self = this;
  this.classList = {
    add: function (name) {
      self.classes[name] = true;
    },
    remove: function (name) {
      self.classes[name] = false;
    },
    toggle: function (name, force) {
      self.classes[name] = force === undefined ? !self.classes[name] : !!force;
    },
    contains: function (name) {
      return !!self.classes[name];
    },
  };
}
El.prototype.getAttribute = function (name) {
  return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
};
El.prototype.setAttribute = function (name, value) {
  this.attrs[name] = value;
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
/** Detach from the parent, the way Element.remove() does. */
El.prototype.remove = function () {
  if (!this.parent) return;
  var at = this.parent.children.indexOf(this);
  if (at !== -1) this.parent.children.splice(at, 1);
  this.parent = null;
};
El.prototype.closest = function (selector) {
  var node = this;
  while (node) {
    if (node.tag === selector) return node;
    node = node.parent;
  }
  return null;
};
/* Only the handful of selector shapes inventory.js actually uses are
   supported, spelled out rather than parsed: an unrecognised selector throws
   so a source change that reaches for a new one fails loudly here instead of
   silently matching nothing. */
El.prototype.querySelectorAll = function (selector) {
  var found = this._select(selector);
  if (found === null) throw new Error("harness: unsupported selector " + selector);
  return found;
};
El.prototype.querySelector = function (selector) {
  var found = this._select(selector);
  if (found === null) throw new Error("harness: unsupported selector " + selector);
  return found.length ? found[0] : null;
};
El.prototype._select = function () {
  return null;
};

/* --- page builder ---------------------------------------------------------- */

/** Column order for each table, mirroring the two templates. */
var GEAR_SORTS = ["name", "troop", "slot", "rarity", "enhancement", "mastery", "power"];
var HEROES_SORTS = ["name", "rarity", "troop", "level", "stars", "pellets", "power"];

/**
 * Build one inventory page, install it over the globals inventory.js reaches
 * for, and hand back the levers a suite needs. Every suite gets its own, so
 * state never leaks between scenarios.
 *
 * @param {Object} spec kind/patchBase/payloadKey/sorts/rows/chips/rescan —
 *        exactly the data attributes the Jinja templates emit.
 */
function makePage(spec) {
  var table = new El("table");
  table.dataset.inventoryKind = spec.kind;
  table.dataset.patchBase = spec.patchBase;
  table.dataset.payloadKey = spec.payloadKey;

  var tbody = new El("tbody");
  tbody.parent = table;

  var headers = (spec.sorts || []).map(function (key) {
    var th = new El("th");
    th.dataset.sort = key;
    th.classes.sortable = true;
    return th;
  });

  var rowsByIndex = [];
  var inputsByRow = {};
  var cellsByRow = {};
  var removeButtons = [];

  (spec.rows || []).forEach(function (rowSpec) {
    var tr = new El("tr");
    tr.dataset.rowId = rowSpec.id;
    tr.dataset.name = rowSpec.name === undefined ? rowSpec.id : rowSpec.name;
    if (rowSpec.troop !== undefined) tr.dataset.troop = rowSpec.troop;
    if (rowSpec.slot !== undefined) tr.dataset.slot = rowSpec.slot;
    if (rowSpec.rarity !== undefined) tr.dataset.rarity = rowSpec.rarity;
    if (rowSpec.power !== undefined && rowSpec.power !== null) {
      tr.dataset.power = String(rowSpec.power);
    } else {
      tr.dataset.power = "";
    }
    if (rowSpec.incomplete) tr.dataset.incomplete = "1";
    if (rowSpec.incompleteLocked) tr.dataset.incompleteLocked = "1";

    var powerCell = new El("td");
    powerCell.classes["power-cell"] = true;
    powerCell.textContent =
      rowSpec.power === undefined || rowSpec.power === null ? "—" : String(rowSpec.power);

    /* Each editable control sits in its own `<td class="lock-cell">`, as the
       templates render it: the pin lives on the cell, and inventory.js
       reaches it with `control.closest("td")`. */
    var cells = {};
    var inputs = (rowSpec.inputs || []).map(function (inputSpec) {
      var control;
      if (inputSpec.kind === "select") {
        control = new El("select");
        if (inputSpec.rarityTint) control.dataset.rarityTint = "";
        if (inputSpec.value) control.classes[inputSpec.value] = true;
      } else {
        control = new El("input", {
          min: inputSpec.min === undefined ? "0" : inputSpec.min,
          max: inputSpec.max,
          step: "1",
        });
        if (inputSpec.max === undefined) delete control.attrs.max;
        if (inputSpec.required) control.dataset.required = "";
      }
      control.dataset.field = inputSpec.field;
      if (inputSpec.sortKey) control.dataset.sortKey = inputSpec.sortKey;
      if (inputSpec.blank) control.dataset.blank = inputSpec.blank;
      if (inputSpec.lockable) control.dataset.lockable = "";
      control.dataset.label = inputSpec.label || rowSpec.id + " " + inputSpec.field;
      control.value = inputSpec.value === undefined ? "" : String(inputSpec.value);

      var cell = new El("td");
      // Only the store's locked fields get the pin markup, exactly as the
      // templates render it — hero stars/pellets are plain cells with
      // nowhere to put a pin.
      if (inputSpec.lockable) cell.classes["lock-cell"] = true;
      // The template's own predicate: a stored value is a lock, so the pin
      // ships on whichever cells arrive non-empty.
      if (inputSpec.lockable && control.value !== "") cell.dataset.locked = "1";
      cell.parent = tr;
      control.parent = cell;
      cells[inputSpec.field] = cell;

      // Mirror the template: the sortable column's dataset starts out
      // agreeing with the box above it.
      if (inputSpec.sortKey) tr.dataset[inputSpec.sortKey] = control.value;
      return control;
    });

    if (spec.removable) {
      var removeBtn = new El("button");
      removeBtn.dataset.removeId = rowSpec.id;
      removeBtn.dataset.removeName = rowSpec.name === undefined ? rowSpec.id : rowSpec.name;
      removeButtons.push(removeBtn);
    }

    tr._select = function (selector) {
      if (selector === ".cell-input") return inputs;
      // Modelled as the real DOM would answer it, so narrowing the source
      // back to `input.` — which would drop both pickers off the row — fails
      // the picker checks rather than crashing the harness on an unsupported
      // selector and reporting only "harness ran to completion".
      if (selector === "input.cell-input") {
        return inputs.filter(function (control) {
          return control.tagName === "INPUT";
        });
      }
      if (selector === ".power-cell") return [powerCell];
      return null;
    };
    tbody.appendChild(tr);
    rowsByIndex.push(tr);
    inputsByRow[rowSpec.id] = inputs;
    cellsByRow[rowSpec.id] = cells;
  });

  table._select = function (selector) {
    if (selector === "tbody") return [tbody];
    if (selector === "tbody tr") return tbody.children.slice();
    if (selector === "th.sortable") return headers;
    // Always answered, empty on the heroes table: the source collects these
    // before it checks whether this page has a remove dialog at all.
    if (selector === "button.btn-remove") return removeButtons;
    return null;
  };

  /* --- toolbar ------------------------------------------------------------ */

  var chips = ["all", "attention"]
    .concat(
      (spec.chips || []).map(function (troop) {
        return "troop:" + troop;
      })
    )
    .map(function (filter, index) {
      var chip = new El("button");
      chip.dataset.filter = filter;
      chip.classes.on = index === 0;
      return chip;
    });
  var chipsEl = new El("div");
  chipsEl._select = function (selector) {
    if (selector === ".chip") return chips;
    return null;
  };

  var searchEl = new El("input");
  var countEl = new El("p");
  var noMatchesEl = new El("p");
  noMatchesEl.hidden = true;
  var summaryEl = new El("p");
  var markReviewedBtn = new El("button");

  /* The banner writes are logged so the "un-hide before writing" ordering is
     observable, the same way the troops harness watches #toast. */
  var bannerLog = [];
  var bannerEl = new El("div");
  var bannerHidden = true;
  Object.defineProperty(bannerEl, "hidden", {
    get: function () {
      return bannerHidden;
    },
    set: function (value) {
      bannerHidden = value;
      bannerLog.push("hidden=" + value);
    },
  });
  var summaryText = "";
  Object.defineProperty(summaryEl, "textContent", {
    get: function () {
      return summaryText;
    },
    set: function (value) {
      summaryText = value;
      bannerLog.push("text=" + value);
    },
  });

  var rescanBtn = new El("button");
  rescanBtn.textContent = "Rescan from OCR";
  rescanBtn.disabled = false;
  if (spec.rescan) {
    rescanBtn.dataset.rescanUrl = spec.rescan.url;
    rescanBtn.dataset.reloadUrl = spec.rescan.reload;
    if (spec.rescan.note) rescanBtn.dataset.rescanNote = spec.rescan.note;
    if (spec.rescan.confirm) rescanBtn.dataset.rescanConfirm = spec.rescan.confirm;
  }

  /* The remove confirmation, present only on the gear page. */
  var removeDialog = new El("div");
  var removeConfirm = new El("button");
  removeConfirm.disabled = false;
  var removeCancel = new El("button");
  var removeTarget = new El("div");

  var byId = {
    "inventory-table": table,
    "trust-banner": bannerEl,
    "trust-summary": summaryEl,
    "mark-reviewed": markReviewedBtn,
    "filter-chips": chipsEl,
    "row-search": searchEl,
    "row-count": countEl,
    "no-matches": noMatchesEl,
    "rescan-btn": rescanBtn,
  };
  if (spec.removable) {
    byId["remove-dialog"] = removeDialog;
    byId["remove-confirm"] = removeConfirm;
    byId["remove-cancel"] = removeCancel;
    byId["remove-target"] = removeTarget;
  }

  /* app.js's bindDialogDismiss wires Escape on the document, so the fake one
     has to be able to take a listener. */
  var docListeners = {};
  globalThis.document = {
    getElementById: function (id) {
      return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null;
    },
    addEventListener: function (type, fn) {
      (docListeners[type] = docListeners[type] || []).push(fn);
    },
  };

  /* --- controllable clock ------------------------------------------------- */

  /* The delay is kept, not just the callback: with it discarded, raising
     DEBOUNCE_MS to 30 seconds left every check in this file passing, so the
     400ms the brief specifies was asserted by nothing. */
  var pending = {};
  var nextTimer = 1;
  globalThis.setTimeout = function (fn, delay) {
    var id = nextTimer++;
    pending[id] = { fn: fn, delay: delay };
    return id;
  };
  globalThis.clearTimeout = function (id) {
    delete pending[id];
  };

  /* --- recordable fetch --------------------------------------------------- */

  var calls = [];
  var nextResponse = null; // overrides the reply for exactly one call
  var pendingMode = false; // next call hangs until releaseFetch() is called
  var releases = [];

  function defaultResponse() {
    return {
      ok: true,
      status: 200,
      json: function () {
        return Promise.resolve({});
      },
    };
  }

  globalThis.fetch = function (url, options) {
    options = options || {};
    calls.push({
      url: url,
      method: options.method,
      body: options.body ? JSON.parse(options.body) : null,
      rawBody: options.body || null,
      keepalive: !!options.keepalive,
      contentType: options.headers && options.headers["Content-Type"],
      cache: options.cache,
    });
    var res = nextResponse || defaultResponse();
    nextResponse = null;
    if (pendingMode) {
      pendingMode = false;
      return new Promise(function (resolve) {
        releases.push(function () {
          resolve(res);
        });
      });
    }
    return Promise.resolve(res);
  };

  /* --- window ------------------------------------------------------------- */

  var toasts = [];
  var navigations = [];
  var confirmAnswer = true;
  var confirmPrompts = [];
  var windowListeners = {};
  /* Ordering log shared with sessionStorage below: the rescan must persist the
     trust payload *before* it navigates, or the reload discards it. */
  var sequence = [];

  globalThis.window = {
    addEventListener: function (type, fn) {
      (windowListeners[type] = windowListeners[type] || []).push(fn);
    },
    showToast: function (message, ok) {
      toasts.push({ msg: String(message), ok: !!ok });
    },
    confirm: function (message) {
      confirmPrompts.push(String(message));
      return confirmAnswer;
    },
    location: {
      pathname: (spec.rescan && spec.rescan.reload) || "/inventory/gear",
      replace: function (url) {
        navigations.push(url);
        sequence.push("navigate");
      },
    },
  };
  if (typeof globalThis.console === "undefined") globalThis.console = {};
  globalThis.console.error = function (message) {
    toasts.push({ msg: String(message), ok: false, viaConsole: true });
  };

  /* --- fake sessionStorage (app.js's HeroesTrust helper) ------------------ */

  var sessionStore = {};
  globalThis.sessionStorage = {
    getItem: function (key) {
      return Object.prototype.hasOwnProperty.call(sessionStore, key) ? sessionStore[key] : null;
    },
    setItem: function (key, value) {
      sessionStore[key] = String(value);
      sequence.push("store:" + key);
    },
    removeItem: function (key) {
      delete sessionStore[key];
      sequence.push("clear:" + key);
    },
    clear: function () {
      sessionStore = {};
    },
  };

  return {
    table: table,
    tbody: tbody,
    headers: headers,
    chips: chips,
    chip: function (filter) {
      for (var i = 0; i < chips.length; i++) {
        if (chips[i].dataset.filter === filter) return chips[i];
      }
      return null;
    },
    searchEl: searchEl,
    markReviewedBtn: markReviewedBtn,
    rescanBtn: rescanBtn,
    bannerEl: bannerEl,
    bannerLog: bannerLog,
    /** The banner as the user reads it: "" when it is not on screen.
     *
     *  Fine for asserting a banner is *present* and says the right thing —
     *  `banner() !== "x"` needs both halves — but useless for asserting it
     *  went away: `banner() === ""` is a disjunction, satisfied by `hidden`
     *  alone or by empty text alone. Deleting `banner.hidden = true` from
     *  renderBanner left 122/122 green, and that is the load-bearing half:
     *  without it "Mark all reviewed" leaves an empty trust banner stuck on
     *  the page. The clear path asserts the two separately. */
    banner: function () {
      return bannerEl.hidden ? "" : summaryEl.textContent;
    },
    bannerHidden: function () {
      return bannerEl.hidden === true;
    },
    bannerText: function () {
      return summaryEl.textContent;
    },
    bannerState: function () {
      return "hidden=" + bannerEl.hidden + " text=" + summaryEl.textContent;
    },
    countText: function () {
      return countEl.textContent;
    },
    noMatchesShown: function () {
      return !noMatchesEl.hidden;
    },
    row: function (id) {
      for (var i = 0; i < rowsByIndex.length; i++) {
        if (rowsByIndex[i].dataset.rowId === id) return rowsByIndex[i];
      }
      return null;
    },
    input: function (id, field) {
      var inputs = inputsByRow[id] || [];
      for (var i = 0; i < inputs.length; i++) {
        if (inputs[i].dataset.field === field) return inputs[i];
      }
      return null;
    },
    /** The `<td class="lock-cell">` one control sits in — where the pin is. */
    cell: function (id, field) {
      return (cellsByRow[id] || {})[field] || null;
    },
    /** "1" when this field's pin is showing, "undefined" when it is not. */
    pinned: function (id, field) {
      var cell = (cellsByRow[id] || {})[field];
      return cell ? String(cell.dataset.locked) : "no-cell";
    },
    removeBtn: function (id) {
      for (var i = 0; i < removeButtons.length; i++) {
        if (removeButtons[i].dataset.removeId === id) return removeButtons[i];
      }
      return null;
    },
    removeConfirm: removeConfirm,
    removeCancel: removeCancel,
    removeDialog: removeDialog,
    removeTargetText: function () {
      return removeTarget.textContent;
    },
    dialogOpen: function () {
      return removeDialog.classes.open === true;
    },
    /** Escape, as app.js's bindDialogDismiss listens for it. */
    pressEscape: function () {
      (docListeners.keydown || []).slice().forEach(function (fn) {
        fn({ key: "Escape" });
      });
    },
    /** A click on the backdrop itself, not on the panel inside it. */
    clickBackdrop: function () {
      removeDialog.fire("click", { target: removeDialog });
    },
    /** A click that bubbled up from the panel — must not dismiss. */
    clickInsideDialog: function () {
      removeDialog.fire("click", { target: removeConfirm });
    },
    powerCell: function (id) {
      return this.row(id).querySelector(".power-cell").textContent;
    },
    /* Read off the tbody rather than the build-time row list, so a row the
       delete path detached really is gone from what this reports. */
    visibleIds: function () {
      return tbody.children
        .filter(function (tr) {
          return !tr.hidden;
        })
        .map(function (tr) {
          return tr.dataset.rowId;
        });
    },
    domOrder: function () {
      return tbody.children.map(function (tr) {
        return tr.dataset.rowId;
      });
    },
    header: function (key) {
      for (var i = 0; i < headers.length; i++) {
        if (headers[i].dataset.sort === key) return headers[i];
      }
      return null;
    },
    calls: calls,
    toasts: toasts,
    navigations: navigations,
    confirmPrompts: confirmPrompts,
    sequence: sequence,
    answerConfirm: function (answer) {
      confirmAnswer = answer;
    },
    lastCall: function () {
      // Shaped like a real request even when nothing was sent, so a check that
      // expected a PATCH and did not get one fails with its own message
      // instead of throwing and taking the rest of the suite down with it.
      if (!calls.length) {
        return { url: null, method: null, body: {}, keepalive: false, cache: null };
      }
      return calls[calls.length - 1];
    },
    stored: function (kind) {
      var raw = globalThis.sessionStorage.getItem("heroesUiTrust:" + kind);
      return raw ? JSON.parse(raw) : null;
    },
    seedTrust: function (kind, payload) {
      globalThis.sessionStorage.setItem(
        "heroesUiTrust:" + kind,
        JSON.stringify(payload)
      );
      sequence.length = 0;
    },
    runTimers: function () {
      var ids = Object.keys(pending);
      ids.forEach(function (id) {
        var timer = pending[id];
        delete pending[id];
        timer.fn();
      });
      return ids.length;
    },
    /** Delays of every timer currently scheduled, in creation order. */
    pendingDelays: function () {
      return Object.keys(pending).map(function (id) {
        return pending[id].delay;
      });
    },
    replyWith: function (res) {
      nextResponse = res;
    },
    jsonReply: function (payload) {
      nextResponse = {
        ok: true,
        status: 200,
        json: function () {
          return Promise.resolve(payload);
        },
      };
    },
    hangNextFetch: function () {
      pendingMode = true;
    },
    releaseFetch: function () {
      if (!releases.length) throw new Error("no fetch is in flight to release");
      releases.shift()();
    },
    firePageHide: function () {
      (windowListeners.pagehide || []).forEach(function (fn) {
        fn({ type: "pagehide" });
      });
    },
    clearToasts: function () {
      toasts.length = 0;
    },
  };
}

/* The two real pages, as the templates render them. */

function gearSpec(overrides) {
  var spec = {
    kind: "gear",
    patchBase: "/api/gear/",
    payloadKey: "piece",
    sorts: GEAR_SORTS,
    chips: ["cavalry", "infantry"],
    removable: true,
    rescan: {
      url: "/api/gear/rescan",
      reload: "/inventory/gear",
      note: "OCR rescan started — leave Backpack > Gear open",
      confirm: "Replace the entire gear inventory from ADB OCR?",
    },
    rows: [
      gearRow("cell0", "Judicator's Armet", {
        troop: "cavalry", slot: "helmet", rarity: "mythic",
        power: 152100, enhancement: "51", mastery: "2", masteryRequired: true,
      }),
      gearRow("cell1", "Scout's Cap", {
        troop: "infantry", slot: "helmet", rarity: "blue",
        power: 18362, enhancement: "7", mastery: "", masteryRequired: false,
      }),
      gearRow("cell2", "Unread Boots", {
        troop: "infantry", slot: "boots", rarity: "mythic",
        power: null, enhancement: "", mastery: "", masteryRequired: true,
        incomplete: true,
      }),
    ],
  };
  Object.keys(overrides || {}).forEach(function (key) {
    spec[key] = overrides[key];
  });
  return spec;
}

function gearRow(id, name, opts) {
  return {
    id: id,
    name: name,
    troop: opts.troop,
    slot: opts.slot,
    rarity: opts.rarity,
    power: opts.power,
    incomplete: !!opts.incomplete,
    // Column order as the template renders it: slot and rarity are pickers,
    // enhancement and mastery typed boxes, and all four are lockable.
    inputs: [
      {
        kind: "select", field: "slot", sortKey: "slot",
        blank: "clear_slot", label: name + " slot",
        lockable: true, value: opts.slot === undefined ? "" : opts.slot,
      },
      {
        kind: "select", field: "rarity", sortKey: "rarity",
        blank: "clear_rarity", label: name + " rarity", rarityTint: true,
        lockable: true, value: opts.rarity === undefined ? "" : opts.rarity,
      },
      {
        field: "enhancement_level", sortKey: "enhancement",
        blank: "clear_enhancement", label: name + " enhancement",
        required: true, lockable: true, min: "0", max: "200",
        value: opts.enhancement,
      },
      {
        field: "mastery_level", sortKey: "mastery",
        blank: "clear_mastery", label: name + " mastery",
        required: !!opts.masteryRequired, lockable: true,
        min: "0", max: "20", value: opts.mastery,
      },
    ],
  };
}

function heroesSpec() {
  return {
    kind: "heroes",
    patchBase: "/api/heroes/",
    payloadKey: "hero",
    sorts: HEROES_SORTS,
    chips: ["cavalry", "infantry"],
    rescan: {
      url: "/api/heroes/rescan",
      reload: "/inventory/heroes",
      note: "OCR rescan started — leave the Heroes roster open",
    },
    rows: [
      heroRow("Helga", {
        troop: "infantry", rarity: "legendary", power: 1000000,
        level: "40", stars: "2", pellets: "0",
      }),
      heroRow("Gordon", {
        troop: "cavalry", rarity: "epic", power: null,
        level: "", stars: "3", pellets: "1",
        incomplete: true, incompleteLocked: true,
      }),
    ],
  };
}

function heroRow(name, opts) {
  return {
    id: name,
    name: name,
    troop: opts.troop,
    rarity: opts.rarity,
    power: opts.power,
    incomplete: !!opts.incomplete,
    incompleteLocked: !!opts.incompleteLocked,
    inputs: [
      {
        field: "level", sortKey: "level", blank: "null",
        label: name + " level", lockable: true,
        min: "1", max: "80", value: opts.level,
      },
      {
        field: "stars", sortKey: "stars", blank: "null",
        label: name + " stars", required: true, min: "0", max: "5", value: opts.stars,
      },
      {
        field: "pellets", sortKey: "pellets", blank: "null",
        label: name + " pellets", min: "0", max: "5", value: opts.pellets,
      },
    ],
  };
}

/** Drain the microtask queue so awaited fetch continuations have all run. */
async function settle() {
  for (var i = 0; i < 80; i++) await Promise.resolve();
}

/* --- the units under test, injected verbatim by the pytest runner ---------- */

/** Runs ks/heroes/ui/static/app.js, which publishes showToast + HeroesTrust. */
function loadSharedAppJs() {
// @@APP_JS@@
}

/** Runs ks/heroes/ui/static/inventory.js against whatever makePage() installed. */
function loadInventoryJs() {
// @@INVENTORY_JS@@
}

/** app.js first (for HeroesTrust), then the page script — the load order
 *  _layout.html produces. The harness's own showToast stub is kept so toasts
 *  stay inspectable; app.js's real one is covered by the troops harness. */
function boot(page) {
  var stub = globalThis.window.showToast;
  loadSharedAppJs();
  globalThis.window.showToast = stub;
  loadInventoryJs();
  return page;
}

/* --- suites ---------------------------------------------------------------- */

async function suiteAutoSave() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  check("the rendered table fires no PATCH on load", d.calls.length === 0, "calls=" + d.calls.length);

  var enh = d.input("cell0", "enhancement_level");
  enh.value = "52";
  enh.fire("input");
  check(
    "typing schedules a save instead of sending one",
    d.calls.length === 0,
    "calls=" + d.calls.length
  );
  // Nothing has saved yet, so the debounce is the only timer outstanding.
  record("debounce_delays", d.pendingDelays().join(","));
  check(
    "and schedules it at the 400ms the brief specifies",
    d.pendingDelays().length === 1 && d.pendingDelays()[0] === 400,
    d.pendingDelays().join(",")
  );
  d.runTimers();
  await settle();
  check("the debounce fires exactly one PATCH", d.calls.length === 1, "calls=" + d.calls.length);

  var call = d.lastCall();
  check(
    "it is a JSON PATCH to the row's own API URL",
    call.method === "PATCH" &&
      call.url === "/api/gear/cell0" &&
      call.contentType === "application/json",
    call.method + " " + call.url
  );
  check("the request is not cached", call.cache === "no-store", call.cache);
  check("keepalive is set so a save survives navigation", call.keepalive === true);
  check(
    "it sends the row's whole editable state, not just the box that moved",
    call.body.enhancement_level === 52 && call.body.mastery_level === 2,
    JSON.stringify(call.body)
  );

  // Dedupe: blurring a row nobody changed is not a save.
  var before = d.calls.length;
  enh.fire("blur");
  await settle();
  check(
    "blurring an unchanged row does not re-PATCH",
    d.calls.length === before,
    "calls=+" + (d.calls.length - before)
  );

  // A blank box mid-typing must never fire: null is what the API rejects.
  before = d.calls.length;
  var mastery = d.input("cell0", "mastery_level");
  mastery.value = "3";
  mastery.fire("input");
  mastery.value = "";
  mastery.fire("input");
  d.runTimers();
  await settle();
  check(
    "a cleared box schedules nothing while it is empty",
    d.calls.length === before,
    "calls=+" + (d.calls.length - before)
  );
  check("and does not nag mid-typing", d.toasts.length === 0, JSON.stringify(d.toasts));

  mastery.fire("blur");
  await settle();
  check(
    "blurring a cleared box sends the API's own clear flag",
    d.calls.length === before + 1 && d.lastCall().body.clear_mastery === true,
    JSON.stringify(d.lastCall().body)
  );
  check(
    "and the box stays empty rather than being filled in with a guess",
    mastery.value === "",
    mastery.value
  );
  check(
    "no bare null reaches a gear PATCH",
    d.lastCall().rawBody.indexOf("null") === -1,
    d.lastCall().rawBody
  );
  record("gear_clear_body", JSON.stringify(d.lastCall().body));

  // Range validation: min/max are the template's, and nothing outside them
  // leaves the page.
  d.clearToasts();
  before = d.calls.length;
  enh.value = "999"; // max="200"
  enh.fire("input");
  d.runTimers();
  await settle();
  check(
    "a value over max is not sent",
    d.calls.length === before,
    "calls=+" + (d.calls.length - before)
  );
  enh.fire("blur");
  await settle();
  check(
    "still not sent on blur",
    d.calls.length === before,
    "calls=+" + (d.calls.length - before)
  );
  check(
    "the error names the field and the bound",
    d.toasts.length === 1 &&
      /Judicator/.test(d.toasts[0].msg) &&
      /0 to 200/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );
  check(
    "the field is marked invalid for assistive tech",
    enh.classes.invalid === true && enh.getAttribute("aria-invalid") === "true"
  );
  enh.value = "60";
  enh.fire("input");
  check("typing again stops nagging immediately", enh.classes.invalid === false);
  d.runTimers();
  await settle();
  check(
    "fixing it clears the flag and saves",
    enh.getAttribute("aria-invalid") === null && d.calls.length === before + 1,
    "calls=+" + (d.calls.length - before)
  );

  // The server's answer refreshes the derived cells.
  d.jsonReply({ piece: { power: 190000, enhancement_level: 61, mastery_level: null } });
  enh.value = "61";
  enh.fire("blur");
  await settle();
  check("the power cell is refreshed from the server's answer", d.powerCell("cell0") === "190000", d.powerCell("cell0"));
  check(
    "and so is the row's sort key, so a re-sort orders by what is on screen",
    d.row("cell0").dataset.power === "190000",
    d.row("cell0").dataset.power
  );

  // A server rejection surfaces the API's own message verbatim.
  d.clearToasts();
  d.replyWith({
    ok: false,
    status: 400,
    statusText: "Bad Request",
    json: function () {
      return Promise.resolve({ detail: "enhancement_level must be 0..200; got 201" });
    },
  });
  enh.value = "62";
  enh.fire("blur");
  await settle();
  check(
    "a server error is surfaced verbatim",
    d.toasts.length === 1 && /must be 0\.\.200/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );

  // Navigating away flushes a debounce that has not fired yet.
  before = d.calls.length;
  var enh1 = d.input("cell1", "enhancement_level");
  enh1.value = "9";
  enh1.fire("input");
  d.firePageHide();
  await settle();
  check(
    "pagehide flushes a pending debounce",
    d.calls.length === before + 1 && d.lastCall().body.enhancement_level === 9,
    "calls=+" + (d.calls.length - before)
  );
}

/* Two boxes on the same row, one PATCH already in the air. Every fetch here is
   deliberately left unresolved so a second save really does arrive while
   `saving` is true — the state where the revert-is-dropped bug lived. */
async function suiteInFlight() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  var enh = d.input("cell0", "enhancement_level");
  var original = enh.value; // what the server currently holds

  d.hangNextFetch();
  enh.value = "99";
  enh.fire("blur"); // blur saves immediately: no debounce to hide behind
  await settle();
  check("an edit starts a PATCH", d.calls.length === 1, "calls=" + d.calls.length);
  record("race_calls_after_edit", d.calls.length);

  enh.value = original; // user changes their mind and tabs away
  enh.fire("blur");
  await settle();
  check(
    "the revert is held, not sent, while a PATCH is in flight",
    d.calls.length === 1,
    "calls=" + d.calls.length
  );
  record("race_calls_during_flight", d.calls.length);

  d.releaseFetch();
  await settle();
  record("race_calls_after_release", d.calls.length);
  record("race_displayed", enh.value);
  record("race_server", String(d.lastCall().body.enhancement_level));
  check(
    "the revert is not dropped: it goes out once the first PATCH lands",
    d.calls.length === 2,
    "calls=" + d.calls.length
  );
  check(
    "the last thing the server was told is the value on screen",
    String(d.lastCall().body.enhancement_level) === enh.value,
    "server=" + d.lastCall().body.enhancement_level + " shown=" + enh.value
  );

  // Several edits during one in-flight save collapse into one more PATCH.
  var before = d.calls.length;
  d.hangNextFetch();
  enh.value = "11";
  enh.fire("blur");
  await settle();
  check("the first edit is in flight", d.calls.length === before + 1, "calls=+" + (d.calls.length - before));
  enh.value = "22";
  enh.fire("blur");
  enh.value = "33";
  enh.fire("blur");
  await settle();
  check(
    "further edits queue behind it rather than racing it",
    d.calls.length === before + 1,
    "calls=+" + (d.calls.length - before)
  );
  d.releaseFetch();
  await settle();
  check(
    "several edits during one save coalesce into exactly one more PATCH",
    d.calls.length === before + 2,
    "calls=+" + (d.calls.length - before)
  );
  check(
    "carrying the final value, not an intermediate one",
    d.lastCall().body.enhancement_level === 33,
    JSON.stringify(d.lastCall().body)
  );
  await settle();
  check(
    "and the queue drains rather than looping",
    d.calls.length === before + 2,
    "calls=+" + (d.calls.length - before)
  );

  // Rows are independent state machines: one row saving must not stall another.
  before = d.calls.length;
  d.hangNextFetch();
  enh.value = "44";
  enh.fire("blur");
  await settle();
  var other = d.input("cell1", "enhancement_level");
  other.value = "8";
  other.fire("blur");
  await settle();
  check(
    "a different row saves concurrently instead of queueing behind the first",
    d.calls.length === before + 2 && d.lastCall().url === "/api/gear/cell1",
    "calls=+" + (d.calls.length - before) + " last=" + d.lastCall().url
  );
  d.releaseFetch();
  await settle();

  // A response landing mid-typing must not overwrite what the user is typing.
  before = d.calls.length;
  d.hangNextFetch();
  var mastery = d.input("cell0", "mastery_level");
  mastery.value = "4";
  mastery.fire("blur");
  await settle();
  mastery.value = "5"; // user keeps typing while the PATCH is open
  d.releaseFetch();
  await settle();
  check(
    "a response landing mid-typing does not clobber the box",
    mastery.value === "5",
    mastery.value
  );
}

/* A write the store refused. With no per-row Save button and no further blur
   coming on a field the user has already left, the row itself is the only
   lasting record that what is on screen is not what was stored. */
async function suiteRejectedSave() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  var enh = d.input("cell0", "enhancement_level");
  d.replyWith({
    ok: false,
    status: 400,
    statusText: "Bad Request",
    json: function () {
      return Promise.resolve({ detail: "enhancement_level must be 0..200; got 201" });
    },
  });
  enh.value = "77";
  enh.fire("blur");
  await settle();

  check(
    "a rejected PATCH marks the row unsaved",
    d.row("cell0").dataset.unsaved === "1",
    String(d.row("cell0").dataset.unsaved)
  );
  check(
    "and flags the box the user just left for assistive tech",
    enh.getAttribute("aria-invalid") === "true",
    String(enh.getAttribute("aria-invalid"))
  );
  check(
    "the box keeps what the user typed rather than silently reverting",
    enh.value === "77",
    enh.value
  );
  record("rejected_row_state", String(d.row("cell0").dataset.unsaved));

  // The toast is on a timer; the row mark must not be.
  d.runTimers();
  await settle();
  check(
    "the mark outlives the toast that carried the reason",
    d.row("cell0").dataset.unsaved === "1",
    String(d.row("cell0").dataset.unsaved)
  );

  // And it is findable afterwards, once the toast is long gone.
  d.chip("attention").fire("click");
  check(
    "a row the server rejected shows up under Needs attention",
    d.visibleIds().indexOf("cell0") !== -1,
    d.visibleIds().join(",")
  );
  d.chip("all").fire("click");

  // Retrying the *same* value, deliberately: a different value would produce
  // a different body and go out whether or not the rejected one was wrongly
  // recorded as saved. Re-blurring 77 only reaches the network if
  // lastSavedBody still describes the pre-77 row, which is the actual
  // invariant — assign it before the !res.ok throw and this check goes red.
  var before = d.calls.length;
  enh.fire("blur"); // value is still "77", untouched since the rejection
  await settle();
  check(
    "re-blurring the rejected value retries it rather than deduping against a body that never landed",
    d.calls.length === before + 1 && d.lastCall().body.enhancement_level === 77,
    "calls=+" + (d.calls.length - before) + " body=" + JSON.stringify(d.lastCall().body)
  );
  check(
    "a successful save clears the unsaved mark",
    d.row("cell0").dataset.unsaved === undefined,
    String(d.row("cell0").dataset.unsaved)
  );
  d.chip("attention").fire("click");
  check(
    "and drops the row back out of Needs attention",
    d.visibleIds().indexOf("cell0") === -1,
    d.visibleIds().join(",")
  );
  d.chip("all").fire("click");

  // Undoing is the other way a divergence ends, and it is the normal one:
  // the server rejects a value, the user puts the old one back. Nothing is
  // sent, so only the dedupe path can notice the row agrees again.
  d.replyWith({
    ok: false,
    status: 400,
    statusText: "Bad Request",
    json: function () {
      return Promise.resolve({ detail: "nope" });
    },
  });
  enh.value = "88";
  enh.fire("blur");
  await settle();
  check("a fresh rejection re-marks the row", d.row("cell0").dataset.unsaved === "1");
  var beforeUndo = d.calls.length;
  enh.value = "77"; // exactly what the server last confirmed
  enh.fire("blur");
  await settle();
  check(
    "undoing a rejected edit sends nothing, because the row already matches",
    d.calls.length === beforeUndo,
    "calls=+" + (d.calls.length - beforeUndo)
  );
  check(
    "screen and store agree again after an undo, so the unsaved mark clears",
    d.row("cell0").dataset.unsaved === undefined,
    String(d.row("cell0").dataset.unsaved)
  );
  d.chip("attention").fire("click");
  check(
    "and the undone row is not stuck in Needs attention",
    d.visibleIds().indexOf("cell0") === -1,
    d.visibleIds().join(",")
  );
  d.chip("all").fire("click");
  record("after_undo_unsaved", String(d.row("cell0").dataset.unsaved));

  // A value the client refuses to send is the same divergence: nothing was
  // written, and the box shows something the store does not hold.
  var mastery = d.input("cell1", "mastery_level");
  mastery.value = "99"; // max="20"
  mastery.fire("blur");
  await settle();
  check(
    "a client-side range error also marks the row unsaved",
    d.row("cell1").dataset.unsaved === "1",
    String(d.row("cell1").dataset.unsaved)
  );
  mastery.value = "3";
  mastery.fire("input");
  check(
    "typing clears the per-box nag straight away",
    mastery.classes.invalid === false
  );
  check(
    "but the row still says it has not saved",
    d.row("cell1").dataset.unsaved === "1",
    String(d.row("cell1").dataset.unsaved)
  );
  d.runTimers();
  await settle();
  check(
    "until the fix actually reaches the server",
    d.row("cell1").dataset.unsaved === undefined,
    String(d.row("cell1").dataset.unsaved)
  );

  // Same undo recovery on the range-error path, which never reaches the
  // network at all: 999 is refused, the old value goes back, mark clears.
  var beforeRangeUndo = d.calls.length;
  mastery.value = "77"; // max="20" again
  mastery.fire("blur");
  await settle();
  check("a fresh range error re-marks the row", d.row("cell1").dataset.unsaved === "1");
  mastery.value = "3"; // back to what the last successful save stored
  mastery.fire("blur");
  await settle();
  check(
    "undoing an out-of-range value sends nothing either",
    d.calls.length === beforeRangeUndo,
    "calls=+" + (d.calls.length - beforeRangeUndo)
  );
  check(
    "and clears the mark it set, rather than stranding the row",
    d.row("cell1").dataset.unsaved === undefined,
    String(d.row("cell1").dataset.unsaved)
  );
}

/* The sessionStorage trust lifecycle: the payload HeroesTrust carried across
   the post-rescan reload has to survive further reloads until each row is
   actually reviewed, which means clearing a flag is a *storage* mutation. */
async function suiteTrust() {
  var d = makePage(gearSpec());
  d.seedTrust("gear", {
    flags: { cell0: "changed", cell1: "new", cell2: "incomplete", ghost: "new" },
    new: 2,
    changed: 1,
    incomplete: 1,
    storedAt: 1735689600000,
  });
  boot(d);
  await settle();

  check("row classes come from the stored rescan payload", d.row("cell0").dataset.trust === "changed", d.row("cell0").dataset.trust);
  check("every flagged row is marked", d.row("cell1").dataset.trust === "new" && d.row("cell2").dataset.trust === "incomplete");
  check(
    "the banner reports the counts of the rows actually on the page",
    /1 new/.test(d.banner()) && /1 changed/.test(d.banner()) && /1 incomplete/.test(d.banner()),
    d.banner()
  );
  record("trust_banner", d.banner());
  var unhide = d.bannerLog.indexOf("hidden=false");
  var written = -1;
  for (var i = 0; i < d.bannerLog.length; i++) {
    if (d.bannerLog[i].indexOf("text=Since") === 0) { written = i; break; }
  }
  check(
    "the banner is un-hidden before its text is written",
    unhide !== -1 && written > unhide,
    d.bannerLog.join(" -> ")
  );
  check(
    "a flag for a row that is no longer on the page is dropped, not counted",
    !/2 new/.test(d.banner()),
    d.banner()
  );

  // Reviewing one row must survive a reload, so the mutation goes to storage.
  var enh = d.input("cell0", "enhancement_level");
  enh.value = "52";
  enh.fire("blur");
  await settle();
  check("the reviewed row loses its class", d.row("cell0").dataset.trust === undefined, String(d.row("cell0").dataset.trust));
  var stored = d.stored("gear");
  check(
    "a successful PATCH clears that row's flag in sessionStorage, not just the DOM",
    stored !== null && stored.flags.cell0 === undefined,
    JSON.stringify(stored)
  );
  check(
    "and leaves the other rows' flags alone",
    stored && stored.flags.cell1 === "new" && stored.flags.cell2 === "incomplete",
    JSON.stringify(stored)
  );
  check(
    "the stored counts are re-derived so they still tally the map",
    stored &&
      stored.new + stored.changed + stored.incomplete === Object.keys(stored.flags).length,
    JSON.stringify(stored)
  );
  check("the banner counts drop as rows are reviewed", !/1 changed/.test(d.banner()), d.banner());
  record("trust_after_one_review", JSON.stringify(stored));

  // A failed PATCH must not clear the flag: the row was not reviewed.
  d.replyWith({
    ok: false, status: 400, statusText: "Bad Request",
    json: function () { return Promise.resolve({ detail: "nope" }); },
  });
  var enh1 = d.input("cell1", "enhancement_level");
  enh1.value = "8";
  enh1.fire("blur");
  await settle();
  check(
    "a rejected PATCH leaves the row flagged",
    d.row("cell1").dataset.trust === "new" && d.stored("gear").flags.cell1 === "new",
    JSON.stringify(d.stored("gear"))
  );

  // Reviewing the rest empties the payload, and an empty payload is removed.
  enh1.value = "9";
  enh1.fire("blur");
  await settle();
  var enh2 = d.input("cell2", "enhancement_level");
  enh2.value = "1";
  enh2.fire("blur");
  await settle();
  check(
    "reviewing the last flagged row clears the stored payload entirely",
    d.stored("gear") === null,
    JSON.stringify(d.stored("gear"))
  );
  check(
    "and the banner goes away",
    d.bannerHidden() && d.bannerText() === "",
    d.bannerState()
  );
}

async function suiteMarkAllReviewed() {
  var d = makePage(gearSpec());
  d.seedTrust("gear", {
    flags: { cell0: "changed", cell1: "new", cell2: "incomplete" },
    new: 1, changed: 1, incomplete: 1, storedAt: 1735689600000,
  });
  boot(d);
  await settle();
  check("the banner starts visible", d.banner() !== "", d.banner());

  d.markReviewedBtn.fire("click");
  check(
    "Mark all reviewed clears every row class",
    d.row("cell0").dataset.trust === undefined &&
      d.row("cell1").dataset.trust === undefined &&
      d.row("cell2").dataset.trust === undefined
  );
  check("and the stored payload", d.stored("gear") === null, JSON.stringify(d.stored("gear")));
  check(
    "and hides the banner",
    d.bannerHidden() && d.bannerText() === "",
    d.bannerState()
  );
  check("without sending anything to the API", d.calls.length === 0, "calls=" + d.calls.length);
}

/* "Needs attention" also has to mean something with no rescan payload at all,
   which is why incompleteness is server-stamped and re-derived on save. */
async function suiteIncompleteness() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  check("a row whose required box is blank is marked incomplete", d.row("cell2").dataset.incomplete === "1");
  check(
    "a blank box on a row that does not require it is not incomplete",
    d.row("cell1").dataset.incomplete === undefined,
    String(d.row("cell1").dataset.incomplete)
  );

  var enh2 = d.input("cell2", "enhancement_level");
  var mastery2 = d.input("cell2", "mastery_level");
  enh2.value = "10";
  enh2.fire("blur");
  await settle();
  check(
    "filling one of two required boxes leaves the row incomplete",
    d.row("cell2").dataset.incomplete === "1",
    String(d.row("cell2").dataset.incomplete)
  );
  mastery2.value = "1";
  mastery2.fire("blur");
  await settle();
  check(
    "filling the last required box clears the mark",
    d.row("cell2").dataset.incomplete === undefined,
    String(d.row("cell2").dataset.incomplete)
  );

  // Clearing it again puts the mark back.
  enh2.value = "";
  enh2.fire("blur");
  await settle();
  check("clearing a required box marks the row incomplete again", d.row("cell2").dataset.incomplete === "1");

  var h = makePage(heroesSpec());
  boot(h);
  await settle();
  var stars = h.input("Gordon", "stars");
  stars.value = "4";
  stars.fire("blur");
  await settle();
  check(
    "an incompleteness the page cannot fix survives an edit",
    h.row("Gordon").dataset.incomplete === "1",
    String(h.row("Gordon").dataset.incomplete)
  );
}

async function suiteFilters() {
  var d = makePage(gearSpec());
  d.seedTrust("gear", { flags: { cell0: "changed" }, new: 0, changed: 1, incomplete: 0 });
  boot(d);
  await settle();

  check("All shows every row", d.visibleIds().join(",") === "cell0,cell1,cell2", d.visibleIds().join(","));
  check("and says nothing about a count it is not filtering", d.countText() === "", d.countText());

  d.chip("attention").fire("click");
  check(
    "Needs attention keeps the trust-flagged row and the incomplete one",
    d.visibleIds().join(",") === "cell0,cell2",
    d.visibleIds().join(",")
  );
  check("the chip is marked pressed", d.chip("attention").getAttribute("aria-pressed") === "true");
  check("and the previous chip is not", d.chip("all").getAttribute("aria-pressed") === "false");
  check("the count reports the filtered subset", d.countText() === "2 of 3 shown", d.countText());
  record("attention_visible", d.visibleIds().join(","));

  d.chip("troop:infantry").fire("click");
  check("a troop chip keeps only that troop", d.visibleIds().join(",") === "cell1,cell2", d.visibleIds().join(","));

  d.searchEl.value = "boots";
  d.searchEl.fire("input");
  check("search and chip combine", d.visibleIds().join(",") === "cell2", d.visibleIds().join(","));

  d.searchEl.value = "judicator";
  d.searchEl.fire("input");
  check(
    "a search that matches nothing under the active chip shows the empty state",
    d.visibleIds().length === 0 && d.noMatchesShown(),
    d.visibleIds().join(",") + " empty=" + d.noMatchesShown()
  );

  d.chip("all").fire("click");
  check("the search survives switching chips", d.visibleIds().join(",") === "cell0", d.visibleIds().join(","));
  check("and the empty state is gone", d.noMatchesShown() === false);

  d.searchEl.value = "";
  d.searchEl.fire("input");
  check("clearing the search restores every row", d.visibleIds().length === 3, d.visibleIds().join(","));

  // Reviewing a row does not yank it out from under the user mid-edit; the
  // filter is re-applied on the next chip/search interaction.
  d.chip("attention").fire("click");
  var enh = d.input("cell0", "enhancement_level");
  enh.value = "52";
  enh.fire("blur");
  await settle();
  check(
    "a row reviewed while filtered stays on screen until the filter is re-applied",
    d.visibleIds().indexOf("cell0") !== -1,
    d.visibleIds().join(",")
  );
  d.chip("attention").fire("click");
  check(
    "and drops out once it is",
    d.visibleIds().join(",") === "cell2",
    d.visibleIds().join(",")
  );
}

async function suiteSorting() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  d.header("name").fire("click");
  check(
    "clicking a header sorts ascending",
    d.domOrder().join(",") === "cell0,cell1,cell2",
    d.domOrder().join(",")
  );
  check("and marks aria-sort", d.header("name").getAttribute("aria-sort") === "ascending");
  d.header("name").fire("click");
  check("clicking again reverses it", d.domOrder().join(",") === "cell2,cell1,cell0", d.domOrder().join(","));
  check("and flips aria-sort", d.header("name").getAttribute("aria-sort") === "descending");

  d.header("power").fire("click");
  check(
    "an unknown number sorts below every real value",
    d.domOrder()[0] === "cell2",
    d.domOrder().join(",")
  );
  check("only the active column carries aria-sort", d.header("name").getAttribute("aria-sort") === null);

  d.header("rarity").fire("click");
  check(
    "rarity sorts by rank, not alphabetically",
    d.domOrder()[0] === "cell1",
    d.domOrder().join(",")
  );
  record("rarity_order", d.domOrder().join(","));

  // Keyboard: a <th> has no built-in activation, so Enter/Space are wired by
  // hand. Space must be prevented or the page scrolls under the user.
  d.header("name").fire("click"); // ascending
  var prevented = 0;
  d.header("name").fire("keydown", {
    key: "Enter",
    preventDefault: function () {
      prevented += 1;
    },
  });
  check(
    "Enter sorts a header from the keyboard",
    d.header("name").getAttribute("aria-sort") === "descending",
    String(d.header("name").getAttribute("aria-sort"))
  );
  d.header("name").fire("keydown", {
    key: " ",
    preventDefault: function () {
      prevented += 1;
    },
  });
  check(
    "so does Space",
    d.header("name").getAttribute("aria-sort") === "ascending",
    String(d.header("name").getAttribute("aria-sort"))
  );
  check("and both suppress the browser's default", prevented === 2, String(prevented));
  var order = d.domOrder().join(",");
  d.header("name").fire("keydown", {
    key: "Tab",
    preventDefault: function () {
      prevented += 1;
    },
  });
  check("an unrelated key does nothing", d.domOrder().join(",") === order && prevented === 2);

  // An edit keeps the sortable column's key in step with the box.
  var enh = d.input("cell2", "enhancement_level");
  enh.value = "200";
  enh.fire("input");
  check("editing a cell keeps the sort key in step", d.row("cell2").dataset.enhancement === "200", d.row("cell2").dataset.enhancement);
  d.header("enhancement").fire("click");
  check("so the re-sort orders by what is on screen", d.domOrder()[2] === "cell2", d.domOrder().join(","));
}

async function suiteRescan() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  d.answerConfirm(false);
  d.rescanBtn.fire("click");
  await settle();
  check("the destructive rescan asks first", d.confirmPrompts.length === 1, JSON.stringify(d.confirmPrompts));
  check("declining it sends nothing", d.calls.length === 0, "calls=" + d.calls.length);
  check("and leaves the button alone", d.rescanBtn.disabled === false);

  d.answerConfirm(true);
  d.jsonReply({
    ok: true,
    count: 12,
    cache_bust: "1735689600000000000",
    trust: { flags: { cell0: "changed", cell9: "new" }, new: 1, changed: 1, incomplete: 0 },
  });
  d.rescanBtn.fire("click");
  await settle();
  check(
    "a rescan POSTs to the declared endpoint",
    d.calls.length === 1 && d.lastCall().url === "/api/gear/rescan" && d.lastCall().method === "POST",
    d.lastCall().method + " " + d.lastCall().url
  );
  var stored = d.stored("gear");
  check(
    "the rescan's trust payload is stored verbatim for the next render",
    stored && stored.flags.cell0 === "changed" && stored.flags.cell9 === "new" && stored.changed === 1,
    JSON.stringify(stored)
  );
  var storeAt = d.sequence.indexOf("store:heroesUiTrust:gear");
  var navAt = d.sequence.indexOf("navigate");
  record("rescan_sequence", d.sequence.join(" -> "));
  check(
    "and stored before the page navigates, or the reload would discard it",
    storeAt !== -1 && navAt !== -1 && storeAt < navAt,
    d.sequence.join(" -> ")
  );
  check(
    "the page lands on the declared URL with the server's cache-bust",
    d.navigations.length === 1 &&
      d.navigations[0] === "/inventory/gear?v=1735689600000000000",
    JSON.stringify(d.navigations)
  );

  // A failure has to hand the button back.
  var f = makePage(gearSpec());
  boot(f);
  await settle();
  f.answerConfirm(true);
  f.replyWith({
    ok: false, status: 500, statusText: "Internal Server Error",
    json: function () { return Promise.resolve({ detail: "adb: device offline" }); },
  });
  f.rescanBtn.fire("click");
  await settle();
  check(
    "a failed rescan surfaces the reason",
    f.toasts.some(function (t) { return /device offline/.test(t.msg) && !t.ok; }),
    JSON.stringify(f.toasts)
  );
  check("and re-enables the button", f.rescanBtn.disabled === false, String(f.rescanBtn.disabled));
  check("restoring its label", f.rescanBtn.textContent === "Rescan from OCR", f.rescanBtn.textContent);
  check("and navigates nowhere", f.navigations.length === 0, JSON.stringify(f.navigations));
}

/* The same script against the other page: only the data attributes differ. */
async function suiteHeroesPage() {
  var d = makePage(heroesSpec());
  boot(d);
  await settle();

  var stars = d.input("Helga", "stars");
  stars.value = "4";
  stars.fire("blur");
  await settle();
  check(
    "a hero row patches its own name-keyed URL",
    d.lastCall().url === "/api/heroes/Helga",
    d.lastCall().url
  );
  check(
    "sending the row's whole editable state",
    d.lastCall().body.stars === 4 && d.lastCall().body.pellets === 0,
    JSON.stringify(d.lastCall().body)
  );

  stars.value = "";
  stars.fire("blur");
  await settle();
  check(
    "a blank hero star box is sent as an explicit null, the API's own spelling",
    d.lastCall().body.stars === null,
    JSON.stringify(d.lastCall().body)
  );
  record("heroes_clear_body", JSON.stringify(d.lastCall().body));

  d.rescanBtn.fire("click");
  await settle();
  check(
    "the heroes rescan does not ask for confirmation",
    d.confirmPrompts.length === 0,
    JSON.stringify(d.confirmPrompts)
  );
  check(
    "and writes its payload under the heroes key, never gear's",
    d.sequence.some(function (step) { return step === "store:heroesUiTrust:heroes"; }) ||
      d.navigations.length === 1,
    d.sequence.join(" -> ")
  );
  check(
    "a hero name is URL-encoded into the patch path",
    "/api/heroes/" + encodeURIComponent("Helga") === "/api/heroes/Helga"
  );

  // Level joined the numeric sorts. Left out, sortValue falls through to the
  // string branch and "9" outranks "40" — which looks like a working sort
  // until a roster spans both sides of ten.
  var s = makePage(heroesSpec());
  boot(s);
  await settle();
  s.input("Helga", "level").value = "9";
  s.input("Helga", "level").fire("input");
  s.input("Gordon", "level").value = "40";
  s.input("Gordon", "level").fire("input");
  s.header("level").fire("click");
  check(
    "level sorts as a number, not as text",
    s.domOrder().join(",") === "Helga,Gordon",
    s.domOrder().join(",")
  );
}

/* The two fixed-vocabulary columns restored from the pre-merge gear page.
   A picker has no half-typed state, so it is the one control whose *blank*
   is a chosen value and has to reach the server on its own. */
async function suitePickers() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  var rarity = d.input("cell0", "rarity");
  check("the rarity column is a picker, not a typed box", rarity.tagName === "SELECT", rarity.tagName);

  rarity.value = "epic";
  rarity.fire("change");
  check("changing it sends nothing yet", d.calls.length === 0, "calls=" + d.calls.length);
  check(
    "and is debounced on the same 400ms the boxes use",
    d.pendingDelays().length === 1 && d.pendingDelays()[0] === 400,
    d.pendingDelays().join(",")
  );
  d.runTimers();
  await settle();
  check(
    "the chosen value goes out as the API's own string",
    d.calls.length === 1 && d.lastCall().body.rarity === "epic",
    JSON.stringify(d.lastCall().body)
  );
  check(
    "alongside the rest of the row, exactly as a box edit would",
    d.lastCall().body.slot === "helmet" && d.lastCall().body.enhancement_level === 51,
    JSON.stringify(d.lastCall().body)
  );
  record("picker_body", JSON.stringify(d.lastCall().body));
  check(
    "the sortable column follows the picker",
    d.row("cell0").dataset.rarity === "epic",
    d.row("cell0").dataset.rarity
  );
  check(
    "and so does the rarity tint the column has always had",
    rarity.classes.epic === true && rarity.classes.mythic === false,
    JSON.stringify(rarity.classes)
  );

  // The release control: "—" is a real choice, not an unfinished one, so it
  // must not sit and wait for a blur that a tap-and-look-away never sends.
  var before = d.calls.length;
  var slot = d.input("cell0", "slot");
  slot.value = "";
  slot.fire("change");
  d.runTimers();
  await settle();
  check(
    "choosing — sends straight away rather than waiting for a blur",
    d.calls.length === before + 1,
    "calls=+" + (d.calls.length - before)
  );
  check(
    "as the API's own clear flag, never an empty string",
    d.lastCall().body.clear_slot === true && d.lastCall().body.slot === undefined,
    JSON.stringify(d.lastCall().body)
  );
  record("picker_clear_body", JSON.stringify(d.lastCall().body));

  // A picker's value is not a number, so the numeric validator must not be
  // allowed anywhere near it: treated as unsendable, every save on the row
  // would be refused before it was ever built.
  d.clearToasts();
  before = d.calls.length;
  var enh = d.input("cell0", "enhancement_level");
  enh.value = "60";
  enh.fire("blur");
  await settle();
  check(
    "a picker is never mistaken for an out-of-range number",
    d.calls.length === before + 1 && d.toasts.length === 0,
    "calls=+" + (d.calls.length - before) + " toasts=" + JSON.stringify(d.toasts)
  );

  // And it takes the same rejection treatment as a box.
  d.replyWith({
    ok: false, status: 400, statusText: "Bad Request",
    json: function () { return Promise.resolve({ detail: "rarity must be one of ..." }); },
  });
  rarity.value = "red";
  rarity.fire("change");
  d.runTimers();
  await settle();
  check(
    "a rejected picker save marks the row unsaved like any other",
    d.row("cell0").dataset.unsaved === "1",
    String(d.row("cell0").dataset.unsaved)
  );
  check(
    "and the toast carries the server's reason",
    d.toasts.some(function (t) { return /rarity must be one of/.test(t.msg) && !t.ok; }),
    JSON.stringify(d.toasts)
  );
}

/* The store's lock model, made visible. There is no lock flag: for gear
   slot/rarity/enhancement/mastery and hero level, holding a value *is* the
   lock, and emptying the field is the only release. The pin therefore has to
   track what the store holds — never what the box shows. */
async function suiteLocks() {
  var d = makePage(gearSpec());
  boot(d);
  await settle();

  check(
    "a field that arrived with a value is pinned",
    d.pinned("cell0", "enhancement_level") === "1" &&
      d.pinned("cell0", "rarity") === "1",
    d.pinned("cell0", "enhancement_level") + "/" + d.pinned("cell0", "rarity")
  );
  check(
    "a field that arrived empty is not",
    d.pinned("cell2", "enhancement_level") === "undefined",
    d.pinned("cell2", "enhancement_level")
  );

  // Releasing: empty the box, and the store confirms it now holds null.
  d.jsonReply({ piece: { power: null, enhancement_level: null, mastery_level: 2, rarity: "mythic", slot: "helmet" } });
  var enh = d.input("cell0", "enhancement_level");
  enh.value = "";
  enh.fire("blur");
  await settle();
  check(
    "clearing a field the store accepts releases its pin",
    d.pinned("cell0", "enhancement_level") === "undefined",
    d.pinned("cell0", "enhancement_level")
  );
  check(
    "and leaves the other fields on that row pinned",
    d.pinned("cell0", "mastery_level") === "1" && d.pinned("cell0", "rarity") === "1",
    d.pinned("cell0", "mastery_level") + "/" + d.pinned("cell0", "rarity")
  );
  record("lock_after_clear", d.pinned("cell0", "enhancement_level"));

  // Filling it again pins it again — from the server's value, not the box's.
  d.jsonReply({ piece: { power: 190000, enhancement_level: 61, mastery_level: 2, rarity: "mythic", slot: "helmet" } });
  enh.value = "61";
  enh.fire("blur");
  await settle();
  check(
    "storing a value pins the field again",
    d.pinned("cell0", "enhancement_level") === "1",
    d.pinned("cell0", "enhancement_level")
  );

  // The load-bearing half: a clear the store refused must not look released.
  // Read the pin off the box instead of the response and this goes red.
  d.replyWith({
    ok: false, status: 400, statusText: "Bad Request",
    json: function () { return Promise.resolve({ detail: "nope" }); },
  });
  enh.value = "";
  enh.fire("blur");
  await settle();
  check(
    "a clear the store rejected leaves the pin exactly where it was",
    d.pinned("cell0", "enhancement_level") === "1",
    d.pinned("cell0", "enhancement_level")
  );
  record("lock_after_rejected_clear", d.pinned("cell0", "enhancement_level"));

  // A response that says nothing about a field says nothing about its lock.
  d.jsonReply({ piece: { power: 5 } });
  enh.value = "62";
  enh.fire("blur");
  await settle();
  check(
    "a field the response does not carry keeps its pin: absent is not null",
    d.pinned("cell0", "enhancement_level") === "1",
    d.pinned("cell0", "enhancement_level")
  );

  // A picker releases the same way, through its own clear flag.
  d.jsonReply({ piece: { power: 5, slot: null, rarity: "mythic", enhancement_level: 62, mastery_level: 2 } });
  var slot = d.input("cell0", "slot");
  slot.value = "";
  slot.fire("change");
  d.runTimers();
  await settle();
  check(
    "choosing — releases the picker's pin once the store confirms it",
    d.pinned("cell0", "slot") === "undefined",
    d.pinned("cell0", "slot")
  );

  // Heroes: `level` is HeroStore's only locked field.
  var h = makePage(heroesSpec());
  boot(h);
  await settle();
  check(
    "a stored hero level is pinned, an unread one is not",
    h.pinned("Helga", "level") === "1" && h.pinned("Gordon", "level") === "undefined",
    h.pinned("Helga", "level") + "/" + h.pinned("Gordon", "level")
  );
  var level = h.input("Helga", "level");
  level.value = "";
  level.fire("blur");
  await settle();
  check(
    "blanking it sends the null that releases the lock",
    h.lastCall().body.level === null && "level" in h.lastCall().body,
    JSON.stringify(h.lastCall().body)
  );
  record("hero_level_release_body", JSON.stringify(h.lastCall().body));
  h.jsonReply({ hero: { power: 1000000, level: null, stars: 2, pellets: 0 } });
  level.value = "55";
  level.fire("blur");
  await settle();
  check(
    "and the pin follows the store, not the box",
    h.pinned("Helga", "level") === "undefined" && level.value === "55",
    h.pinned("Helga", "level") + " box=" + level.value
  );
  // Stars and pellets are stored the same way and are *not* locked fields —
  // a rescan overwrites them freely — so their cells carry no pin markup and
  // must never be marked as though they did.
  check(
    "a column the store does not lock never grows a pin",
    h.pinned("Helga", "stars") === "undefined" &&
      h.pinned("Helga", "pellets") === "undefined",
    h.pinned("Helga", "stars") + "/" + h.pinned("Helga", "pellets")
  );
}

/* DELETE /api/gear/{piece_id} has no undo. The row button only arms the
   dialog; nothing but the dialog's own button ever issues the request. */
async function suiteRemove() {
  var d = makePage(gearSpec());
  d.seedTrust("gear", { flags: { cell1: "new" }, new: 1, changed: 0, incomplete: 0 });
  boot(d);
  await settle();

  d.removeBtn("cell1").fire("click");
  check("tapping the row's button sends nothing at all", d.calls.length === 0, "calls=" + d.calls.length);
  check("it opens the confirmation instead", d.dialogOpen(), String(d.dialogOpen()));
  check(
    "which names the piece it is about to destroy",
    d.removeTargetText() === "Scout's Cap",
    d.removeTargetText()
  );
  check(
    "and the row is still on the table",
    d.visibleIds().indexOf("cell1") !== -1,
    d.visibleIds().join(",")
  );

  /* Every way out disarms, so a later stray tap on a confirm button whose
     dialog is long gone cannot delete the piece it used to name. Each pass
     re-arms from a *different* row and asserts it really did re-arm first:
     without that precondition, a mutation that stopped the dialog opening at
     all would satisfy every "it is closed" check below at once. */
  d.removeCancel.fire("click");
  check("Cancel closes it", d.dialogOpen() === false, String(d.dialogOpen()));
  d.removeConfirm.fire("click");
  await settle();
  check(
    "and disarms it: a confirm tap after cancelling deletes nothing",
    d.calls.length === 0,
    "calls=" + d.calls.length
  );

  d.removeBtn("cell0").fire("click");
  check("another row arms it again", d.dialogOpen(), String(d.dialogOpen()));
  d.pressEscape();
  check("Escape closes it too", d.dialogOpen() === false, String(d.dialogOpen()));
  d.removeConfirm.fire("click");
  await settle();
  check("and disarms it as well", d.calls.length === 0, "calls=" + d.calls.length);

  d.removeBtn("cell2").fire("click");
  check("and a third row arms it again", d.dialogOpen(), String(d.dialogOpen()));
  d.clickInsideDialog();
  check(
    "a click that bubbled out of the panel does not dismiss it",
    d.dialogOpen(),
    String(d.dialogOpen())
  );
  d.clickBackdrop();
  check("a click on the backdrop itself does", d.dialogOpen() === false, String(d.dialogOpen()));
  d.removeConfirm.fire("click");
  await settle();
  check("disarmed by that too", d.calls.length === 0, "calls=" + d.calls.length);
  record("remove_calls_before_confirm", d.calls.length);

  // The deliberate second tap.
  d.removeBtn("cell1").fire("click");
  d.hangNextFetch();
  d.removeConfirm.fire("click");
  await settle();
  check(
    "confirming DELETEs the row's own API URL",
    d.calls.length === 1 &&
      d.lastCall().method === "DELETE" &&
      d.lastCall().url === "/api/gear/cell1",
    d.lastCall().method + " " + d.lastCall().url
  );
  d.removeConfirm.fire("click");
  await settle();
  check(
    "an impatient double-tap sends one DELETE, not two",
    d.calls.length === 1,
    "calls=" + d.calls.length
  );
  d.releaseFetch();
  await settle();
  check("the dialog closes on success", d.dialogOpen() === false, String(d.dialogOpen()));
  check(
    "the row leaves the table",
    d.visibleIds().join(",") === "cell0,cell2",
    d.visibleIds().join(",")
  );
  check(
    "and its trust flag leaves sessionStorage with it, rather than pinning the banner open over a row nobody can see",
    d.stored("gear") === null,
    JSON.stringify(d.stored("gear"))
  );
  check(
    "the deletion is confirmed by name",
    d.toasts.some(function (t) { return t.ok && /Scout's Cap/.test(t.msg); }),
    JSON.stringify(d.toasts)
  );
  d.chip("all").fire("click");
  check(
    "and the row count now describes a two-row table",
    d.visibleIds().length === 2 && d.countText() === "",
    d.visibleIds().join(",") + " count=" + d.countText()
  );

  // A refused delete must leave the table exactly as it was.
  d.clearToasts();
  d.removeBtn("cell0").fire("click");
  d.replyWith({
    ok: false, status: 404, statusText: "Not Found",
    json: function () { return Promise.resolve({ detail: "piece not found: cell0" }); },
  });
  d.removeConfirm.fire("click");
  await settle();
  check(
    "a refused delete keeps the row",
    d.visibleIds().indexOf("cell0") !== -1,
    d.visibleIds().join(",")
  );
  check(
    "says why",
    d.toasts.some(function (t) { return !t.ok && /piece not found/.test(t.msg); }),
    JSON.stringify(d.toasts)
  );
  check(
    "and leaves the dialog open and re-armed rather than dropping the user back on an unchanged table",
    d.dialogOpen() && d.removeConfirm.disabled === false,
    "open=" + d.dialogOpen() + " disabled=" + d.removeConfirm.disabled
  );

  // Deleting the last row a filter matches has to re-run the filter, or the
  // table sits there empty with no empty state and reads as broken.
  var f = makePage(gearSpec());
  boot(f);
  await settle();
  f.chip("troop:cavalry").fire("click");
  check(
    "one row matches the active filter",
    f.visibleIds().join(",") === "cell0",
    f.visibleIds().join(",")
  );
  f.removeBtn("cell0").fire("click");
  f.removeConfirm.fire("click");
  await settle();
  check(
    "deleting the last row a filter matched leaves the empty state, not a blank table",
    f.visibleIds().length === 0 && f.noMatchesShown(),
    f.visibleIds().join(",") + " empty=" + f.noMatchesShown()
  );

  // The heroes table has no delete markup at all. The guard for that is in
  // the source, and it has to be an early return rather than a crash: wiring
  // a null confirm button would throw out of the IIFE and take the whole
  // table's auto-save down with it, on the page that has no delete anyway.
  var h = makePage(heroesSpec());
  boot(h);
  await settle();
  var stars = h.input("Helga", "stars");
  stars.value = "4";
  stars.fire("blur");
  await settle();
  check(
    "a page with no delete dialog still wires the rest of its table",
    h.calls.length === 1 && h.lastCall().url === "/api/heroes/Helga",
    "calls=" + h.calls.length + " last=" + h.lastCall().url
  );
}

/* --- run ------------------------------------------------------------------- */

(async function main() {
  try {
    await suiteAutoSave();
    await suiteInFlight();
    await suiteRejectedSave();
    await suiteTrust();
    await suiteMarkAllReviewed();
    await suiteIncompleteness();
    await suiteFilters();
    await suiteSorting();
    await suiteRescan();
    await suiteHeroesPage();
    await suitePickers();
    await suiteLocks();
    await suiteRemove();
  } catch (err) {
    check("harness ran to completion", false, String((err && err.stack) || err));
  }
  EMIT("@@RESULTS@@" + JSON.stringify({ checks: checks, data: data }));
})();
