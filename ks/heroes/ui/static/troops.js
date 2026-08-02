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
 */
(function () {
  "use strict";

  var form = document.getElementById("troops-form");
  if (!form) return;

  var SAVE_URL = form.dataset.saveUrl || "/api/troops";
  var DEBOUNCE_MS = 600;

  var statusEl = document.getElementById("save-status");
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

  function invalidMessage(input) {
    var label = input.dataset.label || input.id;
    var max = input.getAttribute("max");
    if (max !== null) {
      return label + " must be a whole number from 0 to " + max;
    }
    return label + " must be a whole number, 0 or more";
  }

  function setTotal(type, value) {
    var el = form.querySelector('[data-total-for="' + type + '"]');
    if (el) el.textContent = Number(value).toLocaleString();
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

    var body = JSON.stringify(readDoc());
    if (body === lastSavedBody) {
      // Nothing to send — e.g. an edit typed and undone. Clear "Editing…"
      // so the page never claims unsaved work it does not have.
      setStatus(savedOnce ? "Saved" : "", savedOnce ? "ok" : "");
      return;
    }
    if (saving) {
      queued = true;
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

  // 35 fields and no submit button means Enter cannot implicitly submit —
  // but if that ever changes, save instead of navigating away with the form
  // serialized into the query string.
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    save();
  });

  // Trust the server's own sum once it answers, but start from what was
  // rendered so a stale total can never sit on screen.
  recomputeTotals();
  lastSavedBody = JSON.stringify(readDoc());

  window.addEventListener("pagehide", function () {
    if (timer) save();
  });
})();
