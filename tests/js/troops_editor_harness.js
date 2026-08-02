/* Executable coverage for the troops editor's client-side logic.
 *
 * ks/heroes/ui/static/troops.js holds the whole save state machine (debounce,
 * dedupe, in-flight coalescing, validation, blank/blur handling) and the repo
 * has no browser to run it in. This harness stands up a fake DOM, a
 * controllable clock and a recordable fetch, then runs the *real, unmodified*
 * source against them. tests/test_heroes_troops_editor_js.py injects the two
 * static files at the @@...@@ markers below and runs this under whatever JS
 * engine the host has (node/bun/jsc/...), so nothing here may assume a
 * particular runtime beyond ES2017 + Promises.
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
  this.attrs = attrs || {};
  this.dataset = {};
  this.value = "";
  this.textContent = "";
  this.className = "";
  this.hidden = false;
  this.validity = { badInput: false };
  this.listeners = {};
  this.classes = {};
  var self = this;
  this.classList = {
    toggle: function (name, force) {
      self.classes[name] = !!force;
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
El.prototype.fire = function (type) {
  (this.listeners[type] || []).slice().forEach(function (fn) {
    fn({ type: type });
  });
};

var TYPES = ["infantry", "cavalry", "archers"];
/* config/troops.yaml, the same seed the server renders from. */
var SEED = {
  infantry: { 3: 1015, 6: 30084, 7: 2759 },
  cavalry: { 1: 1000, 2: 2288, 3: 4197, 4: 114, 6: 17473, 7: 2852 },
  archers: { 1: 245, 2: 1024, 3: 2630, 6: 20420, 7: 5067 },
};
var SEED_TOTALS = { infantry: 33858, cavalry: 27924, archers: 29386 };
var MARCH = 80280;

/**
 * Build a page, install it over the globals troops.js reaches for, and hand
 * back the levers the driver needs. Every suite gets its own, so state never
 * leaks between scenarios. Attributes mirror inventory_troops.html exactly —
 * every input carries min="0", truegold also carries max="5" — because the
 * clamp logic reads its bounds off those attributes.
 * @param {{truegold?: number|string, tierValues?: Object}} [opts]
 *        tierValues is keyed "type:tier", e.g. {"infantry:1": "-3"}.
 */
function makeDom(opts) {
  opts = opts || {};
  var tierValues = opts.tierValues || {};

  var scalars = [];
  var tiers = [];
  var totals = {};

  function makeScalar(field, label, value, max) {
    var attrs = { min: "0", step: "1" };
    if (max !== undefined) attrs.max = String(max);
    var el = new El("input", attrs);
    el.dataset.field = field;
    el.dataset.label = label;
    el.value = String(value);
    scalars.push(el);
    return el;
  }
  makeScalar("march_capacity", "March capacity", MARCH);
  makeScalar("truegold", "Truegold", opts.truegold === undefined ? 0 : opts.truegold, 5);

  TYPES.forEach(function (type) {
    totals[type] = new El("span");
    totals[type].textContent = String(SEED_TOTALS[type]);
    for (var tier = 1; tier <= 11; tier++) {
      var el = new El("input", { min: "0", step: "1" });
      el.dataset.type = type;
      el.dataset.tier = String(tier);
      el.dataset.label = type + " T" + tier;
      var override = tierValues[type + ":" + tier];
      el.value =
        override === undefined
          ? String((SEED[type] && SEED[type][tier]) || 0)
          : String(override);
      tiers.push(el);
    }
  });

  var form = new El("form");
  form.dataset.saveUrl = "/api/troops";
  form.querySelectorAll = function (sel) {
    if (sel === "input[data-field]") return scalars;
    if (sel === "input[data-tier]") return tiers;
    return [];
  };
  form.querySelector = function (sel) {
    var m = /^\[data-total-for="(\w+)"\]$/.exec(sel);
    return m ? totals[m[1]] || null : null;
  };

  var statusEl = new El("p");
  var noticeEl = new El("p");
  noticeEl.hidden = true; // matches the template's `hidden` attribute

  /* The toast lives behind accessors so the order of writes is observable:
     app.js must un-hide the live region *before* it writes the message. */
  var toastLog = [];
  var toastEl = new El("div");
  var hiddenValue = true;
  var textValue = "";
  Object.defineProperty(toastEl, "hidden", {
    get: function () {
      return hiddenValue;
    },
    set: function (v) {
      hiddenValue = v;
      toastLog.push("hidden=" + v);
    },
  });
  Object.defineProperty(toastEl, "textContent", {
    get: function () {
      return textValue;
    },
    set: function (v) {
      textValue = v;
      toastLog.push("text=" + v);
    },
  });

  globalThis.document = {
    getElementById: function (id) {
      if (id === "troops-form") return form;
      if (id === "save-status") return statusEl;
      if (id === "troops-repair-notice") return noticeEl;
      if (id === "toast") return toastEl;
      return null;
    },
  };

  /* --- controllable clock ------------------------------------------------- */

  var pending = {};
  var nextTimer = 1;
  globalThis.setTimeout = function (fn) {
    var id = nextTimer++;
    pending[id] = fn;
    return id;
  };
  globalThis.clearTimeout = function (id) {
    delete pending[id];
  };

  /* --- recordable fetch --------------------------------------------------- */

  var puts = [];
  var nextResponse = null; // overrides the reply for exactly one call
  var pendingMode = false; // next call hangs until release() is called
  var release = null;

  function defaultResponse() {
    return {
      ok: true,
      status: 200,
      json: function () {
        return Promise.resolve({ troops: {}, totals: {} });
      },
    };
  }

  globalThis.fetch = function (url, options) {
    puts.push({
      url: url,
      method: options.method,
      body: JSON.parse(options.body),
      keepalive: !!options.keepalive,
      contentType: options.headers && options.headers["Content-Type"],
      cache: options.cache,
    });
    var res = nextResponse || defaultResponse();
    nextResponse = null;
    if (pendingMode) {
      pendingMode = false;
      return new Promise(function (resolve) {
        release = function () {
          release = null;
          resolve(res);
        };
      });
    }
    return Promise.resolve(res);
  };

  var toasts = [];
  function stubShowToast(message, ok) {
    toasts.push({ msg: String(message), ok: !!ok });
  }
  var windowListeners = {};
  globalThis.window = {
    addEventListener: function (type, fn) {
      (windowListeners[type] = windowListeners[type] || []).push(fn);
    },
    showToast: stubShowToast,
  };
  if (typeof globalThis.console === "undefined") globalThis.console = {};
  globalThis.console.error = function (m) {
    toasts.push({ msg: String(m), ok: false, viaConsole: true });
  };

  /* --- fake sessionStorage (app.js's HeroesTrust helper) -------------------
     A bare global, matching how `document` is installed above: real browsers
     expose `sessionStorage` unqualified, and app.js reads it that way. Fresh
     per makeDom() call so state never leaks between suites. */
  var sessionStore = {};
  globalThis.sessionStorage = {
    getItem: function (key) {
      return Object.prototype.hasOwnProperty.call(sessionStore, key) ? sessionStore[key] : null;
    },
    setItem: function (key, value) {
      sessionStore[key] = String(value);
    },
    removeItem: function (key) {
      delete sessionStore[key];
    },
    clear: function () {
      sessionStore = {};
    },
  };

  return {
    form: form,
    statusEl: statusEl,
    noticeEl: noticeEl,
    notice: function () {
      return noticeEl.hidden ? "" : noticeEl.textContent;
    },
    toastEl: toastEl,
    toastLog: toastLog,
    stubShowToast: stubShowToast,
    puts: puts,
    toasts: toasts,
    scalar: function (field) {
      for (var i = 0; i < scalars.length; i++) {
        if (scalars[i].dataset.field === field) return scalars[i];
      }
      return null;
    },
    tier: function (type, tier) {
      for (var i = 0; i < tiers.length; i++) {
        if (tiers[i].dataset.type === type && tiers[i].dataset.tier === String(tier)) {
          return tiers[i];
        }
      }
      return null;
    },
    total: function (type) {
      return totals[type].textContent;
    },
    status: function () {
      return statusEl.textContent;
    },
    /* Shaped like a real request even when nothing was sent, so a check that
       expected a PUT and did not get one fails with its own message instead
       of throwing and taking the rest of the suite down with it — this
       harness is only useful if a regression reports every symptom. */
    lastPut: function () {
      if (!puts.length) {
        return {
          url: null,
          method: null,
          keepalive: false,
          body: { infantry: {}, cavalry: {}, archers: {} },
        };
      }
      return puts[puts.length - 1];
    },
    timerCount: function () {
      return Object.keys(pending).length;
    },
    runTimers: function () {
      var ids = Object.keys(pending);
      ids.forEach(function (id) {
        var fn = pending[id];
        delete pending[id];
        fn();
      });
      return ids.length;
    },
    replyWith: function (res) {
      nextResponse = res;
    },
    hangNextFetch: function () {
      pendingMode = true;
    },
    releaseFetch: function () {
      if (!release) throw new Error("no fetch is in flight to release");
      release();
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

/** Drain the microtask queue so awaited fetch continuations have all run. */
async function settle() {
  for (var i = 0; i < 50; i++) await Promise.resolve();
}

/** Set by detectIntlGrouping(): false on an engine built without Intl. */
var INTL_GROUPING = false;

/**
 * Pick the expected rendering of a total for this engine. Both spellings are
 * written out rather than derived from toLocaleString, so the assertion is
 * never comparing the implementation against itself; the grouping itself is
 * pinned by suiteLocale() and by the Python side's "{:,}".format check.
 */
function grouped(withSeparators, plain) {
  return INTL_GROUPING ? withSeparators : plain;
}

/* --- the units under test, injected verbatim by the pytest runner ---------- */

/** Runs ks/heroes/ui/static/troops.js against whatever makeDom() last installed. */
function loadTroopsEditor() {
// @@TROOPS_JS@@
}

/** Runs ks/heroes/ui/static/app.js, which publishes window.showToast. */
function loadSharedAppJs() {
// @@APP_JS@@
}

/* --- suites ---------------------------------------------------------------- */

async function suiteSaving() {
  var d = makeDom();
  loadTroopsEditor();
  await settle();

  // Load is inert: rendering must not write to disk, and the totals on screen
  // come from the DOM rather than a round trip.
  check("load fires no PUT", d.puts.length === 0, "puts=" + d.puts.length);
  check(
    "totals are recomputed from the rendered inputs",
    d.total("infantry") === grouped("33,858", "33858"),
    d.total("infantry")
  );

  // Typing debounces; the debounce sends the whole document.
  var t1 = d.tier("infantry", 1);
  t1.value = "5";
  t1.fire("input");
  check(
    "typing schedules a save instead of sending one",
    d.puts.length === 0 && d.timerCount() === 1,
    "puts=" + d.puts.length + " timers=" + d.timerCount()
  );
  check(
    "the total updates live while typing",
    d.total("infantry") === grouped("33,863", "33863"),
    d.total("infantry")
  );
  d.runTimers();
  await settle();
  check("the debounce fires exactly one PUT", d.puts.length === 1, "puts=" + d.puts.length);

  var put = d.lastPut();
  check(
    "it is a JSON PUT to the form's save URL",
    put.method === "PUT" && put.url === "/api/troops" && put.contentType === "application/json"
  );
  check(
    "it sends the whole document, every type and tier",
    Object.keys(put.body.infantry).length === 11 &&
      Object.keys(put.body.cavalry).length === 11 &&
      Object.keys(put.body.archers).length === 11 &&
      put.body.march_capacity === MARCH &&
      put.body.truegold === 0,
    JSON.stringify(Object.keys(put.body))
  );
  check("it carries the edited tier", put.body.infantry["1"] === 5, JSON.stringify(put.body.infantry));
  check("no null reaches the API", JSON.stringify(put.body).indexOf("null") === -1);
  check("keepalive is set so a save survives navigation", put.keepalive === true);
  check("the request is not cached", put.cache === "no-store", put.cache);
  check("status says Saved", d.status() === "Saved", d.status());

  // The server's own sums win once it answers.
  d.replyWith({
    ok: true,
    status: 200,
    json: function () {
      return Promise.resolve({ troops: {}, totals: { infantry: 7, cavalry: 8, archers: 9 } });
    },
  });
  t1.value = "6";
  t1.fire("blur");
  await settle();
  check("the server's totals replace the local sum", d.total("infantry") === "7", d.total("infantry"));

  // Dedupe: blurring an unchanged form is not a save.
  var before = d.puts.length;
  t1.fire("blur");
  await settle();
  check("blurring an unchanged form does not re-PUT", d.puts.length === before, "puts=+" + (d.puts.length - before));
  check("and it does not claim unsaved work", d.status() === "Saved", d.status());

  // A blank box mid-typing cancels the pending save and never sends null.
  before = d.puts.length;
  var t2 = d.tier("infantry", 7); // seeded 2759, so clearing it is a real change
  t2.value = "7";
  t2.fire("input");
  check("a valid keystroke schedules", d.timerCount() === 1);
  t2.value = "";
  t2.fire("input");
  check(
    "clearing the box cancels the pending save",
    d.timerCount() === 0 && d.puts.length === before,
    "timers=" + d.timerCount() + " puts=+" + (d.puts.length - before)
  );
  check("and does not nag mid-typing", d.toasts.length === 0, JSON.stringify(d.toasts));

  t2.fire("blur");
  await settle();
  check("blurring a blank box writes a visible 0", t2.value === "0", t2.value);
  check("and saves it", d.puts.length === before + 1, "puts=+" + (d.puts.length - before));
  check("as 0, not null", d.lastPut().body.infantry["7"] === 0, JSON.stringify(d.lastPut().body.infantry));

  // Client-side validation: a negative value never leaves the page.
  d.clearToasts();
  before = d.puts.length;
  var t3 = d.tier("cavalry", 4);
  t3.value = "-5";
  t3.fire("input");
  check("a negative keystroke schedules nothing", d.timerCount() === 0);
  check("and does not toast mid-typing", d.toasts.length === 0, JSON.stringify(d.toasts));
  t3.fire("blur");
  await settle();
  check("a negative value is not PUT", d.puts.length === before, "puts=+" + (d.puts.length - before));
  check(
    "the error names the offending field",
    d.toasts.length === 1 && /cavalry T4/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );
  check(
    "the field is marked invalid for assistive tech",
    t3.classes.invalid === true && t3.getAttribute("aria-invalid") === "true"
  );
  t3.value = "115";
  t3.fire("input");
  t3.fire("blur");
  await settle();
  check(
    "fixing it clears the flag and saves",
    t3.classes.invalid === false &&
      t3.getAttribute("aria-invalid") === null &&
      d.puts.length === before + 1,
    "puts=+" + (d.puts.length - before)
  );

  // max= is honoured, and the message quotes the bound.
  d.clearToasts();
  before = d.puts.length;
  var tg = d.scalar("truegold");
  tg.value = "9";
  tg.fire("blur");
  await settle();
  check("a value over max is not saved", d.puts.length === before, "puts=+" + (d.puts.length - before));
  check(
    "the error quotes the bound",
    d.toasts.length === 1 && /0 to 5/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );
  tg.value = "3";
  tg.fire("blur");
  await settle();
  check(
    "an in-range value saves",
    d.puts.length === before + 1 && d.lastPut().body.truegold === 3,
    "puts=+" + (d.puts.length - before)
  );

  // Text the browser refused to parse reads as "" but must not become 0.
  d.clearToasts();
  before = d.puts.length;
  var t5 = d.tier("archers", 5);
  t5.value = "";
  t5.validity.badInput = true;
  t5.fire("input");
  check("unparseable input schedules nothing", d.timerCount() === 0);
  t5.fire("blur");
  await settle();
  check("unparseable input is not saved", d.puts.length === before, "puts=+" + (d.puts.length - before));
  check("and is not silently turned into 0", t5.value === "", t5.value);
  check("it explains itself", d.toasts.length === 1, JSON.stringify(d.toasts));
  t5.validity.badInput = false;
  t5.value = "0";
  t5.fire("blur");
  await settle();

  // A server rejection surfaces the API's own message verbatim.
  d.clearToasts();
  d.replyWith({
    ok: false,
    status: 422,
    statusText: "Unprocessable Entity",
    json: function () {
      return Promise.resolve({ detail: "troops.infantry[1] must be non-negative; got -5" });
    },
  });
  var t6 = d.tier("archers", 8);
  t6.value = "12";
  t6.fire("blur");
  await settle();
  check(
    "a server error is toasted verbatim",
    d.toasts.length === 1 && /must be non-negative/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );
  check("and the status line stops claiming Saved", d.status() === "Not saved", d.status());

  // Navigating away flushes a debounce that has not fired yet.
  before = d.puts.length;
  var t7 = d.tier("archers", 1);
  t7.value = "77";
  t7.fire("input");
  check("a debounce is pending", d.timerCount() === 1);
  d.firePageHide();
  await settle();
  check(
    "pagehide flushes the pending save",
    d.puts.length === before + 1 && d.lastPut().body.archers["1"] === 77,
    "puts=+" + (d.puts.length - before)
  );
}

/* The in-flight path. Every fetch here is deliberately left unresolved so a
   second save really does arrive while `saving` is true — the state the rest
   of the suite can never reach, and where the revert-is-dropped bug lived. */
async function suiteInFlight() {
  var d = makeDom();
  loadTroopsEditor();
  await settle();

  var march = d.scalar("march_capacity");
  var original = march.value; // what the server currently holds

  d.hangNextFetch();
  march.value = "99999";
  march.fire("blur"); // blur saves immediately: no debounce to hide behind
  await settle();
  check("an edit starts a PUT", d.puts.length === 1, "puts=" + d.puts.length);
  check("which is still in flight", d.status() === "Saving…", d.status());
  record("race_puts_after_edit", d.puts.length);

  march.value = original; // user changes their mind and tabs away
  march.fire("blur");
  await settle();
  check(
    "the revert is held, not sent, while a PUT is in flight",
    d.puts.length === 1,
    "puts=" + d.puts.length
  );
  record("race_puts_during_flight", d.puts.length);

  d.releaseFetch();
  await settle();
  record("race_puts_after_release", d.puts.length);
  record("race_final_status", d.status());
  record("race_displayed", march.value);
  record("race_server", String(d.lastPut().body.march_capacity));
  check(
    "the revert is not dropped: it goes out once the first PUT lands",
    d.puts.length === 2,
    "puts=" + d.puts.length
  );
  check(
    "the last thing the server was told is the value on screen",
    String(d.lastPut().body.march_capacity) === march.value,
    "server=" + d.lastPut().body.march_capacity + " shown=" + march.value
  );
  check(
    'the status line only says "Saved" once they agree',
    d.status() === "Saved" && String(d.lastPut().body.march_capacity) === march.value,
    d.status()
  );

  // Several edits during one in-flight save collapse into one more PUT.
  var before = d.puts.length;
  d.hangNextFetch();
  var t = d.tier("cavalry", 2);
  t.value = "11";
  t.fire("blur");
  await settle();
  check("the first edit is in flight", d.puts.length === before + 1, "puts=+" + (d.puts.length - before));
  t.value = "22";
  t.fire("blur");
  t.value = "33";
  t.fire("blur");
  await settle();
  check(
    "further edits queue behind it rather than racing it",
    d.puts.length === before + 1,
    "puts=+" + (d.puts.length - before)
  );
  d.releaseFetch();
  await settle();
  check(
    "they coalesce into exactly one more PUT",
    d.puts.length === before + 2,
    "puts=+" + (d.puts.length - before)
  );
  check(
    "carrying the final value, not an intermediate one",
    d.lastPut().body.cavalry["2"] === 33,
    JSON.stringify(d.lastPut().body.cavalry)
  );
  await settle();
  check(
    "and the queue drains rather than looping",
    d.puts.length === before + 2,
    "puts=+" + (d.puts.length - before)
  );

  // An in-flight save whose document is unchanged still dedupes afterwards.
  before = d.puts.length;
  d.hangNextFetch();
  t.value = "44";
  t.fire("blur");
  await settle();
  t.fire("blur"); // no change, but arrives while saving
  await settle();
  d.releaseFetch();
  await settle();
  check(
    "a queued no-op is deduped once lastSavedBody is fresh",
    d.puts.length === before + 1,
    "puts=+" + (d.puts.length - before)
  );
  check("and it does not report failure", d.status() === "Saved", d.status());
}

/* A value outside the client-only min/max bounds already on disk must not
   brick every other field — and repairing it must not touch the file. */
async function suiteClampOnLoad() {
  var d = makeDom({ truegold: 7 }); // max="5"; the API does not enforce it
  loadTroopsEditor();
  await settle();

  check(
    "a value over max is pulled back to the bound",
    d.scalar("truegold").value === "5",
    d.scalar("truegold").value
  );
  // The regression test for "rendering the page must not rewrite the file":
  // a GET is not permission to destroy the number that was on disk.
  check("a clamping page load fires no PUT at all", d.puts.length === 0, "puts=" + d.puts.length);
  record("clamp_load_puts", d.puts.length);
  check(
    "the clamp is reported in the persistent banner",
    /Truegold was 7, shown as 5/.test(d.notice()),
    d.notice()
  );
  check(
    "and not in a toast the next message would overwrite",
    d.toasts.length === 0,
    JSON.stringify(d.toasts)
  );
  check(
    "the banner says the correction is not on disk yet",
    /next edit saves/.test(d.notice()),
    d.notice()
  );

  var before = d.puts.length;
  var t = d.tier("infantry", 1);
  t.value = "5";
  t.fire("blur");
  await settle();
  check(
    "every other field is saveable again",
    d.puts.length === before + 1 && d.lastPut().body.infantry["1"] === 5,
    "puts=+" + (d.puts.length - before)
  );
  check(
    "and that first edit carries the corrected value to disk",
    d.lastPut().body.truegold === 5,
    String(d.lastPut().body.truegold)
  );
  check(
    "no field is left flagged invalid",
    t.classes.invalid === false && d.scalar("truegold").classes.invalid === false
  );

  // Below min is the same class of bug: troops_form.py renders a negative
  // straight through, readInt() rejects it, and save() blocks on every field.
  var neg = makeDom({ tierValues: { "infantry:1": "-3" } });
  loadTroopsEditor();
  await settle();
  check("a value below min is pulled up to the bound", neg.tier("infantry", 1).value === "0", neg.tier("infantry", 1).value);
  check("clamping a negative fires no PUT either", neg.puts.length === 0, "puts=" + neg.puts.length);
  check(
    "the negative is named in the banner",
    /infantry T1 was -3, shown as 0/.test(neg.notice()),
    neg.notice()
  );
  var t2 = neg.tier("cavalry", 3);
  t2.value = "9";
  t2.fire("blur");
  await settle();
  check(
    "an unrelated field saves despite the negative on disk",
    neg.puts.length === 1 && neg.lastPut().body.cavalry["3"] === 9,
    "puts=" + neg.puts.length
  );
  check("and the repaired negative goes with it", neg.lastPut().body.infantry["1"] === 0);

  // Not everything can be repaired: a count past Number.MAX_SAFE_INTEGER has
  // no defensible replacement. It must be flagged and named, not swallowed.
  var huge = makeDom({ tierValues: { "archers:2": "99999999999999999999" } });
  loadTroopsEditor();
  await settle();
  check("an unclampable value is left alone", huge.tier("archers", 2).value === "99999999999999999999");
  check("and fires no PUT", huge.puts.length === 0, "puts=" + huge.puts.length);
  check(
    "it is flagged on load rather than on a save the user cannot trigger",
    huge.tier("archers", 2).classes.invalid === true &&
      huge.tier("archers", 2).getAttribute("aria-invalid") === "true"
  );
  check(
    "and the banner explains that nothing can save until it is fixed",
    /Nothing can save until you fix: archers T2 must be a whole number/.test(huge.notice()),
    huge.notice()
  );

  // Both at once: the case where a toast lost the clamp notice to the
  // validation error raised a moment later.
  var both = makeDom({ truegold: 7, tierValues: { "archers:2": "99999999999999999999" } });
  loadTroopsEditor();
  await settle();
  record("both_notice", both.notice());
  check(
    "a clamp and an unrepairable value are both reported, not one over the other",
    /Truegold was 7, shown as 5/.test(both.notice()) &&
      /Nothing can save until you fix: archers T2/.test(both.notice()),
    both.notice()
  );
  check("still no PUT", both.puts.length === 0, "puts=" + both.puts.length);
  var t3 = both.tier("cavalry", 3);
  t3.value = "9";
  t3.fire("blur");
  await settle();
  check(
    "the surviving validation error still blocks the save, as it must",
    both.puts.length === 0 && both.toasts.length === 1,
    "puts=" + both.puts.length + " toasts=" + JSON.stringify(both.toasts)
  );
  check(
    "and the banner is still on screen next to that toast",
    /Truegold was 7/.test(both.notice()),
    both.notice()
  );

  // Control: an in-range document is left completely alone.
  var clean = makeDom({ truegold: 5 });
  loadTroopsEditor();
  await settle();
  check(
    "an in-range document is not touched on load",
    clean.puts.length === 0 && clean.toasts.length === 0 && clean.notice() === "",
    "puts=" + clean.puts.length + " toasts=" + clean.toasts.length + " notice=" + clean.notice()
  );
  check("and its banner stays hidden", clean.noticeEl.hidden === true);
}

/* Live totals must be grouped the way Jinja's "{:,}".format grouped them, not
   the way the viewer's locale would. Number.prototype.toLocaleString is
   swapped out so a call that omits the locale is detectable. */
async function suiteLocale() {
  var d = makeDom();
  loadTroopsEditor();
  await settle();

  var original = Number.prototype.toLocaleString;
  Number.prototype.toLocaleString = function (locale) {
    if (locale === undefined) return "LOCALE-DEFAULT";
    return original.call(this, locale);
  };
  try {
    var t = d.tier("infantry", 2);
    t.value = "1234567";
    t.fire("input");
    var shown = d.total("infantry");
    record("live_total_infantry", shown);
    // Holds on any engine: the sentinel only proves that *some* locale was
    // passed, which is the actual fix. Whether the result is comma-grouped
    // depends on the engine having Intl, checked separately below.
    check(
      "live totals pin their grouping instead of following the viewer's locale",
      shown.indexOf("LOCALE-DEFAULT") === -1,
      shown
    );
  } finally {
    Number.prototype.toLocaleString = original;
  }
}

/* qjs and d8 are routinely built without Intl, and node can be built with
   --without-intl; there, toLocaleString("en-US") returns ungrouped digits
   however correct the source is. Reported so the Python side can skip the
   exact-string comparison instead of failing with a baffling diff. */
function detectIntlGrouping() {
  try {
    INTL_GROUPING = (1234567).toLocaleString("en-US") === "1,234,567";
  } catch (err) {
    INTL_GROUPING = false;
  }
  record("intl_grouping", INTL_GROUPING);
  record("intl_present", typeof Intl !== "undefined");
}

/* app.js: the shared live region must be un-hidden before its text is written,
   or screen readers drop the announcement. */
function suiteToastOrder() {
  var d = makeDom();
  var stub = d.stubShowToast;
  loadSharedAppJs();
  var showToast = globalThis.window.showToast;
  globalThis.window.showToast = stub; // leave the harness stub in place

  check("app.js publishes window.showToast", typeof showToast === "function");

  d.toastLog.length = 0;
  showToast("Saved", true);
  var unhide = d.toastLog.indexOf("hidden=false");
  var written = d.toastLog.indexOf("text=Saved");
  record("toast_log", d.toastLog.join(" -> "));
  check("the live region is un-hidden", unhide !== -1, d.toastLog.join(" -> "));
  check(
    "the message is written only after it is visible",
    unhide !== -1 && written !== -1 && written > unhide,
    d.toastLog.join(" -> ")
  );
  check("the ok style is applied", d.toastEl.className === "ok", d.toastEl.className);

  d.toastLog.length = 0;
  showToast(new Error("nope"), false);
  check("non-string messages are stringified", d.toastEl.textContent === "Error: nope", d.toastEl.textContent);
  check("the error style is applied", d.toastEl.className === "err", d.toastEl.className);
  check(
    "the ordering holds on the error path too",
    d.toastLog.indexOf("text=Error: nope") > d.toastLog.indexOf("hidden=false"),
    d.toastLog.join(" -> ")
  );

  d.runTimers();
  check(
    "the toast hides and clears itself afterwards",
    d.toastEl.hidden === true && d.toastEl.textContent === "" && d.toastEl.className === "",
    d.toastLog.join(" -> ")
  );
}

/* app.js: HeroesTrust persists a rescan's trust payload across the page
   reload that follows a successful rescan (both inventory pages navigate
   away on success, discarding in-memory JS state) — this is the written
   sessionStorage contract Task 5 consumes. */
function suiteHeroesTrust() {
  var d = makeDom();
  loadSharedAppJs();
  var HeroesTrust = globalThis.window.HeroesTrust;

  check(
    "app.js publishes window.HeroesTrust",
    typeof HeroesTrust === "object" && HeroesTrust !== null
  );

  check("load() with nothing stored returns null", HeroesTrust.load("gear") === null);

  var trust = { flags: { cell0: "changed", cell1: "incomplete" }, new: 0, changed: 1, incomplete: 1 };
  HeroesTrust.save("gear", trust);

  var raw = globalThis.sessionStorage.getItem("heroesUiTrust:gear");
  check("save() writes to the documented sessionStorage key", raw !== null, String(raw));

  var stored = raw ? JSON.parse(raw) : null;
  check(
    "the stored shape carries flags/new/changed/incomplete verbatim",
    !!stored &&
      JSON.stringify(stored.flags) === JSON.stringify(trust.flags) &&
      stored.new === 0 &&
      stored.changed === 1 &&
      stored.incomplete === 1,
    JSON.stringify(stored)
  );
  check(
    "save() adds a storedAt timestamp not present in the API payload",
    !!stored && typeof stored.storedAt === "number" && stored.storedAt > 0,
    JSON.stringify(stored)
  );

  var loaded = HeroesTrust.load("gear");
  check(
    "load() reads back exactly what save() wrote",
    JSON.stringify(loaded) === JSON.stringify(stored),
    JSON.stringify(loaded)
  );

  check(
    "gear and heroes payloads live in separate keys",
    globalThis.sessionStorage.getItem("heroesUiTrust:heroes") === null
  );
  HeroesTrust.save("heroes", { flags: { Helga: "new" }, new: 1, changed: 0, incomplete: 0 });
  check(
    "saving heroes does not clobber the gear payload",
    HeroesTrust.load("gear") !== null && HeroesTrust.load("heroes") !== null
  );

  HeroesTrust.clear("gear");
  check(
    "clear() removes only the requested kind",
    HeroesTrust.load("gear") === null && HeroesTrust.load("heroes") !== null
  );

  var threw = false;
  try {
    HeroesTrust.save("bogus", {});
  } catch (err) {
    threw = true;
  }
  check("save() rejects an unknown kind instead of silently writing garbage", threw);

  // load()/clear() validate `kind` the same way save() does — all three go
  // through the same storageKey() guard, so a typo'd kind fails loud on any
  // of them rather than only on save().
  var loadThrew = false;
  try {
    HeroesTrust.load("bogus");
  } catch (err) {
    loadThrew = true;
  }
  check("load() rejects an unknown kind the same way save() does", loadThrew);

  var clearThrew = false;
  try {
    HeroesTrust.clear("bogus");
  } catch (err) {
    clearThrew = true;
  }
  check("clear() rejects an unknown kind the same way save() does", clearThrew);

  // Corrupt stored JSON (hand-edited, or left over from an older shape)
  // must read back as "nothing usable", not throw.
  globalThis.sessionStorage.setItem("heroesUiTrust:heroes", "{not valid json");
  check(
    "load() returns null instead of throwing on corrupt stored JSON",
    HeroesTrust.load("heroes") === null
  );

  // A real storage failure (quota exceeded, disabled in private mode, ...)
  // must not propagate out of save() — the specific guarantee app.js's
  // docstring promises. The stub must actually throw, or this exercises
  // nothing.
  var realSetItem = globalThis.sessionStorage.setItem;
  globalThis.sessionStorage.setItem = function () {
    throw new Error("QuotaExceededError");
  };
  var saveThrewOnStorageFailure = false;
  try {
    HeroesTrust.save("gear", trust);
  } catch (err) {
    saveThrewOnStorageFailure = true;
  }
  globalThis.sessionStorage.setItem = realSetItem;
  check(
    "save() swallows a real sessionStorage failure instead of throwing",
    !saveThrewOnStorageFailure
  );
}

/* --- run ------------------------------------------------------------------- */

(async function main() {
  try {
    detectIntlGrouping();
    await suiteSaving();
    await suiteInFlight();
    await suiteClampOnLoad();
    await suiteLocale();
    suiteToastOrder();
    suiteHeroesTrust();
  } catch (err) {
    check("harness ran to completion", false, String((err && err.stack) || err));
  }
  EMIT("@@RESULTS@@" + JSON.stringify({ checks: checks, data: data }));
})();
