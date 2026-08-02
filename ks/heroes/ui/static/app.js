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
 * Publishes window.escapeHtml, window.safeUrl and window.bindDialogDismiss —
 * what every page that builds markup, points an <img> somewhere, or opens a
 * dialog needs.
 *
 * WHY shared: the first two already existed twice, and the escaping copies
 * had diverged. hero_detail.js escaped four characters; the event lineups
 * board escaped five (it also handles `'`, which matters the moment a value
 * lands in a single-quoted attribute). Two spellings of one *security* helper
 * is worse than two spellings of a formatter: a fix to either would never
 * reach the other, and nothing pointed either at its twin. The strict version
 * won.
 *
 * safeUrl joined them for the same reason, one wave later: it was the only
 * one of these that is purely a security control and the only one still
 * private to a single page script — so the board checked its icon URLs and
 * hero_detail.js, doing the structurally identical thing with the same field,
 * did not.
 */
(function () {
  "use strict";

  /**
   * Escape a value for interpolation into HTML — including into a
   * double- or single-quoted attribute.
   *
   * Not a substitute for `textContent`, which cannot inject at all and is
   * what a caller should reach for wherever a single node holds the text.
   * This is for the places that assemble nested markup by hand.
   *
   * @param {*} value anything; stringified first
   * @returns {string} the same text with & < > " ' replaced by entities
   */
  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * A same-origin path, or "" for anything else.
   *
   * Every URL that reaches this is a path: ensure_all_icons emits
   * /gear-icons/<id>.png, hero portraits are /static/heroes/<slug>.webp. So
   * refusing everything else costs nothing and leaves a rule that can be
   * stated in one line — which an earlier version could not: it rejected
   * "//host/x" as off-site while allowing "https://host/x", which is off-site
   * too.
   *
   * Both "//host/x" and "/\host/x" start with "/" and are why this is not
   * just `charAt(0) === "/"`: WHATWG parses a backslash in the authority of a
   * special scheme exactly like a slash, so both are protocol-relative URLs
   * wearing a path's clothes.
   *
   * The tab/LF/CR check is the same case one spelling further out. A browser
   * strips every ASCII tab, LF and CR from a URL *before* parsing it, so
   * "/\t/evil.example/x.png" is fetched as "//evil.example/x.png" — the exact
   * thing the line below rejects, smuggled past a `charAt(1)` that sees a tab
   * instead of a slash. Refusing the characters outright is safe: no icon
   * path this app generates contains one.
   *
   * This is an origin check, not an escaping one. What it returns still has
   * to be escaped before it reaches an attribute — see the board's
   * renderGearGrid.
   *
   * @param {*} u the candidate URL; falsy values yield ""
   * @returns {string} the same string if it is a plain same-origin path, else ""
   */
  function safeUrl(u) {
    if (!u) return "";
    var s = String(u);
    if (/[\t\n\r]/.test(s)) return "";
    if (s.charAt(0) !== "/") return "";
    if (s.charAt(1) === "/" || s.charAt(1) === "\\") return "";
    return s;
  }

  /**
   * Wire the three ways a dialog gets dismissed: its close button, a click
   * on the backdrop *itself*, and Escape.
   *
   * `ev.target === backdrop` is the load-bearing part — a click that bubbled
   * up from the panel must not dismiss the thing the user is reading — and it
   * is exactly the line that was duplicated. `close` is supplied by the
   * caller because the two dialogs hide themselves differently (one toggles
   * `hidden` alongside the class, one only sets `aria-hidden`); this owns the
   * triggers, not the hiding.
   *
   * @param {?Element} backdrop the full-screen dimmer
   * @param {?Element} closeButton the explicit close control, if there is one
   * @param {function(): void} close idempotent; called once per dismissal
   */
  function bindDialogDismiss(backdrop, closeButton, close) {
    if (closeButton) closeButton.addEventListener("click", close);
    if (backdrop) {
      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop) close();
      });
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") close();
    });
  }

  window.escapeHtml = esc;
  window.safeUrl = safeUrl;
  window.bindDialogDismiss = bindDialogDismiss;
})();

/**
 * Publishes window.detailOf — the one reading of FastAPI's error envelope.
 *
 * WHY shared: the JSON endpoints answer a failure with {"detail": "..."} and
 * the two optimiser screens both have to turn that into a line of prose. The
 * Gear XP planner unwrapped it; the lineup board did `res.text()` and put the
 * raw body on screen, so the first HTTPException /api/optimize ever raises
 * would have shown the user `{"detail":"..."}` braces and all. One rule now,
 * including the part that is easy to miss: FastAPI's *validation* 422s put a
 * list of objects in `detail`, and "[object Object]" is worse than useless.
 */
(function () {
  "use strict";

  /**
   * The server's own message when it sent a usable one.
   *
   * @param {*} data the parsed JSON body, or null when the body was not JSON
   *        (an unhandled exception answers with plain "Internal Server Error")
   * @param {string} fallback what to show otherwise — the caller's own
   *        phrasing, since only it knows which request failed
   * @returns {string} a line fit to put in front of a user
   */
  function detailOf(data, fallback) {
    var detail = data && data.detail;
    if (typeof detail === "string" && detail) return detail;
    return String(fallback);
  }

  window.detailOf = detailOf;
})();

/**
 * Publishes window.setStatusLine — the one-line `.status-line` region both
 * optimiser screens carry under their controls.
 *
 * WHY shared: it existed twice, with the arguments flipped. The lineup board
 * spelled it `setStatus(kind, text)` and the Gear XP planner
 * `setStatus(text, kind)` — the same two statements either way round. Both
 * parameters are strings and neither copy validated them, so calling one with
 * the other's order raised nothing at all: it just wrote the message into the
 * element's `class` and the state word into its text. One spelling, one
 * argument order, one place to fix.
 */
(function () {
  "use strict";

  /**
   * Write a status paragraph's text and its state class together.
   *
   * `.status-line` is always the first class, so the two are set in one
   * assignment rather than by toggling three mutually exclusive state
   * classes and hoping none is left behind.
   *
   * @param {?Element} el the status paragraph; a missing one is a no-op
   * @param {*} text the message; stringified
   * @param {string} [kind] "" | "ok" | "warn" | "err" — the state class
   */
  function setStatusLine(el, text, kind) {
    if (!el) return;
    el.className = "status-line" + (kind ? " " + kind : "");
    el.textContent = String(text);
  }

  window.setStatusLine = setStatusLine;
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
