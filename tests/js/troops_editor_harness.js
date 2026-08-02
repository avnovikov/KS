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
 * leaks between scenarios.
 * @param {{truegold?: number|string}} [opts]
 */
function makeDom(opts) {
  opts = opts || {};

  var scalars = [];
  var tiers = [];
  var totals = {};

  function makeScalar(field, label, value, max) {
    var el = new El("input", max === undefined ? {} : { max: String(max) });
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
      var el = new El("input");
      el.dataset.type = type;
      el.dataset.tier = String(tier);
      el.dataset.label = type + " T" + tier;
      el.value = String((SEED[type] && SEED[type][tier]) || 0);
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

  return {
    form: form,
    statusEl: statusEl,
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
    lastPut: function () {
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
    d.total("infantry") === "33,858",
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
    d.total("infantry") === "33,863",
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

/* An out-of-range value already on disk must not brick every other field. */
async function suiteClampOnLoad() {
  var d = makeDom({ truegold: 7 }); // max="5"; the API does not enforce it
  loadTroopsEditor();
  await settle();

  check("the out-of-range field is pulled back to its bound", d.scalar("truegold").value === "5", d.scalar("truegold").value);
  check(
    "the clamp is announced rather than silent",
    d.toasts.length === 1 && /Truegold/.test(d.toasts[0].msg),
    JSON.stringify(d.toasts)
  );
  check(
    "and written back, so what is stored is what is shown",
    d.puts.length === 1 && d.lastPut().body.truegold === 5,
    JSON.stringify(d.puts.map(function (p) { return p.body.truegold; }))
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
  check("no field is left flagged invalid", t.classes.invalid === false && d.scalar("truegold").classes.invalid === false);

  // Control: an in-range document is left completely alone.
  var clean = makeDom({ truegold: 5 });
  loadTroopsEditor();
  await settle();
  check("an in-range document is not touched on load", clean.puts.length === 0 && clean.toasts.length === 0,
        "puts=" + clean.puts.length + " toasts=" + clean.toasts.length);
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
    check(
      "live totals pin their grouping instead of following the viewer's locale",
      shown.indexOf("LOCALE-DEFAULT") === -1,
      shown
    );
  } finally {
    Number.prototype.toLocaleString = original;
  }
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

/* --- run ------------------------------------------------------------------- */

(async function main() {
  try {
    await suiteSaving();
    await suiteInFlight();
    await suiteClampOnLoad();
    await suiteLocale();
    suiteToastOrder();
  } catch (err) {
    check("harness ran to completion", false, String((err && err.stack) || err));
  }
  EMIT("@@RESULTS@@" + JSON.stringify({ checks: checks, data: data }));
})();
