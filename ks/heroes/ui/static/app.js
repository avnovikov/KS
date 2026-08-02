/* Shared UI helpers loaded by _layout.html on every page.
 *
 * Kept inside an IIFE that only publishes window.showToast: every page script
 * is a classic (non-module) script sharing one global scope, so anything not
 * deliberately exported would collide across files. The inventory gear/heroes
 * pages used to inline their own showToast — near-identical copies that
 * shadowed this one and had already drifted apart on timing; both now call
 * this and declare no script of their own.
 *
 * A second IIFE below publishes window.HeroesTrust — see its own comment
 * for the sessionStorage contract inventory.js consumes.
 */
(function () {
  "use strict";

  var OK_MS = 2500;
  var ERR_MS = 6000; // errors carry a message worth reading — linger longer
  var timer = null;

  /**
   * Show a message in the #toast live region.
   * @param {string} message text to announce
   * @param {boolean} ok true for the success style, false for the error style
   */
  function showToast(message, ok) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.className = ok ? "ok" : "err";
    // Un-hide *before* writing the text: screen readers routinely miss
    // mutations made to a display:none live region. `hidden` is toggled as a
    // property alongside the class so role="status" behaves consistently.
    el.hidden = false;
    el.textContent = String(message);
    clearTimeout(timer);
    timer = setTimeout(function () {
      el.className = "";
      el.hidden = true;
      el.textContent = "";
    }, ok ? OK_MS : ERR_MS);
  }

  window.showToast = showToast;
})();

/**
 * Carries a rescan's trust payload (ks/heroes/ui/trust.py's flags/new/
 * changed/incomplete summary) across the page reload that follows a
 * successful rescan.
 *
 * WHY sessionStorage: both /inventory/gear and /inventory/heroes navigate
 * away on a successful rescan (window.location.replace / location.reload)
 * to render the freshly-scanned rows, which discards any in-memory JS
 * state. sessionStorage survives that reload — scoped to the tab, gone
 * when it closes — so the *next* render of the same inventory page can
 * still see which rows just changed.
 *
 * Contract for Task 5 (the inventory_gear.html / inventory_heroes.html
 * rewrite that consumes this):
 *   - Right after a successful `POST /api/gear/rescan`, call
 *     `HeroesTrust.save("gear", data.trust)` before navigating away; same
 *     for `HeroesTrust.save("heroes", data.trust)` after
 *     `/api/heroes/rescan`. `data.trust` is passed through unmodified —
 *     exactly the `{flags, new, changed, incomplete}` object the rescan
 *     API returns.
 *   - On the next render of that inventory page, call
 *     `HeroesTrust.load("gear")` / `HeroesTrust.load("heroes")` to read it
 *     back. Returns `null` if nothing is stored (first visit, or already
 *     cleared) or if storage was unavailable/corrupt.
 *   - Call `HeroesTrust.clear(kind)` once the payload has been consumed —
 *     e.g. right after applying row classes/the banner on page load, or
 *     when the user dismisses the banner / hits "Mark all reviewed" (see
 *     the plan for Task 5). Nothing here clears it automatically: an
 *     unconsumed payload keeps surfacing until a consumer explicitly
 *     clears it, so this step must not be skipped.
 *
 * sessionStorage keys (exact, one per inventory kind so gear and heroes
 * flags can never collide): "heroesUiTrust:gear", "heroesUiTrust:heroes".
 *
 * Stored shape (JSON-encoded string) — the API's `trust` object plus one
 * field added on the way in:
 *   {
 *     "flags": {"<piece_id-or-hero-name>": "new"|"changed"|"incomplete"},
 *     "new": <int>,
 *     "changed": <int>,
 *     "incomplete": <int>,
 *     "storedAt": <number>   // Date.now() at save() time — not part of the
 *                            // API response; lets a consumer decide a
 *                            // payload is too stale to show.
 *   }
 */
(function () {
  "use strict";

  var PREFIX = "heroesUiTrust:";
  var KINDS = { gear: true, heroes: true };

  function storageKey(kind) {
    if (!KINDS[kind]) {
      throw new Error('HeroesTrust: kind must be "gear" or "heroes", got ' + kind);
    }
    return PREFIX + kind;
  }

  /**
   * Persist a rescan's trust payload for the next render of this
   * inventory page. An unknown `kind` is a caller bug and throws
   * immediately; a *storage* failure (private-browsing quota, disabled
   * storage, …) never throws, since trust cues are a nice-to-have that
   * must not block the rescan success path.
   * @param {"gear"|"heroes"} kind which inventory table this payload is for
   * @param {{flags: Object, new: number, changed: number, incomplete: number}} trust
   *        the rescan API's `trust` object, passed through unmodified
   */
  function save(kind, trust) {
    var key = storageKey(kind); // throws before anything is attempted
    var payload = Object.assign({}, trust, { storedAt: Date.now() });
    try {
      sessionStorage.setItem(key, JSON.stringify(payload));
    } catch (_) {
      /* storage disabled/full: nothing to persist, nothing to crash. */
    }
  }

  /**
   * Read back the payload `save(kind, …)` last stored.
   * @param {"gear"|"heroes"} kind
   * @returns {?Object} the stored payload (with `storedAt`), or `null` if
   *          nothing is stored or it could not be parsed.
   */
  function load(kind) {
    var key = storageKey(kind); // throws before anything is attempted
    var raw;
    try {
      raw = sessionStorage.getItem(key);
    } catch (_) {
      return null;
    }
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  /**
   * Drop the stored payload for `kind` once it has been consumed.
   * @param {"gear"|"heroes"} kind
   */
  function clear(kind) {
    var key = storageKey(kind); // throws before anything is attempted
    try {
      sessionStorage.removeItem(key);
    } catch (_) {
      /* ignore */
    }
  }

  window.HeroesTrust = { save: save, load: load, clear: clear };
})();
