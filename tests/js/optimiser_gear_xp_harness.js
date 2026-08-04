/* Executable coverage for the Gear XP spend planner's client logic.
 *
 * Everything below the server-rendered form is built in the browser from one
 * POST /api/optimize/gear-xp: the request body, the delta line, the ordered
 * spend rows, the leftovers, and every refusal-to-send and error path. A
 * page-render test can only see the empty form, and a source grep cannot tell
 * whether any of it works.
 *
 * So this does what tests/js/optimiser_events_harness.js does for the lineup
 * board: stands up a fake DOM and a recordable fetch, then runs the *real,
 * unmodified* sources — ks/heroes/ui/static/app.js (loaded first, as
 * _layout.html loads it) and ks/heroes/ui/static/optimiser_gear_xp.js —
 * injected at the markers below by tests/test_heroes_optimiser_gear_xp_js.py.
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
 * `className` and `classList` are two views of one list, as in a real DOM —
 * the script sets `className` on the status line and calls `classList.toggle`
 * on the segments and the fodder boxes, and a harness where those drifted
 * would let a real bug through.
 *
 * `innerHTML` is present but counted, never honoured: the page under test is
 * required to build every node it shows with textContent, so an assignment
 * here is itself the bug (see suiteInjection).
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
  this.value = "";
  this.validity = { badInput: false };
  this._classes = [];
  this._text = "";
  this.htmlWrites = 0;
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
    return "";
  },
  set: function (value) {
    this.htmlWrites += 1;
    this._text = String(value);
    this.children = [];
  },
});

Object.defineProperty(El.prototype, "textContent", {
  get: function () {
    return this._text;
  },
  set: function (value) {
    this._text = String(value);
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
  // A node with children has no text of its own; the getter below walks them.
  this._text = "";
  return child;
};

/** Concatenated text of a node's subtree, the way a real textContent getter
 *  reports it — the script builds `.delta-line` out of five spans. */
El.prototype.deepText = function () {
  if (!this.children.length) return this._text;
  return this.children
    .map(function (child) {
      return child.deepText();
    })
    .join("");
};

/** Total innerHTML assignments anywhere in this subtree. */
El.prototype.deepHtmlWrites = function () {
  return this.children.reduce(function (total, child) {
    return total + child.deepHtmlWrites();
  }, this.htmlWrites);
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

/** Ids, data-attributes and starting values transcribed from
 *  optimiser_gear_xp.html; if the template renames one, the script stops
 *  finding it and the suites fail. The server-side half of that contract is
 *  checked for real in test_heroes_inventory_optimiser_ui.py. */
var EVENT_SEGMENTS = [
  { key: "swordland", label: "Swordland", unit: "Points" },
  { key: "beartrap", label: "Bear Trap", unit: "Points" },
  { key: "arena", label: "Arena", unit: "Score" },
];

var MODE_OPTIONS = {
  swordland: "",
  beartrap: "",
  arena: "attack",
};

var FODDER = [
  { key: "grey", label: "Grey" },
  { key: "green", label: "Green" },
  { key: "blue", label: "Blue" },
  { key: "purple", label: "Purple" },
  { key: "part_100", label: "100-XP part" },
];

/**
 * Build the Gear XP page and install it over the globals the script reaches
 * for. Each suite gets its own, so no state leaks between scenarios.
 *
 * @param {Object} spec {result} the JSON the POST replies with, or
 *        {status, body} to make it fail, or {reject} to make fetch throw.
 *        {gearEnabled: false} renders the gear-less form the server sends
 *        when the UI was started without --gear.
 */
function makePage(spec) {
  spec = spec || {};
  var gearEnabled = spec.gearEnabled !== false;

  function el(tag, id, className) {
    var node = new El(tag);
    if (id) node.attrs.id = id;
    if (className) node.className = className;
    return node;
  }

  var form = el("form", "gear-xp-form", "spend-form");
  form.dataset.apiUrl = "/api/optimize/gear-xp";

  var runBtn = el("button", "run-btn", "btn-run");
  runBtn.disabled = !gearEnabled;
  var statusEl = el("p", "spend-status", "status-line");
  var resultEl = el("section", "spend-result", "panel spend-result");
  resultEl.hidden = true;
  var deltaEl = el("p", "delta-line", "delta-line");
  var targetEl = el("p", "target-line", "target-line");
  var listEl = el("ol", "spend-list", "spend-list");
  var emptyEl = el("p", "spend-empty", "empty");
  emptyEl.hidden = true;
  var leftoverEl = el("p", "leftover-line", "leftover-line");
  var valueSummaryEl = el("p", "value-summary-line", "value-summary-line");
  valueSummaryEl.hidden = true;

  var eventButtons = EVENT_SEGMENTS.map(function (seg, i) {
    var btn = new El("button");
    btn.className = i === 0 ? "seg on" : "seg";
    btn.dataset.event = seg.key;
    btn.dataset.unit = seg.unit;
    btn.textContent = seg.label;
    btn.disabled = !gearEnabled;
    btn.setAttribute("aria-pressed", i === 0 ? "true" : "false");
    return btn;
  });

  var modeFields = EVENT_SEGMENTS.map(function (seg, i) {
    var field = new El("div");
    field.className = "stack-field";
    field.dataset.modeFor = seg.key;
    field.hidden = i !== 0;
    return field;
  });

  var modeSelects = EVENT_SEGMENTS.map(function (seg) {
    var select = new El("select");
    select.className = "stack-input";
    select.dataset.modeSelect = seg.key;
    select.value = MODE_OPTIONS[seg.key];
    select.disabled = !gearEnabled;
    return select;
  });

  var fodderInputs = FODDER.map(function (kind) {
    var input = new El("input");
    input.className = "stack-input";
    input.attrs.id = "fodder-" + kind.key;
    input.dataset.fodder = kind.key;
    input.dataset.label = kind.label;
    input.value = "0";
    input.disabled = !gearEnabled;
    return input;
  });

  var byId = {
    "gear-xp-form": form,
    "run-btn": runBtn,
    "spend-status": statusEl,
    "spend-result": resultEl,
    "delta-line": deltaEl,
    "target-line": targetEl,
    "spend-list": listEl,
    "spend-empty": emptyEl,
    "leftover-line": leftoverEl,
    "value-summary-line": valueSummaryEl,
  };

  globalThis.document = {
    getElementById: function (id) {
      return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null;
    },
    querySelectorAll: function (selector) {
      if (selector === "[data-event]") return eventButtons.slice();
      if (selector === "[data-mode-for]") return modeFields.slice();
      if (selector === "[data-mode-select]") return modeSelects.slice();
      if (selector === "[data-fodder]") return fodderInputs.slice();
      throw new Error("harness: unsupported selector " + selector);
    },
    createElement: function (tag) {
      return new El(tag);
    },
    addEventListener: function () {},
  };

  /* --- recordable fetch --------------------------------------------------- */

  var calls = [];
  var replies = [];
  var pendingResolve = null;

  function replyFor() {
    var reply = replies.length ? replies.shift() : spec;
    var ok = reply.status === undefined ? true : reply.status >= 200 && reply.status < 300;
    var body =
      reply.body !== undefined
        ? reply.body
        : JSON.stringify(reply.result === undefined ? {} : reply.result);
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
    var opts = options || {};
    calls.push({ url: url, method: opts.method, headers: opts.headers, body: opts.body });
    var next = replies.length ? replies[0] : spec;
    if (next && next.reject) {
      if (replies.length) replies.shift();
      return Promise.reject(new Error(next.reject));
    }
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

  function bySelectKey(list, prop, key) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].dataset[prop] === key) return list[i];
    }
    return null;
  }

  return {
    form: form,
    runBtn: runBtn,
    statusEl: statusEl,
    resultEl: resultEl,
    deltaEl: deltaEl,
    targetEl: targetEl,
    listEl: listEl,
    emptyEl: emptyEl,
    leftoverEl: leftoverEl,
    valueSummaryEl: valueSummaryEl,
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
      return bySelectKey(eventButtons, "event", key);
    },
    eventButtons: eventButtons,
    modeField: function (key) {
      return bySelectKey(modeFields, "modeFor", key);
    },
    modeSelect: function (key) {
      return bySelectKey(modeSelects, "modeSelect", key);
    },
    fodder: function (key) {
      return bySelectKey(fodderInputs, "fodder", key);
    },
    fodderInputs: fodderInputs,

    clickEvent: function (key) {
      var btn = this.eventButton(key);
      if (btn) btn.fire("click", { type: "click" });
    },
    /** Type into a box the way a user does: set the value, fire `input`. */
    type: function (key, value) {
      var input = this.fodder(key);
      input.value = String(value);
      input.fire("input", { type: "input" });
    },
    blur: function (key) {
      this.fodder(key).fire("blur", { type: "blur" });
    },
    submit: function () {
      var prevented = 0;
      form.fire("submit", {
        type: "submit",
        preventDefault: function () {
          prevented += 1;
        },
      });
      return prevented;
    },

    lastBody: function () {
      if (!calls.length) return null;
      return JSON.parse(calls[calls.length - 1].body);
    },
    status: function () {
      return { text: statusEl.textContent, cls: statusEl.className };
    },
    /** [{cls, text}] for the spans the delta line was built out of. */
    deltaParts: function () {
      return deltaEl.children.map(function (span) {
        return { cls: span.className, text: span.textContent };
      });
    },
    deltaText: function () {
      return deltaEl.deepText();
    },
    /** [{rank, name, meta}] in render order. */
    steps: function () {
      return listEl.children.map(function (row) {
        var rank = row.children[0];
        var main = row.children[1];
        var kids = main ? main.children : [];
        return {
          cls: row.className,
          rank: rank ? rank.textContent : "",
          name: kids[0] ? kids[0].textContent : "",
          meta: kids[1] ? kids[1].textContent : "",
        };
      });
    },
    /** innerHTML assignments anywhere the script could have made one. */
    htmlWrites: function () {
      return (
        resultEl.deepHtmlWrites() +
        deltaEl.deepHtmlWrites() +
        targetEl.deepHtmlWrites() +
        listEl.deepHtmlWrites() +
        emptyEl.deepHtmlWrites() +
        leftoverEl.deepHtmlWrites() +
        valueSummaryEl.deepHtmlWrites() +
        statusEl.deepHtmlWrites()
      );
    },
    valueSummary: function () {
      return { hidden: valueSummaryEl.hidden, text: valueSummaryEl.textContent };
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

/** Runs ks/heroes/ui/static/optimiser_gear_xp.js against whatever makePage()
 *  installed. */
function loadGearXpScript() {
// @@OPTIMISER_GEAR_XP_JS@@
}

/** app.js first, then the page script — the load order _layout.html produces.
 *  The harness's own showToast stub is restored afterwards so toasts stay
 *  inspectable; app.js's real one is covered by the troops harness. */
async function boot(page) {
  var stub = globalThis.window.showToast;
  loadSharedAppJs();
  globalThis.window.showToast = stub;
  loadGearXpScript();
  await settle();
  return page;
}

/* --- fixtures --------------------------------------------------------------- */

function goodResult() {
  return {
    event: "swordland",
    baseline_utility: 26152.44,
    best_utility: 26410.86,
    delta_utility: 258.42,
    steps: [
      {
        piece_id: "p1",
        name: "Judicator's Armet",
        from_level: 51,
        to_level: 52,
        xp_spent: 1200,
        fodder_spent: { grey: 8, green: 1 },
      },
      {
        piece_id: "p2",
        name: "Warden Greaves",
        from_level: 10,
        to_level: 11,
        xp_spent: 300,
        fodder_spent: { purple: 2 },
      },
    ],
    leftover: { grey: 0, green: 3, blue: 1, purple: 0, part_100: 0 },
    baseline_summary: { mode: "garrison", heroes: ["Hilde", "Howard", "Saul"] },
    best_summary: {
      mode: "rally_lead",
      heroes: ["Hilde", "Howard", "Saul"],
      expected_personal_points: 26410.86,
    },
    value_summary:
      "The first 1,290 XP (80% of 1,620 XP spent) already captured 95% of the " +
      "258.42-point gain — the rest spends spare fodder for diminishing returns.",
  };
}

/** Fill the bag so `collect()` has something to send. */
function fillBag(d) {
  d.type("grey", "12");
  d.type("green", "4");
}

/* --- suites ----------------------------------------------------------------- */

async function suiteFirstRender() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  check(
    "the planner solves nothing until asked — no request on load",
    d.calls.length === 0,
    JSON.stringify(d.calls)
  );
  check("the result panel starts hidden", d.resultEl.hidden === true, d.resultEl.hidden);
  check(
    "Swordland is the event the page opens on",
    d.eventButton("swordland").classList.contains("on") &&
      d.eventButton("swordland").getAttribute("aria-pressed") === "true",
    d.eventButton("swordland").className
  );
  check(
    "only that event's mode picker is on screen",
    d.modeField("swordland").hidden === false &&
      d.modeField("beartrap").hidden === true &&
      d.modeField("arena").hidden === true,
    [d.modeField("swordland").hidden, d.modeField("beartrap").hidden, d.modeField("arena").hidden].join(",")
  );
  check(
    "the run button is live when a gear inventory is configured",
    d.runBtn.disabled === false,
    d.runBtn.disabled
  );
}

async function suiteHappyPath() {
  var d = makePage({ result: goodResult() });
  await boot(d);
  fillBag(d);
  var prevented = d.submit();
  await settle();

  check("submitting the form does not navigate", prevented === 1, "preventDefault×" + prevented);
  check("exactly one request goes out", d.calls.length === 1, JSON.stringify(d.calls.length));
  check(
    "to the endpoint the form declares",
    d.calls[0].url === "/api/optimize/gear-xp",
    d.calls[0].url
  );
  check("as a POST", d.calls[0].method === "POST", String(d.calls[0].method));
  check(
    "of JSON",
    d.calls[0].headers && d.calls[0].headers["Content-Type"] === "application/json",
    JSON.stringify(d.calls[0].headers)
  );

  var body = d.lastBody();
  record("post_body", body);
  check("carrying the chosen event", body.event === "swordland", JSON.stringify(body.event));
  check(
    "and every fodder count the form offers",
    body.grey === 12 && body.green === 4 && body.blue === 0 && body.purple === 0 && body.part_100 === 0,
    JSON.stringify(body)
  );
  check(
    "as numbers, never strings",
    ["grey", "green", "blue", "purple", "part_100"].every(function (k) {
      return typeof body[k] === "number";
    }),
    JSON.stringify(body)
  );
  check(
    'and no "mode" at all while Best mode is selected',
    !Object.prototype.hasOwnProperty.call(body, "mode"),
    JSON.stringify(body)
  );

  check("the result panel opens", d.resultEl.hidden === false, d.resultEl.hidden);
  var parts = d.deltaParts();
  record("delta_parts", parts);
  check(
    "the delta line names the unit this event's utility is in",
    parts[0] && parts[0].cls === "delta-label" && parts[0].text === "Points",
    JSON.stringify(parts[0])
  );
  check(
    "and reads baseline → best",
    parts[1].text === "26,152.4" && parts[2].text === "→" && parts[3].text === "26,410.9",
    d.deltaText()
  );
  check(
    "with the gain called out and signed",
    parts[4] && parts[4].text === "+258.4",
    JSON.stringify(parts[4])
  );
  check(
    "and styled as a gain",
    parts[4] && parts[4].cls.indexOf("delta-up") !== -1,
    parts[4] ? parts[4].cls : ""
  );

  check(
    "the target line names the event, the mode that won, and its lineup",
    d.targetEl.textContent === "Swordland · rally lead · Hilde, Howard, Saul",
    d.targetEl.textContent
  );

  var steps = d.steps();
  record("steps", steps);
  check("one row per proposed spend", steps.length === 2, "rows=" + steps.length);
  check("numbered in spend order", steps[0].rank === "1" && steps[1].rank === "2", JSON.stringify(steps.map(function (s) { return s.rank; })));
  check(
    "in the order the search returned them",
    steps[0].name === "Judicator's Armet" && steps[1].name === "Warden Greaves",
    JSON.stringify(steps.map(function (s) { return s.name; }))
  );
  check(
    "each row carrying the levels it buys, the XP it costs and the fodder it eats",
    steps[0].meta === "+51 → +52 · 1,200 XP · 8 Grey, 1 Green",
    steps[0].meta
  );
  check(
    "fodder named the way the form names it",
    steps[1].meta.indexOf("2 Purple") !== -1,
    steps[1].meta
  );
  check(
    "leftovers list only what is actually left",
    d.leftoverEl.textContent === "Left in the bag: 3 Green, 1 Blue",
    d.leftoverEl.textContent
  );
  check(
    "the coarse value-vs-burn summary the server composed is shown verbatim",
    d.valueSummary().hidden === false && d.valueSummary().text === goodResult().value_summary,
    JSON.stringify(d.valueSummary())
  );
  check(
    "the empty-result line stays out of the way",
    d.emptyEl.hidden === true,
    d.emptyEl.hidden
  );
  check(
    "the status line reports how many spends came back",
    d.statusEl.textContent === "2 spends proposed." && d.statusEl.classList.contains("ok"),
    d.statusEl.textContent + " / " + d.statusEl.className
  );
  check("and success raises no toast", d.toasts.length === 0, JSON.stringify(d.toasts));
  check("the run button is handed back", d.runBtn.disabled === false, d.runBtn.disabled);
}

async function suiteEventAndModeSwitching() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  d.clickEvent("beartrap");
  check(
    "picking an event moves the pressed state",
    d.eventButton("beartrap").getAttribute("aria-pressed") === "true" &&
      d.eventButton("swordland").getAttribute("aria-pressed") === "false",
    d.eventButtons
      .map(function (b) {
        return b.dataset.event + "=" + b.getAttribute("aria-pressed");
      })
      .join(",")
  );
  check(
    "and the selected class with it",
    d.eventButton("beartrap").classList.contains("on") &&
      !d.eventButton("swordland").classList.contains("on"),
    d.eventButtons
      .map(function (b) {
        return b.className;
      })
      .join(" | ")
  );
  check(
    "and swaps in that event's own modes",
    d.modeField("beartrap").hidden === false &&
      d.modeField("swordland").hidden === true &&
      d.modeField("arena").hidden === true,
    [d.modeField("swordland").hidden, d.modeField("beartrap").hidden, d.modeField("arena").hidden].join(",")
  );

  d.modeSelect("beartrap").value = "joiner";
  fillBag(d);
  d.submit();
  await settle();
  var body = d.lastBody();
  check("the new event reaches the request", body.event === "beartrap", JSON.stringify(body));
  check("with the mode chosen for it", body.mode === "joiner", JSON.stringify(body));
  check(
    "and the mode picker for the event you left is not consulted",
    body.mode !== "",
    JSON.stringify(body)
  );

  d.clickEvent("arena");
  check(
    "arena swaps the mode picker for a side picker",
    d.modeField("arena").hidden === false && d.modeField("beartrap").hidden === true,
    [d.modeField("beartrap").hidden, d.modeField("arena").hidden].join(",")
  );
  d.submit();
  await settle();
  var arenaBody = d.lastBody();
  check(
    "and sends the side as the mode, on the arena event",
    arenaBody.event === "arena" && arenaBody.mode === "attack",
    JSON.stringify(arenaBody)
  );
  check(
    "the arena delta is labelled a score, not points",
    d.deltaParts()[0].text === "Score",
    JSON.stringify(d.deltaParts()[0])
  );

  d.modeSelect("arena").value = "defense";
  d.submit();
  await settle();
  check(
    "switching side switches what is asked for",
    d.lastBody().mode === "defense",
    JSON.stringify(d.lastBody())
  );
}

async function suiteBlankCounts() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  d.type("grey", "");
  check(
    "clearing a box leaves it visibly empty while you are still typing",
    d.fodder("grey").value === "",
    d.fodder("grey").value
  );
  check(
    "and half-way through an edit is not an error worth shouting about",
    d.fodder("grey").getAttribute("aria-invalid") === null &&
      !d.fodder("grey").classList.contains("invalid"),
    d.fodder("grey").className + " " + d.fodder("grey").getAttribute("aria-invalid")
  );
  d.blur("grey");
  check(
    "but leaving it writes the zero it means back into the box",
    d.fodder("grey").value === "0",
    d.fodder("grey").value
  );

  d.type("green", "6");
  d.type("blue", "");
  d.submit();
  await settle();
  check(
    "a box still blank at submit time is filled in before anything is sent",
    d.fodder("blue").value === "0",
    d.fodder("blue").value
  );
  var body = d.lastBody();
  check(
    "so a cleared count is sent as 0 and never as null",
    body.blue === 0 &&
      Object.keys(body).every(function (k) {
        return body[k] !== null;
      }),
    JSON.stringify(body)
  );
  check(
    "and what was sent is exactly what the boxes show",
    d.fodderInputs.every(function (input) {
      return String(body[input.dataset.fodder]) === input.value;
    }),
    JSON.stringify(
      d.fodderInputs.map(function (i) {
        return i.dataset.fodder + "=" + i.value;
      })
    )
  );
}

async function suiteRefusesUnsendableCounts() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  // Another box is filled throughout, so every "nothing was sent" below is
  // the *invalid box* stopping the request and never the empty-bag guard.
  d.type("green", "5");
  d.type("grey", "-3");
  check(
    "a negative count is flagged as you type",
    d.fodder("grey").getAttribute("aria-invalid") === "true" &&
      d.fodder("grey").classList.contains("invalid"),
    d.fodder("grey").className + " " + d.fodder("grey").getAttribute("aria-invalid")
  );
  d.submit();
  await settle();
  check("and nothing is sent", d.calls.length === 0, JSON.stringify(d.calls));
  check(
    "the status line says which box to fix",
    d.statusEl.classList.contains("err") && d.statusEl.textContent.indexOf("Grey") !== -1,
    d.statusEl.textContent + " / " + d.statusEl.className
  );
  record("invalid_status", d.statusEl.textContent);

  d.type("grey", "1.5");
  d.submit();
  await settle();
  check("a fractional count is refused too", d.calls.length === 0, JSON.stringify(d.calls));

  d.type("grey", "1e3");
  d.submit();
  await settle();
  check("and so is an exponent", d.calls.length === 0, JSON.stringify(d.calls));

  // What the browser itself could not parse: `value` reads empty, but this is
  // junk in the box rather than a box the user cleared.
  d.type("grey", "");
  d.fodder("grey").validity.badInput = true;
  d.blur("grey");
  check(
    "text the browser refused to parse is not silently read as zero",
    d.fodder("grey").value === "",
    d.fodder("grey").value
  );
  d.submit();
  await settle();
  check("and blocks the request", d.calls.length === 0, JSON.stringify(d.calls));

  d.fodder("grey").validity.badInput = false;
  d.type("grey", "7");
  check(
    "fixing the box clears the flag",
    d.fodder("grey").getAttribute("aria-invalid") === null &&
      !d.fodder("grey").classList.contains("invalid"),
    d.fodder("grey").className + " " + d.fodder("grey").getAttribute("aria-invalid")
  );
  d.submit();
  await settle();
  check("and lets the search run", d.calls.length === 1, JSON.stringify(d.calls.length));
  check("with the corrected count", d.lastBody().grey === 7, JSON.stringify(d.lastBody()));
}

async function suiteEmptyBag() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  d.submit();
  await settle();
  check(
    "an all-zero bag never reaches the solver",
    d.calls.length === 0,
    JSON.stringify(d.calls)
  );
  check(
    "and is a nudge rather than an error",
    d.statusEl.classList.contains("warn") && !d.statusEl.classList.contains("err"),
    d.statusEl.className
  );
  record("empty_bag_status", d.statusEl.textContent);
  check(
    "which says what to do",
    d.statusEl.textContent.indexOf("at least one") !== -1,
    d.statusEl.textContent
  );

  d.type("part_100", "1");
  d.submit();
  await settle();
  check(
    "one piece of any kind is enough to run",
    d.calls.length === 1,
    JSON.stringify(d.calls.length)
  );
}

async function suiteNoSpendsFound() {
  var flat = goodResult();
  flat.steps = [];
  flat.best_utility = flat.baseline_utility;
  flat.delta_utility = 0;
  flat.leftover = { grey: 12, green: 4, blue: 0, purple: 0, part_100: 0 };
  var d = makePage({ result: flat });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();

  check("the result panel still opens", d.resultEl.hidden === false, d.resultEl.hidden);
  check("with no spend rows", d.steps().length === 0, "rows=" + d.steps().length);
  check(
    "and an explanation in their place",
    d.emptyEl.hidden === false && d.emptyEl.textContent.indexOf("No spend raises") === 0,
    d.emptyEl.hidden + " / " + d.emptyEl.textContent
  );
  check(
    "a zero delta is not dressed up as a gain",
    d.deltaParts()[4].text === "0.0" && d.deltaParts()[4].cls.indexOf("delta-flat") !== -1,
    JSON.stringify(d.deltaParts()[4])
  );
  check(
    "and the whole bag is still in the bag",
    d.leftoverEl.textContent === "Left in the bag: 12 Grey, 4 Green",
    d.leftoverEl.textContent
  );
  check(
    "the count reads zero, not blank",
    d.statusEl.textContent === "0 spends proposed.",
    d.statusEl.textContent
  );
}

async function suiteNoValueSummary() {
  var flat = goodResult();
  flat.value_summary = null;
  var d = makePage({ result: flat });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();

  check(
    "no value summary from the server means the line stays out of the way",
    d.valueSummary().hidden === true && d.valueSummary().text === "",
    JSON.stringify(d.valueSummary())
  );
}

async function suiteSingularAndFallbacks() {
  var one = goodResult();
  one.steps = [
    {
      piece_id: "p9",
      name: null,
      from_level: 3,
      to_level: 4,
      xp_spent: 60,
      fodder_spent: { blue: 1 },
    },
  ];
  delete one.delta_utility;
  delete one.best_summary;
  one.leftover = { grey: 0, green: 0, blue: 0, purple: 0, part_100: 0 };
  var d = makePage({ result: one });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();

  check(
    "one spend is announced in the singular",
    d.statusEl.textContent === "1 spend proposed.",
    d.statusEl.textContent
  );
  check(
    "a piece with no name falls back to its id rather than showing nothing",
    d.steps()[0].name === "p9",
    d.steps()[0].name
  );
  check(
    "a reply without delta_utility still shows the gain",
    d.deltaParts()[4].text === "+258.4",
    JSON.stringify(d.deltaParts()[4])
  );
  check(
    "a reply without a lineup summary still names the event",
    d.targetEl.textContent === "Swordland",
    d.targetEl.textContent
  );
  check(
    "an empty bag afterwards says so in words",
    d.leftoverEl.textContent === "Left in the bag: nothing",
    d.leftoverEl.textContent
  );
}

async function suiteArenaSummary() {
  var arena = goodResult();
  arena.event = "arena";
  arena.baseline_utility = 588.1;
  arena.best_utility = 636.4;
  arena.delta_utility = 48.3;
  arena.best_summary = {
    status: "Optimal",
    side: "defense",
    formation: { F1: "Howard", F2: "Helga", B1: "Saul", B2: "Jabel", B3: "Diana" },
    heroes: ["Howard", "Helga", "Saul", "Jabel", "Diana"],
    score: 636.4,
  };
  var d = makePage({ result: arena });
  await boot(d);
  d.clickEvent("arena");
  fillBag(d);
  d.submit();
  await settle();

  check(
    "an arena reply names the side rather than a mode",
    d.targetEl.textContent === "Arena · defense · Howard, Helga, Saul, Jabel, Diana",
    d.targetEl.textContent
  );
  check(
    "and three-figure scores are still readable",
    d.deltaParts()[1].text === "588.1" && d.deltaParts()[3].text === "636.4",
    d.deltaText()
  );
}

async function suiteRequestFailure() {
  var d = makePage({ status: 400, body: JSON.stringify({ detail: "gear inventory is empty" }) });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();

  check(
    "the server's own reason is what the user reads",
    d.statusEl.textContent === "gear inventory is empty" && d.statusEl.classList.contains("err"),
    d.statusEl.textContent + " / " + d.statusEl.className
  );
  check(
    "and is raised as a toast as well, since the status line is easy to miss",
    d.toasts.length === 1 && d.toasts[0].msg === "gear inventory is empty" && d.toasts[0].ok === false,
    JSON.stringify(d.toasts)
  );
  check(
    "and no half-drawn result is left behind",
    d.resultEl.hidden === true && d.deltaEl.children.length === 0,
    d.resultEl.hidden + " / delta spans=" + d.deltaEl.children.length
  );
  check("and the button comes back", d.runBtn.disabled === false, d.runBtn.disabled);

  // FastAPI's own validation errors put a list of objects in `detail`.
  d.queueReply({
    status: 422,
    statusText: "Unprocessable Entity",
    body: JSON.stringify({ detail: [{ loc: ["body", "grey"], msg: "x" }] }),
  });
  d.submit();
  await settle();
  check(
    "a non-string detail is never printed raw",
    d.statusEl.textContent.indexOf("object Object") === -1 &&
      d.statusEl.textContent.indexOf("422") !== -1,
    d.statusEl.textContent
  );
  record("validation_status", d.statusEl.textContent);

  d.queueReply({ status: 500, body: "<html>proxy exploded</html>" });
  d.submit();
  await settle();
  check(
    "a reply that is not JSON at all still reports the failure",
    d.statusEl.classList.contains("err") && d.statusEl.textContent.indexOf("500") !== -1,
    d.statusEl.textContent
  );

  d.queueReply({ reject: "network down" });
  d.submit();
  await settle();
  check(
    "and so does a request that never lands",
    d.statusEl.classList.contains("err") && d.statusEl.textContent === "network down",
    d.statusEl.textContent
  );
  check("the button survives every one of them", d.runBtn.disabled === false, d.runBtn.disabled);
}

async function suiteStaleResultsAreDropped() {
  var d = makePage({ result: goodResult() });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();
  check("a first search succeeds", d.resultEl.hidden === false, d.resultEl.hidden);

  d.queueReply({ status: 400, body: JSON.stringify({ detail: "gear inventory is empty" }) });
  d.submit();
  await settle();
  check(
    "a failed search takes the previous proposal down with it",
    d.resultEl.hidden === true,
    d.resultEl.hidden
  );

  d.holdNextFetch();
  d.submit();
  await settle();
  check(
    "and a proposal is hidden the moment the next search starts",
    d.resultEl.hidden === true,
    d.resultEl.hidden
  );
  d.releaseFetch();
  await settle();
}

async function suiteBusyLockout() {
  var d = makePage({ result: goodResult() });
  await boot(d);
  fillBag(d);
  d.holdNextFetch();
  d.submit();
  await settle();

  check("the search is in flight", d.calls.length === 1, JSON.stringify(d.calls.length));
  check(
    "the run button locks while it is",
    d.runBtn.disabled === true && d.runBtn.classList.contains("busy"),
    d.runBtn.disabled + " / " + d.runBtn.className
  );
  d.submit();
  await settle();
  check(
    "so a second submit cannot start a second multi-second solve",
    d.calls.length === 1,
    JSON.stringify(d.calls.length)
  );

  d.releaseFetch();
  await settle();
  check(
    "and the lock lifts when the answer lands",
    d.runBtn.disabled === false && !d.runBtn.classList.contains("busy"),
    d.runBtn.disabled + " / " + d.runBtn.className
  );
  d.submit();
  await settle();
  check("leaving the form usable again", d.calls.length === 2, JSON.stringify(d.calls.length));
}

async function suiteWithoutGear() {
  var d = makePage({ result: goodResult(), gearEnabled: false });
  await boot(d);

  check(
    "a gear-less app renders the run button already disabled",
    d.runBtn.disabled === true,
    d.runBtn.disabled
  );
  // A disabled submit button cannot be clicked, but Enter in a number box
  // still submits the form — which is why the guard is in the handler. The
  // count is planted directly: the boxes are disabled too, so the only way
  // to reach the guard on its own (rather than the empty-bag one) is to put
  // the form in the state a later template change could leave it in.
  d.fodder("grey").value = "12";
  d.submit();
  await settle();
  check(
    "and submitting anyway sends nothing, bag or no bag",
    d.calls.length === 0,
    JSON.stringify(d.calls)
  );
  check(
    "nor does the script hand the disabled button back",
    d.runBtn.disabled === true,
    d.runBtn.disabled
  );
}

async function suiteInjection() {
  var hostile = goodResult();
  hostile.steps[0].name = '<img src=x onerror="alert(1)">';
  hostile.steps[1].name = "Warden's \"Greaves\" & <b>co</b>";
  hostile.best_summary = {
    mode: "rally_lead",
    heroes: ['<script>alert(1)</script>', "Saul"],
  };
  var d = makePage({ result: hostile });
  await boot(d);
  fillBag(d);
  d.submit();
  await settle();

  var steps = d.steps();
  check(
    "an OCR'd piece name lands as text, tags and all",
    steps[0].name === '<img src=x onerror="alert(1)">',
    steps[0].name
  );
  check(
    "quotes and ampersands survive verbatim rather than being double-escaped",
    steps[1].name === "Warden's \"Greaves\" & <b>co</b>",
    steps[1].name
  );
  check(
    "and so does a hostile hero name on the target line",
    d.targetEl.textContent === "Swordland · rally lead · <script>alert(1)</script>, Saul",
    d.targetEl.textContent
  );
  check(
    "because the page assigns innerHTML nowhere — there is no markup to inject into",
    d.htmlWrites() === 0,
    "innerHTML assignments=" + d.htmlWrites()
  );
}

/* Every grouped number this page prints is pinned to en-US, so the same
   1,200 XP does not render "1.200" for one user and "1 200" for another while
   the troops editor and the lineup board beside it stay on commas. The exact
   strings asserted elsewhere in this file cannot see the difference — the
   host's own locale is usually en-US, so a bare toLocaleString() produces the
   same commas. So toLocaleString is swapped for a sentinel that fires when
   the locale argument is omitted, the technique
   tests/js/troops_editor_harness.js was using alone. */
async function suiteLocale() {
  var d = makePage({ result: goodResult() });
  await boot(d);

  var original = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (locale) {
    if (locale === undefined) return "LOCALE-DEFAULT";
    return original.call(this, locale);
  };
  try {
    fillBag(d);
    d.submit();
    await settle();
    // groupInt writes the XP on each step row; fmtUtility writes the
    // baseline/best/delta triple on the line above them.
    var shown =
      d.deltaText() +
      " | " +
      d
        .steps()
        .map(function (s) {
          return s.meta;
        })
        .join(" | ");
    record("locale_rendered", shown);
    // Holds on any engine: the sentinel only proves that *some* locale was
    // passed, which is the fix. Whether the result is comma-grouped depends
    // on the engine having Intl.
    check(
      "the planner pins its grouping instead of following the viewer's locale",
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
    suiteHappyPath,
    suiteEventAndModeSwitching,
    suiteBlankCounts,
    suiteRefusesUnsendableCounts,
    suiteEmptyBag,
    suiteNoSpendsFound,
    suiteNoValueSummary,
    suiteSingularAndFallbacks,
    suiteArenaSummary,
    suiteRequestFailure,
    suiteStaleResultsAreDropped,
    suiteBusyLockout,
    suiteWithoutGear,
    suiteInjection,
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
