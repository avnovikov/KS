/* Troops inventory editor: debounced auto-save of the whole document.
 *
 * Why the whole document rather than a patch: PUT /api/troops is a top-level
 * merge in which a type block replaces its counterpart wholesale, so a
 * partial body can only ever be *more* surprising. Sending everything also
 * keeps the on-disk file self-consistent and lets the page repair a corrupt
 * troops.yaml (a complete, valid PUT is self-healing) — the document is ~35
 * small integers, so there is nothing to save by sending less.
 *
 * Blank inputs: a cleared box is never sent as JSON null (which the API
 * rightly 422s). While a field is empty or half-typed no PUT is scheduled at
 * all, and on blur an empty field is filled in with a visible 0 and saved —
 * so what is stored is always what is shown.
 *
 * Out-of-range inputs: `min`/`max` are client-only bounds the API does not
 * enforce, so a document already outside them on load is clamped in the DOM —
 * visibly, and reported in a banner — rather than left to block every *other*
 * field's save. Rendering the page never writes: the correction goes to disk
 * with the user's first real edit.
 */
(function () {
  "use strict";

  var form = document.getElementById("troops-form");
  if (!form) return;

  var SAVE_URL = form.dataset.saveUrl || "/api/troops";
  var DEBOUNCE_MS = 600;

  var statusEl = document.getElementById("save-status");
  var noticeEl = document.getElementById("troops-repair-notice");
  var scalarInputs = Array.prototype.slice.call(
    form.querySelectorAll("input[data-field]")
  );
  var tierInputs = Array.prototype.slice.call(
    form.querySelectorAll("input[data-tier]")
  );
  var allInputs = scalarInputs.concat(tierInputs);

  var timer = null;
  var saving = false;
  var queued = false;
  var lastSavedBody = null;
  var savedOnce = false;

  /* --- reading the form --------------------------------------------------- */

  /** True when the box is empty (as opposed to holding text the browser
   *  refused to parse, which reads as empty too but sets badInput). */
  function isBlank(input) {
    if (input.validity && input.validity.badInput) return false;
    return String(input.value).trim() === "";
  }

  /** Non-negative integer in range, or null when the value cannot be sent. */
  function readInt(input) {
    if (input.validity && input.validity.badInput) return null;
    var raw = String(input.value).trim();
    if (raw === "") return 0; // blank means zero; blur makes that visible
    if (!/^\d+$/.test(raw)) return null; // no signs, decimals, exponents
    var value = Number(raw);
    if (!Number.isSafeInteger(value)) return null;
    var max = input.getAttribute("max");
    if (max !== null && value > Number(max)) return null;
    return value;
  }

  function readDoc() {
    var doc = {};
    scalarInputs.forEach(function (input) {
      doc[input.dataset.field] = readInt(input);
    });
    tierInputs.forEach(function (input) {
      var type = input.dataset.type;
      if (!doc[type]) doc[type] = {};
      doc[type][input.dataset.tier] = readInt(input);
    });
    return doc;
  }

  /* --- feedback ----------------------------------------------------------- */

  function toast(message, ok) {
    if (typeof window.showToast === "function") window.showToast(message, ok);
    else if (!ok) console.error(message);
  }

  function setStatus(text, kind) {
    if (!statusEl) return;
    // Rewriting the same text would re-announce it on every keystroke.
    if (statusEl.textContent !== text) statusEl.textContent = text;
    statusEl.className = "save-status" + (kind ? " " + kind : "");
  }

  function markValidity(input, ok) {
    input.classList.toggle("invalid", !ok);
    if (ok) input.removeAttribute("aria-invalid");
    else input.setAttribute("aria-invalid", "true");
  }

  function fieldLabel(input) {
    return input.dataset.label || input.id;
  }

  function invalidMessage(input) {
    var max = input.getAttribute("max");
    if (max !== null) {
      return fieldLabel(input) + " must be a whole number from 0 to " + max;
    }
    return fieldLabel(input) + " must be a whole number, 0 or more";
  }

  /* Group digits the way the server-rendered total already is.
   * The template formats with Python's `"{:,}".format`, which is always
   * comma-grouped regardless of locale; a bare toLocaleString() would follow
   * the *browser's* locale and flip 33.858 <-> 33,858 the moment the user
   * typed. Pinning en-US keeps the live total identical to the one Jinja
   * rendered a moment earlier. */
  function groupDigits(value) {
    return Number(value).toLocaleString("en-US");
  }

  function setTotal(type, value) {
    var el = form.querySelector('[data-total-for="' + type + '"]');
    if (el) el.textContent = groupDigits(value);
  }

  function recomputeTotals() {
    var sums = {};
    tierInputs.forEach(function (input) {
      var type = input.dataset.type;
      var value = readInt(input);
      sums[type] = (sums[type] || 0) + (value === null ? 0 : value);
    });
    Object.keys(sums).forEach(function (type) {
      setTotal(type, sums[type]);
    });
  }

  /* --- saving ------------------------------------------------------------- */

  function cancelPending() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function schedule() {
    cancelPending();
    setStatus("Editing…");
    timer = setTimeout(function () {
      timer = null;
      save();
    }, DEBOUNCE_MS);
  }

  async function save(origin) {
    cancelPending();
    var bad = allInputs.filter(function (input) {
      var ok = readInt(input) !== null;
      markValidity(input, ok);
      return !ok;
    });
    if (bad.length) {
      var culprit = origin && readInt(origin) === null ? origin : bad[0];
      setStatus("Not saved", "err");
      toast(invalidMessage(culprit), false);
      return;
    }

    // Order matters: in-flight *before* dedupe. lastSavedBody is only
    // refreshed when a PUT succeeds, so while one is in flight it still
    // describes the pre-save document. Deduping against it first would drop
    // an edit that reverts the form back to that stale value (type A, blur,
    // type back to A, blur) — the in-flight PUT would then land, set
    // lastSavedBody to the value the user just undid, and the status line
    // would say "Saved" while the server held something else. Queueing
    // instead re-runs save() after lastSavedBody has been refreshed, where
    // the dedupe below is finally comparing against the truth.
    if (saving) {
      queued = true;
      return;
    }

    var body = JSON.stringify(readDoc());
    if (body === lastSavedBody) {
      // Nothing to send — e.g. an edit typed and undone. Clear "Editing…"
      // so the page never claims unsaved work it does not have.
      setStatus(savedOnce ? "Saved" : "", savedOnce ? "ok" : "");
      return;
    }
    saving = true;
    setStatus("Saving…");
    try {
      var res = await fetch(SAVE_URL, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: body,
        cache: "no-store",
        // Let an in-flight save survive tapping away to another tab.
        keepalive: true,
      });
      var data = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        var detail = data.detail || res.statusText;
        throw new Error(
          typeof detail === "string" ? detail : JSON.stringify(detail)
        );
      }
      lastSavedBody = body;
      savedOnce = true;
      if (
        data.totals &&
        data.totals.march_capacity > 0 &&
        typeof window.markSetupStep === "function"
      ) {
        window.markSetupStep("troops");
      }
      if (data.totals) {
        Object.keys(data.totals).forEach(function (key) {
          if (form.querySelector('[data-total-for="' + key + '"]')) {
            setTotal(key, data.totals[key]);
          }
        });
      }
      setStatus("Saved", "ok");
    } catch (err) {
      setStatus("Not saved", "err");
      toast(String((err && err.message) || err), false);
    } finally {
      saving = false;
      if (queued) {
        queued = false;
        save();
      }
    }
  }

  /* --- wiring ------------------------------------------------------------- */

  allInputs.forEach(function (input) {
    input.addEventListener("input", function () {
      recomputeTotals();
      markValidity(input, true); // never nag mid-typing
      if (isBlank(input) || readInt(input) === null) {
        cancelPending(); // an empty box must not fire a failing PUT
        setStatus("Editing…");
        return;
      }
      schedule();
    });

    input.addEventListener("blur", function () {
      if (isBlank(input)) input.value = "0";
      recomputeTotals();
      save(input);
    });
  });

  /** Pull what can be pulled back in range, and collect what cannot.
   *
   *  `min`/`max` are client-only bounds the API does not enforce, and
   *  troops_form.py renders whatever integer was on disk, so the page can
   *  load holding a value readInt() refuses to send. save() blocks on *any*
   *  unreadable field, so a single bad number — `truegold: 7`, or an
   *  `infantry: {1: -3}` left behind by a hand edit — used to make the whole
   *  form unsaveable, the only clue being a toast naming a field the user
   *  never touched.
   *
   *  A value with an unambiguous in-range neighbour is moved to it: below
   *  `min` becomes `min`, above `max` becomes `max`. Anything else (text the
   *  browser rejected, a count past Number.MAX_SAFE_INTEGER) has no
   *  defensible replacement, so it is left alone and reported instead.
   *
   *  Nothing is written to disk here. This runs during a GET, the pre-clamp
   *  number is the user's, and destroying it before they have seen the notice
   *  would be worse than the stale value: the correction rides along with
   *  their first real edit, which is why lastSavedBody is snapshotted first.
   *  @returns {{clamped: string[], blocked: Element[]}}
   */
  function reviewLoadedValues() {
    var clamped = [];
    allInputs.forEach(function (input) {
      var raw = String(input.value).trim();
      if (!/^-?\d+$/.test(raw)) return;
      var value = Number(raw);
      if (!Number.isSafeInteger(value)) return;
      var min = input.getAttribute("min");
      var max = input.getAttribute("max");
      var bound = null;
      if (min !== null && value < Number(min)) bound = min;
      else if (max !== null && value > Number(max)) bound = max;
      if (bound === null) return;
      input.value = bound;
      clamped.push(fieldLabel(input) + " was " + raw + ", shown as " + bound);
    });
    var blocked = allInputs.filter(function (input) {
      return readInt(input) === null;
    });
    // Flag them now rather than waiting for a save the user cannot trigger.
    blocked.forEach(function (input) {
      markValidity(input, false);
    });
    return { clamped: clamped, blocked: blocked };
  }

  /** Report load-time repairs in the persistent banner, not a toast.
   *
   *  A toast is the wrong channel for this: #toast is shared and runs on one
   *  timer, so a clamp notice raised at load is overwritten by the very next
   *  message — including the validation error that an unclampable field in
   *  the same file triggers — and then times out unread. The banner sits
   *  above the form until the page is left.
   */
  function showRepairNotice(review) {
    if (!noticeEl) return;
    var parts = [];
    if (review.clamped.length) {
      parts.push(
        "Out of range in your troops file: " +
          review.clamped.join("; ") +
          ". Your next edit saves the corrected value."
      );
    }
    if (review.blocked.length) {
      parts.push(
        "Nothing can save until you fix: " +
          review.blocked.map(invalidMessage).join("; ") +
          "."
      );
    }
    if (!parts.length) return;
    noticeEl.textContent = parts.join(" ");
    noticeEl.hidden = false;
  }

  // Trust the server's own sum once it answers, but start from what was
  // rendered so a stale total can never sit on screen.
  recomputeTotals();
  // Snapshot *before* clamping, so a clamp reads as a real pending change
  // that the user's first edit sends rather than one the dedupe eats.
  lastSavedBody = JSON.stringify(readDoc());

  var loadReview = reviewLoadedValues();
  if (loadReview.clamped.length) recomputeTotals();
  showRepairNotice(loadReview);

  window.addEventListener("pagehide", function () {
    if (timer) save();
  });
})();
