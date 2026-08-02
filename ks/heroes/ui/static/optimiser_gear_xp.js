/* Gear XP spend planner (layout A) for /optimiser/gear-xp.
 *
 * One column, one request: pick the event (and optionally the mode/side),
 * enter how much fodder is in the bag, and POST it all to
 * /api/optimize/gear-xp. The reply is a *proposal* — a baseline→best utility
 * delta, the ordered +1-level steps that got there, and what is left in the
 * bag. Nothing is written back to gear.json, by design; the user applies the
 * spends in game.
 *
 * Labels are never spelled twice. The event names, the unit each event's
 * utility is measured in (`data-unit`) and the fodder names (`data-label`)
 * are server-rendered and read back off the markup here, so the page holds
 * one copy of each.
 *
 * Text discipline: this file assigns no innerHTML at all. Piece names come
 * out of OCR and mode keys out of config, so every string the API returns
 * reaches the DOM through `textContent` on a node built here — which cannot
 * inject, and so needs no escaper. (app.js's window.escapeHtml is for pages
 * that must assemble nested markup; this one does not.)
 *
 * Blank boxes: a cleared count is never sent as JSON null. Blank means zero,
 * and the zero is written into the box — on blur, and again before any
 * request goes out — so what is sent is always what is on screen. A box
 * holding something that is not a whole number blocks the request entirely
 * rather than being silently coerced.
 */
(function () {
  "use strict";

  var form = document.getElementById("gear-xp-form");
  if (!form) return;

  var runBtn = document.getElementById("run-btn");
  var statusEl = document.getElementById("spend-status");
  var resultEl = document.getElementById("spend-result");
  var deltaEl = document.getElementById("delta-line");
  var targetEl = document.getElementById("target-line");
  var listEl = document.getElementById("spend-list");
  var emptyEl = document.getElementById("spend-empty");
  var leftoverEl = document.getElementById("leftover-line");
  // Every one of these is dereferenced unguarded below, so every one is
  // checked: a half-present shell must be inert, not half-wired.
  if (
    !runBtn ||
    !statusEl ||
    !resultEl ||
    !deltaEl ||
    !targetEl ||
    !listEl ||
    !emptyEl ||
    !leftoverEl
  ) {
    return;
  }

  var API_URL = form.dataset.apiUrl || "/api/optimize/gear-xp";
  var NO_STEPS =
    "No spend raises this lineup — the bag is too small for the next level, " +
    "or every piece is already at its cap.";

  function slice(list) {
    return Array.prototype.slice.call(list);
  }

  var eventButtons = slice(document.querySelectorAll("[data-event]"));
  var fodderInputs = slice(document.querySelectorAll("[data-fodder]"));

  /** event key -> the .stack-field wrapping that event's mode picker. */
  var modeFields = {};
  slice(document.querySelectorAll("[data-mode-for]")).forEach(function (el) {
    modeFields[el.dataset.modeFor] = el;
  });
  /** event key -> that event's <select>. Separate hook from the wrapper's so
   *  neither query can pick up the other. */
  var modeSelects = {};
  slice(document.querySelectorAll("[data-mode-select]")).forEach(function (el) {
    modeSelects[el.dataset.modeSelect] = el;
  });

  /** Read off the markup: {swordland: {label: "Swordland", unit: "Points"}}. */
  var eventMeta = {};
  eventButtons.forEach(function (btn) {
    eventMeta[btn.dataset.event] = {
      label: String(btn.textContent).trim(),
      unit: String(btn.dataset.unit || "Utility").trim()
    };
  });

  /** Fodder kind -> the name shown beside its box, and the form's own order,
   *  so a spend line and the leftover line list kinds the way the form does. */
  var fodderLabels = {};
  var fodderOrder = fodderInputs.map(function (input) {
    fodderLabels[input.dataset.fodder] = input.dataset.label || input.dataset.fodder;
    return input.dataset.fodder;
  });

  var activeEvent = (function () {
    for (var i = 0; i < eventButtons.length; i++) {
      if (eventButtons[i].classList.contains("on")) {
        return eventButtons[i].dataset.event;
      }
    }
    return eventButtons.length ? eventButtons[0].dataset.event : "swordland";
  })();

  /** Whether this app has a gear inventory at all — read off the button the
   *  server already disabled. A disabled submit button cannot be clicked,
   *  but Enter in a number box still submits the form, so run() checks this
   *  before doing anything rather than trusting the button alone. */
  var enabled = !runBtn.disabled;
  var busy = false;

  /* --- formatting ----------------------------------------------------------- */

  /** Comma-grouped integer. Pinned to en-US, as the troops editor's totals
   *  are: the browser's own locale would flip 1,200 <-> 1.200 between users. */
  function groupInt(value) {
    var n = Number(value);
    if (value == null || !isFinite(n)) return "—";
    return Math.round(n).toLocaleString("en-US");
  }

  /** Utility to one decimal, grouped. Sword/bear utilities run to five
   *  figures and arena scores to three, so both want grouping and neither
   *  wants more than one decimal. */
  function fmtUtility(value) {
    var n = Number(value);
    if (value == null || !isFinite(n)) return "—";
    var text = n.toFixed(1);
    var dot = text.indexOf(".");
    return Number(text.slice(0, dot)).toLocaleString("en-US") + text.slice(dot);
  }

  /** "8 Grey, 1 Green" in the form's own order; "" when nothing is counted.
   *
   *  Only kinds the form offers are listed, which is every kind the API can
   *  return: the box set is pinned to FodderBag's fields server-side
   *  (test_gear_xp_page_offers_one_box_per_fodder_kind_the_api_accepts), so a
   *  new kind grows a box — and therefore a label here — before it can
   *  appear in a reply. */
  function fmtFodder(counts) {
    if (!counts) return "";
    var parts = [];
    fodderOrder.forEach(function (kind) {
      var n = Number(counts[kind]);
      if (!isFinite(n) || n <= 0) return;
      parts.push(groupInt(n) + " " + (fodderLabels[kind] || kind));
    });
    return parts.join(", ");
  }

  /* --- DOM building --------------------------------------------------------- */

  /** Empty a node. `textContent = ""` drops its children, which is why this
   *  file never needs `innerHTML` — see the header note. */
  function clear(node) {
    node.textContent = "";
  }

  function addSpan(parent, className, text) {
    var el = document.createElement("span");
    if (className) el.className = className;
    el.textContent = text;
    parent.appendChild(el);
    return el;
  }

  /* --- feedback ------------------------------------------------------------- */

  /** app.js's shared writer, bound to this page's status paragraph — see
   *  there for why the two lines it replaced do not live here and again on
   *  the lineup board. */
  function setStatus(text, kind) {
    window.setStatusLine(statusEl, text, kind);
  }

  function toast(message, ok) {
    if (typeof window.showToast === "function") window.showToast(message, ok);
  }

  // Only ever reached past run()'s `!enabled` guard, so a gear-less page's
  // disabled button is never touched — there is deliberately no second
  // `!enabled` term here to go stale against that one.
  function setBusy(on) {
    busy = on;
    runBtn.disabled = on;
    runBtn.classList.toggle("busy", on);
  }

  function markValidity(input, ok) {
    input.classList.toggle("invalid", !ok);
    if (ok) input.removeAttribute("aria-invalid");
    else input.setAttribute("aria-invalid", "true");
  }

  /* --- the form ------------------------------------------------------------- */

  function selectEvent(key) {
    if (!eventMeta[key]) return;
    activeEvent = key;
    eventButtons.forEach(function (btn) {
      var on = btn.dataset.event === key;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    Object.keys(modeFields).forEach(function (ev) {
      modeFields[ev].hidden = ev !== key;
    });
  }

  eventButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      selectEvent(btn.dataset.event);
    });
  });

  /** True when the box is empty, as opposed to holding text the browser
   *  refused to parse — which also reads as an empty `value`, but sets
   *  badInput and must not be treated as "the user meant zero". */
  function isBlank(input) {
    if (input.validity && input.validity.badInput) return false;
    return String(input.value).trim() === "";
  }

  /** Non-negative whole number, or null when the box holds something that
   *  cannot be sent. Blank is 0 — and showZero() has already made that 0
   *  visible by the time this decides anything. */
  function readCount(input) {
    if (input.validity && input.validity.badInput) return null;
    var raw = String(input.value).trim();
    if (raw === "") return 0;
    if (!/^\d+$/.test(raw)) return null; // no signs, decimals or exponents
    var value = Number(raw);
    return Number.isSafeInteger(value) ? value : null;
  }

  function showZero(input) {
    if (isBlank(input)) input.value = "0";
  }

  fodderInputs.forEach(function (input) {
    input.addEventListener("input", function () {
      markValidity(input, readCount(input) !== null);
    });
    input.addEventListener("blur", function () {
      showZero(input);
      markValidity(input, readCount(input) !== null);
    });
  });

  /* --- rendering ------------------------------------------------------------ */

  function renderDelta(unit, baseline, best, delta) {
    clear(deltaEl);
    addSpan(deltaEl, "delta-label", unit);
    addSpan(deltaEl, "delta-from", fmtUtility(baseline));
    addSpan(deltaEl, "delta-arrow", "→");
    addSpan(deltaEl, "delta-to", fmtUtility(best));
    var badge = addSpan(
      deltaEl,
      "delta-badge",
      (delta > 0 ? "+" : "") + fmtUtility(delta)
    );
    badge.classList.add(delta > 0 ? "delta-up" : "delta-flat");
  }

  /** Which lineup the "best" number belongs to, taken from the *reply* and
   *  not the request: with "Best mode" selected, which mode actually won is
   *  the interesting half of the answer. */
  function renderTarget(label, summary) {
    var s = summary || {};
    var parts = [label];
    if (s.mode) parts.push(String(s.mode).replace(/_/g, " "));
    else if (s.side) parts.push(String(s.side));
    var heroes = Array.isArray(s.heroes)
      ? s.heroes.filter(function (name) {
          return name;
        })
      : [];
    if (heroes.length) parts.push(heroes.join(", "));
    targetEl.textContent = parts.join(" · ");
  }

  function renderSteps(steps) {
    clear(listEl);
    var rows = Array.isArray(steps) ? steps : [];
    emptyEl.hidden = rows.length > 0;
    if (!rows.length) {
      emptyEl.textContent = NO_STEPS;
      return;
    }
    rows.forEach(function (step, i) {
      var row = document.createElement("li");
      row.className = "spend-row";
      addSpan(row, "spend-rank", String(i + 1));
      var main = document.createElement("div");
      main.className = "spend-main";
      var name = step.name == null || step.name === "" ? step.piece_id : step.name;
      addSpan(main, "spend-name", name == null ? "—" : String(name));
      addSpan(main, "spend-meta", stepMeta(step));
      row.appendChild(main);
      listEl.appendChild(row);
    });
  }

  function stepMeta(step) {
    var parts = ["+" + groupInt(step.from_level) + " → +" + groupInt(step.to_level)];
    if (step.xp_spent != null) parts.push(groupInt(step.xp_spent) + " XP");
    var fodder = fmtFodder(step.fodder_spent);
    if (fodder) parts.push(fodder);
    return parts.join(" · ");
  }

  function renderLeftover(counts) {
    leftoverEl.textContent = "Left in the bag: " + (fmtFodder(counts) || "nothing");
  }

  function render(target, data) {
    var baseline = Number(data.baseline_utility);
    var best = Number(data.best_utility);
    var delta =
      data.delta_utility == null ? best - baseline : Number(data.delta_utility);
    renderDelta(target.unit, baseline, best, delta);
    renderTarget(target.label, data.best_summary);
    renderSteps(data.steps);
    renderLeftover(data.leftover);
    resultEl.hidden = false;
    return Array.isArray(data.steps) ? data.steps.length : 0;
  }

  /* --- running -------------------------------------------------------------- */

  /** app.js's shared reading of FastAPI's error envelope, with this page's
   *  own phrasing for the case where there is nothing usable in it. It lives
   *  there because the lineup board needs the same unwrapping and was doing
   *  without. */
  function detailOf(data, res) {
    var status = res.status + (res.statusText ? " " + res.statusText : "");
    return window.detailOf(data, "spend search failed (" + status + ")");
  }

  /** {ok, body} or {ok: false, message} — every blank/invalid box is decided
   *  before anything is sent, so no request can carry a null count. */
  function collect() {
    fodderInputs.forEach(showZero);
    var body = {};
    var bad = [];
    var total = 0;
    fodderInputs.forEach(function (input) {
      var n = readCount(input);
      markValidity(input, n !== null);
      if (n === null) {
        bad.push(input.dataset.label || input.dataset.fodder);
        return;
      }
      body[input.dataset.fodder] = n;
      total += n;
    });
    if (bad.length) {
      return {
        ok: false,
        message: "Enter a whole number, 0 or more, for " + bad.join(", ") + ".",
        kind: "err"
      };
    }
    if (total === 0) {
      return {
        ok: false,
        message: "Enter at least one piece of fodder to spend.",
        kind: "warn"
      };
    }
    body.event = activeEvent;
    var picker = modeSelects[activeEvent];
    var mode = picker ? String(picker.value || "") : "";
    if (mode) body.mode = mode;
    return { ok: true, body: body };
  }

  async function run() {
    if (busy || !enabled) return;
    var collected = collect();
    if (!collected.ok) {
      setStatus(collected.message, collected.kind);
      return;
    }
    // Whatever is on screen is now stale, and the reply may not agree with
    // the controls by the time it lands, so the target is captured here and
    // the old proposal goes away before the new one is asked for.
    var meta = eventMeta[activeEvent] || { label: activeEvent, unit: "Utility" };
    resultEl.hidden = true;
    setBusy(true);
    setStatus("Searching " + meta.label + " spends…", "");
    try {
      var res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collected.body)
      });
      var text = await res.text();
      var data = null;
      try {
        data = JSON.parse(text);
      } catch (_) {
        data = null;
      }
      if (!res.ok) throw new Error(detailOf(data, res));
      if (!data || typeof data !== "object") {
        throw new Error("spend search returned no result");
      }
      var count = render(meta, data);
      setStatus(
        count === 1 ? "1 spend proposed." : count + " spends proposed.",
        "ok"
      );
    } catch (err) {
      var message = String((err && err.message) || err);
      setStatus(message, "err");
      toast(message, false);
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    run();
  });
})();
