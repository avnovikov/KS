/* Spreadsheet+ inventory table: filter chips, name search, sortable columns,
 * debounced per-row auto-save, and the post-rescan trust cues.
 *
 * One script serves both /inventory/gear and /inventory/heroes. Everything
 * that differs between them is declared in the markup — the table's
 * data-inventory-kind / data-patch-base / data-payload-key, each row's
 * data-row-id, and each editable cell's data-field / data-blank / data-required
 * — because the two pages previously carried near-identical inline copies of
 * the sort logic and of showToast, and the copies had already drifted.
 *
 * Auto-save semantics, and why:
 *
 *   - Typing schedules a PATCH 400ms later; blurring saves immediately. Both
 *     send the row's *whole* editable state, so what the server holds for a
 *     row is always exactly what that row shows.
 *   - A half-typed value is a real value: "12" is a valid prefix of "125", so
 *     a slow typist can persist 12 on the way to 125. That is harmless here —
 *     gear power is recomputed from (rarity, enhancement, mastery) on every
 *     PATCH rather than accumulated — and the final keystroke always wins.
 *   - While a box is empty or holds text the browser refused to parse, no
 *     request is scheduled at all: a blank numeric input serializes to null,
 *     and PATCH /api/gear rejects that. An empty box commits on *blur*, as an
 *     explicit "OCR could not read this" (clear_enhancement / clear_mastery
 *     for gear, a JSON null for heroes stars/pellets) — so blank is stored as
 *     blank rather than silently diverging from the number still on disk.
 *   - A value outside the column's min/max never leaves the page; the field is
 *     flagged and the toast names it.
 *
 * The in-flight check runs *before* the dedupe check, and that order is load
 * bearing — see save().
 *
 * Two editable control shapes, not one: `input.cell-input` for the numeric
 * columns and `select.cell-input` for gear's fixed rarity/slot vocabularies.
 * A select has no half-typed state, so it commits on `change` (still through
 * the same debounce, so flicking through options coalesces) and is never
 * "unsendable" — the option set is server-rendered from the vocabulary the
 * PATCH endpoint validates against.
 *
 * The pin (`td.lock-cell[data-locked]`) is the visible half of the store's
 * lock model: for gear slot/rarity/enhancement/mastery and hero level, the
 * store treats *any stored non-null value* as immune to OCR rescans, and
 * emptying the field is the only way to release it. So `data-locked` tracks
 * what the server echoed back, never what the box shows — a clear the server
 * rejected must leave the pin exactly where it was.
 */
(function () {
  "use strict";

  var table = document.getElementById("inventory-table");
  if (!table) return;

  var KIND = table.dataset.inventoryKind; // "gear" | "heroes"
  var PATCH_BASE = table.dataset.patchBase; // "/api/gear/" | "/api/heroes/"
  var PAYLOAD_KEY = table.dataset.payloadKey; // "piece" | "hero"
  var DEBOUNCE_MS = 400;
  var FLASH_MS = 900;

  var tbody = table.querySelector("tbody");
  var banner = document.getElementById("trust-banner");
  var summaryEl = document.getElementById("trust-summary");
  var markReviewedBtn = document.getElementById("mark-reviewed");
  var chipsEl = document.getElementById("filter-chips");
  var searchEl = document.getElementById("row-search");
  var countEl = document.getElementById("row-count");
  var noMatchesEl = document.getElementById("no-matches");

  function slice(list) {
    return Array.prototype.slice.call(list);
  }

  /** Per-row save state. One state machine per row, not one per table: two
   *  rows can be saving at once without either queueing behind the other. */
  function RowState(tr) {
    this.tr = tr;
    this.id = tr.dataset.rowId;
    // Both control shapes, in document order: `.cell-input` rather than
    // `input.cell-input`, or the gear rarity/slot selects would be edited on
    // screen and never sent.
    this.inputs = slice(tr.querySelectorAll(".cell-input"));
    this.timer = null;
    this.flashTimer = null;
    this.saving = false;
    this.queued = false;
    this.lastSavedBody = null;
  }

  var rows = slice(table.querySelectorAll("tbody tr")).map(function (tr) {
    return new RowState(tr);
  });
  var byId = {};
  rows.forEach(function (state) {
    byId[state.id] = state;
  });
  var headers = slice(table.querySelectorAll("th.sortable"));

  /* --- reading a row -------------------------------------------------------- */

  /** A fixed-vocabulary picker rather than a typed box. */
  function isPicker(control) {
    return control.tagName === "SELECT";
  }

  /** True when the box is empty, as opposed to holding text the browser
   *  refused to parse (which also reads as "" but sets badInput). */
  function isBlank(input) {
    if (input.validity && input.validity.badInput) return false;
    return String(input.value).trim() === "";
  }

  /** In-range non-negative integer, or null when the value cannot be sent. */
  function readInt(input) {
    if (input.validity && input.validity.badInput) return null;
    var raw = String(input.value).trim();
    if (raw === "") return null; // blank is handled by the caller, not here
    if (!/^\d+$/.test(raw)) return null; // no signs, decimals, exponents
    var value = Number(raw);
    if (!Number.isSafeInteger(value)) return null;
    var max = input.getAttribute("max");
    if (max !== null && value > Number(max)) return null;
    var min = input.getAttribute("min");
    if (min !== null && value < Number(min)) return null;
    return value;
  }

  /** True when this box holds something that cannot be sent at all. A blank
   *  box is *not* unsendable — it is the row's "unknown" state.
   *
   *  A picker never is: its options are server-rendered from the same
   *  vocabulary the PATCH endpoint validates against, and readInt() would
   *  reject every one of them for not being a number. */
  function isUnsendable(input) {
    if (isPicker(input)) return false;
    return !isBlank(input) && readInt(input) === null;
  }

  /**
   * Build the PATCH body for one row from what its boxes currently show.
   * Callers validate first (see save()); an unsendable box is omitted here
   * rather than serialized as undefined.
   * @returns {Object} the JSON body for PATCH {patch_base}{row id}
   */
  function readRow(state) {
    var body = {};
    state.inputs.forEach(function (input) {
      var field = input.dataset.field;
      if (isBlank(input)) {
        var blank = input.dataset.blank;
        // No data-blank at all means "omit the field", which both PATCH
        // endpoints read as "leave whatever is stored alone".
        if (blank === "null") body[field] = null;
        else if (blank) body[blank] = true;
        return;
      }
      if (isPicker(input)) {
        body[field] = String(input.value);
        return;
      }
      var value = readInt(input);
      if (value !== null) body[field] = value;
    });
    return body;
  }

  /* --- feedback ------------------------------------------------------------- */

  function toast(message, ok) {
    if (typeof window.showToast === "function") window.showToast(message, ok);
    else if (!ok) console.error(message);
  }

  function markValidity(input, ok) {
    input.classList.toggle("invalid", !ok);
    if (ok) input.removeAttribute("aria-invalid");
    else input.setAttribute("aria-invalid", "true");
  }

  function invalidMessage(input) {
    var label = input.dataset.label || input.dataset.field;
    var min = input.getAttribute("min") || "0";
    var max = input.getAttribute("max");
    if (max !== null) {
      return label + " must be a whole number from " + min + " to " + max;
    }
    return label + " must be a whole number, " + min + " or more";
  }

  /** Mark the row as holding something the store does not.
   *
   *  This is the only lasting trace of a failed write. The toast carrying the
   *  server's reason times out; the per-row Save button that used to keep the
   *  user's attention on the row is gone; and `blur` will not fire again on a
   *  field they have already left, so nothing retries by itself. Without this
   *  the box would sit there showing a value the store never accepted.
   *
   *  Cleared only by a save for this row that actually succeeds — not by the
   *  next keystroke, which is why it lives on the row rather than riding along
   *  with markValidity()'s per-input flag (that one deliberately clears as
   *  soon as the user starts fixing things, so the page never nags mid-typing).
   */
  function markRowUnsaved(state, origin) {
    state.tr.dataset.unsaved = "1";
    if (origin) markValidity(origin, false);
  }

  /** Brief per-row confirmation. Auto-save fires constantly, so a toast on
   *  every success would bury the error toasts that actually need reading. */
  function flashSaved(state) {
    state.tr.classList.add("row-saved");
    clearTimeout(state.flashTimer);
    state.flashTimer = setTimeout(function () {
      state.flashTimer = null;
      state.tr.classList.remove("row-saved");
    }, FLASH_MS);
  }

  /* --- trust cues ----------------------------------------------------------- */

  /* The live payload for this page: `null` once every flagged row has been
   * reviewed. Kept in step with sessionStorage rather than only with the DOM,
   * because both inventory pages reload after a rescan and a DOM-only clear
   * would resurrect every flag on the next render. */
  var trust = null;

  function countFlags(flags) {
    var counts = { new: 0, changed: 0, incomplete: 0 };
    Object.keys(flags).forEach(function (key) {
      var flag = flags[key];
      if (counts[flag] !== undefined) counts[flag] += 1;
    });
    return counts;
  }

  function persistTrust() {
    if (!window.HeroesTrust) return;
    var flags = trust ? trust.flags : {};
    if (!Object.keys(flags).length) {
      trust = null;
      window.HeroesTrust.clear(KIND);
      return;
    }
    var counts = countFlags(flags);
    // storedAt is refreshed by save(); nothing reads it, and re-deriving the
    // counts here keeps them tallying the map even after rows drop out.
    window.HeroesTrust.save(KIND, {
      flags: flags,
      new: counts.new,
      changed: counts.changed,
      incomplete: counts.incomplete,
    });
  }

  function renderBanner() {
    if (!banner) return;
    var flags = trust ? trust.flags : {};
    var keys = Object.keys(flags);
    if (!keys.length) {
      banner.hidden = true;
      if (summaryEl) summaryEl.textContent = "";
      return;
    }
    var counts = countFlags(flags);
    var parts = [];
    if (counts.new) parts.push(counts.new + " new");
    if (counts.changed) parts.push(counts.changed + " changed");
    if (counts.incomplete) parts.push(counts.incomplete + " incomplete");
    // Un-hide before writing, for the same reason app.js's toast does: a
    // screen reader routinely misses a mutation to a display:none live region.
    banner.hidden = false;
    if (summaryEl) {
      summaryEl.textContent =
        "Since the last rescan: " +
        parts.join(" · ") +
        ". Spot-check these rows against the game — editing one clears its mark.";
    }
  }

  function paintTrustRows() {
    rows.forEach(function (state) {
      var flag = trust && trust.flags[state.id];
      if (flag) state.tr.dataset.trust = flag;
      else delete state.tr.dataset.trust;
    });
  }

  function loadTrust() {
    if (!window.HeroesTrust) return;
    var payload = window.HeroesTrust.load(KIND);
    var stored = (payload && payload.flags) || {};
    var storedKeys = Object.keys(stored);
    if (!storedKeys.length) return;
    // Drop flags for rows this render does not have. A piece that vanished in
    // the rescan can never be reviewed, so leaving it in would pin the banner
    // open forever and make the counts describe rows nobody can see.
    var flags = {};
    storedKeys.forEach(function (key) {
      if (byId[key]) flags[key] = stored[key];
    });
    trust = Object.keys(flags).length ? { flags: flags } : null;
    if (!trust) window.HeroesTrust.clear(KIND);
  }

  /** Drop one row's flag from the DOM *and* from storage. */
  function clearTrustFor(id) {
    if (!trust || !trust.flags[id]) return;
    delete trust.flags[id];
    if (byId[id]) delete byId[id].tr.dataset.trust;
    persistTrust();
    renderBanner();
  }

  function markAllReviewed() {
    trust = null;
    paintTrustRows();
    if (window.HeroesTrust) window.HeroesTrust.clear(KIND);
    renderBanner();
  }

  /** Re-derive "this row is missing data" from the boxes on screen.
   *
   *  Which boxes count is decided server-side (`data-required`, set from
   *  trust.py's own rarity gate), so the browser never carries a second copy
   *  of that table. `data-incomplete-locked` marks an incompleteness nothing
   *  on this page can fix — a hero with no power — which must survive an edit
   *  to the fields that *are* editable.
   */
  function refreshIncomplete(state) {
    if (state.tr.dataset.incompleteLocked === "1") return;
    var missing = false;
    state.inputs.forEach(function (input) {
      if (input.dataset.required === undefined) return;
      if (isBlank(input)) missing = true;
    });
    if (missing) state.tr.dataset.incomplete = "1";
    else delete state.tr.dataset.incomplete;
  }

  /* --- saving --------------------------------------------------------------- */

  function cancelPending(state) {
    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
  }

  function schedule(state) {
    cancelPending(state);
    state.timer = setTimeout(function () {
      state.timer = null;
      save(state);
    }, DEBOUNCE_MS);
  }

  /**
   * Repaint each pin from what the store now holds.
   *
   * There is no lock flag anywhere: GearStore and HeroStore treat *any*
   * stored non-null value on their locked fields as immune to a rescan, so
   * the pin's predicate is literally `payload[field] !== null`. It is read
   * off the server's echoed record and never off the box, because those two
   * disagree exactly when it matters — a clear the store refused has to
   * leave the pin showing, or the page would promise a release that never
   * happened.
   *
   * A field the response does not carry is left alone rather than treated as
   * released: absent is not the same as null.
   */
  function syncLocks(state, payload) {
    state.inputs.forEach(function (input) {
      if (input.dataset.lockable === undefined) return;
      var field = input.dataset.field;
      if (!Object.prototype.hasOwnProperty.call(payload, field)) return;
      var cell = input.closest("td");
      if (!cell) return;
      var stored = payload[field];
      if (stored === null || stored === undefined || stored === "") {
        delete cell.dataset.locked;
      } else {
        cell.dataset.locked = "1";
      }
    });
  }

  function applyServerRow(state, payload) {
    if (!payload) return;
    syncLocks(state, payload);
    var power = payload.power;
    var powerStr = power === null || power === undefined ? "" : String(power);
    var powerInput = state.tr.querySelector("input[data-field=power]");
    if (powerInput) {
      // Power is now an editable input; update its value from the server
      // response (e.g. rescaled after a star edit) so the box stays in
      // step. Plain String(), not toLocaleString() — the box value must
      // round-trip through readInt() unchanged.
      powerInput.value = powerStr;
    } else {
      // Gear rows or legacy pages: update the text cell as before.
      var cell = state.tr.querySelector(".power-cell");
      if (cell) cell.textContent = powerStr || "—";
    }
    state.tr.dataset.power = powerStr;

    if (KIND === "heroes") {
      var eg = payload.exclusive_gear;
      var widgetLevel =
        eg && eg.level !== null && eg.level !== undefined ? String(eg.level) : "";
      state.tr.dataset.widget_level = widgetLevel;
    }

    if (payload.assurance) {
      ["power", "stars", "level", "pellets"].forEach(function (field) {
        var assur = payload.assurance[field];
        var input = state.tr.querySelector("input[data-field=" + field + "]");
        if (!input) return;
        var td = input.closest("td");
        if (!td) return;
        if (assur) {
          td.dataset.assurance = assur.level;
          td.title = assur.reason || "";
        } else {
          delete td.dataset.assurance;
          td.title = "";
        }
      });
    }
  }

  /* The rarity column has been colour-coded since before this rewrite; the
   * picker that replaced the static cell keeps that, repainted as the user
   * changes it. Only the six canonical values can be chosen, and app.css
   * folds each store alias onto one of them. */
  var RARITY_TINTS = ["grey", "green", "blue", "epic", "mythic", "red"];

  function paintRarity(control) {
    if (control.dataset.rarityTint === undefined) return;
    RARITY_TINTS.forEach(function (name) {
      control.classList.remove(name);
    });
    var value = String(control.value).trim().toLowerCase();
    if (value) control.classList.add(value);
  }

  /** Keep the sortable column's dataset in step with the box above it, so a
   *  re-sort after an edit orders by what is on screen. */
  function syncSortKey(input) {
    var key = input.dataset.sortKey;
    if (!key) return;
    var tr = input.closest("tr");
    if (tr) tr.dataset[key] = String(input.value).trim();
  }

  async function save(state, origin) {
    cancelPending(state);
    // Flag *every* offending box, not only the one that gets named: with two
    // editable columns per row the other one would otherwise stay unmarked
    // and look fine.
    var bad = state.inputs.filter(function (input) {
      var ok = !isUnsendable(input);
      markValidity(input, ok);
      return !ok;
    });
    if (bad.length) {
      // Name the box the user just left when it is itself an offender —
      // otherwise the first one found, which may be a column they never
      // touched.
      var culprit = origin && bad.indexOf(origin) !== -1 ? origin : bad[0];
      // Nothing was sent, so the row is out of step with the store just as
      // surely as if the server had rejected it.
      markRowUnsaved(state);
      toast(invalidMessage(culprit), false);
      return;
    }

    // Order matters: in-flight *before* dedupe. lastSavedBody is only
    // refreshed when a PATCH succeeds, so while one is in flight it still
    // describes the pre-save row. Deduping first would drop an edit that
    // reverts the row back to that stale value (type A, blur, type the old
    // value back, blur) — the in-flight PATCH would then land and record the
    // value the user had just undone, leaving the row showing one number and
    // the store holding another. Queueing instead re-runs save() once
    // lastSavedBody finally describes the truth.
    if (state.saving) {
      state.queued = true;
      return;
    }

    var body = JSON.stringify(readRow(state));
    if (body === state.lastSavedBody) {
      // Nothing to send — and this is also how a divergence *ends*. The row
      // now serializes to exactly what the server last confirmed, so whatever
      // made it diverge has been undone: typing 999, being told it is out of
      // range, and putting the old number back is the normal recovery for
      // both paths that set this mark. Nothing is sent, so the success path
      // below never runs and this is the only place that can notice. Leaving
      // it set would strand the row pink and pinned in "Needs attention"
      // until a reload — a permanently stuck false error on a page whose
      // whole job is trust signalling, worse than the toast it replaced.
      delete state.tr.dataset.unsaved;
      return;
    }

    state.saving = true;
    try {
      var res = await fetch(PATCH_BASE + encodeURIComponent(state.id), {
        method: "PATCH",
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
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      state.lastSavedBody = body;
      // Only non-editable cells are written back from the response. Copying
      // the server's values into the boxes would clobber whatever the user
      // typed while this request was in the air.
      applyServerRow(state, data[PAYLOAD_KEY]);
      delete state.tr.dataset.unsaved; // screen and store agree again
      refreshIncomplete(state);
      clearTrustFor(state.id);
      flashSaved(state);
    } catch (err) {
      markRowUnsaved(state, origin);
      toast(String((err && err.message) || err), false);
    } finally {
      state.saving = false;
      if (state.queued) {
        state.queued = false;
        save(state);
      }
    }
  }

  /* --- filtering ------------------------------------------------------------ */

  var activeFilter = "all";
  var searchTerm = "";

  /** "Needs attention" is the union of the signals the user cares about: a
   *  flag from the last rescan (session-scoped, cleared as rows are
   *  reviewed), an incompleteness the server computed from trust.py's own
   *  predicate (so the chip still means something on a plain page load, long
   *  after any rescan payload is gone), and a row whose last save was
   *  rejected — which is how a failed write stays findable once its toast
   *  has gone. */
  function needsAttention(state) {
    return (
      !!state.tr.dataset.trust ||
      state.tr.dataset.incomplete === "1" ||
      state.tr.dataset.unsaved === "1"
    );
  }

  function matches(state) {
    var tr = state.tr;
    if (activeFilter === "attention") {
      if (!needsAttention(state)) return false;
    } else if (activeFilter.indexOf("troop:") === 0) {
      if ((tr.dataset.troop || "") !== activeFilter.slice("troop:".length)) return false;
    }
    if (searchTerm) {
      if ((tr.dataset.name || "").toLowerCase().indexOf(searchTerm) === -1) return false;
    }
    return true;
  }

  function applyFilters() {
    var shown = 0;
    rows.forEach(function (state) {
      var ok = matches(state);
      state.tr.hidden = !ok;
      if (ok) shown += 1;
    });
    // "No rows match this filter" is a lie on an inventory that is simply
    // empty — there is nothing to filter yet, so say nothing.
    if (noMatchesEl) noMatchesEl.hidden = shown !== 0 || rows.length === 0;
    if (countEl) {
      countEl.textContent =
        shown === rows.length ? "" : shown + " of " + rows.length + " shown";
    }
  }

  /* --- sorting -------------------------------------------------------------- */

  /* One rank table, not one per page: the gear and heroes copies had already
   * drifted (only the heroes one knew about "legendary"). Ranks a table never
   * uses are inert. */
  var RARITY_RANK = {
    legendary: 6,
    mythic: 5,
    gold: 5,
    red: 5,
    epic: 4,
    purple: 4,
    rare: 3,
    blue: 3,
    uncommon: 2,
    green: 2,
    common: 1,
    grey: 1,
    gray: 1,
    white: 1,
  };
  var SLOT_RANK = { helmet: 1, helm: 1, chest: 2, gloves: 3, boots: 4 };
  var TROOP_RANK = { infantry: 1, cavalry: 2, archers: 3, archer: 3 };
  var NUMERIC_SORTS = {
    power: 1,
    enhancement: 1,
    mastery: 1,
    level: 1,
    stars: 1,
    pellets: 1,
    widget_level: 1,
  };

  function sortValue(tr, key) {
    var raw = tr.dataset[key] || "";
    if (NUMERIC_SORTS[key]) {
      if (raw === "") return -1; // unknown sorts below every real value
      var n = Number(raw);
      return Number.isFinite(n) ? n : -1;
    }
    if (key === "rarity") return RARITY_RANK[raw] || 0;
    if (key === "slot") return SLOT_RANK[raw] || 99;
    if (key === "troop") return TROOP_RANK[raw] || 99;
    if (key === "name") return raw.toLowerCase();
    return raw;
  }

  function sortTable(key, dir) {
    var mult = dir === "asc" ? 1 : -1;
    var ordered = rows.slice().sort(function (a, b) {
      var va = sortValue(a.tr, key);
      var vb = sortValue(b.tr, key);
      if (va < vb) return -1 * mult;
      if (va > vb) return 1 * mult;
      return String(a.id).localeCompare(String(b.id));
    });
    ordered.forEach(function (state) {
      tbody.appendChild(state.tr);
    });
    headers.forEach(function (th) {
      if (th.dataset.sort === key) {
        th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      } else {
        th.removeAttribute("aria-sort");
      }
    });
  }

  /* --- rescan --------------------------------------------------------------- */

  async function purgeCaches() {
    if (typeof caches === "undefined") return;
    try {
      var keys = await caches.keys();
      await Promise.all(
        keys.map(function (key) {
          return caches.delete(key);
        })
      );
    } catch (_) {
      /* a stale icon is not worth failing the rescan over */
    }
  }

  function wireRescan() {
    var btn = document.getElementById("rescan-btn");
    if (!btn || !btn.dataset.rescanUrl) return;
    btn.addEventListener("click", async function () {
      if (btn.disabled) return;
      var confirmText = btn.dataset.rescanConfirm;
      if (confirmText && !window.confirm(confirmText)) return;
      var label = btn.textContent;
      btn.disabled = true;
      btn.classList.add("busy");
      btn.textContent = "Scanning…";
      if (btn.dataset.rescanNote) toast(btn.dataset.rescanNote, true);
      try {
        var res = await fetch(btn.dataset.rescanUrl, {
          method: "POST",
          cache: "no-store",
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
        // Persist the trust payload *before* navigating: the reload below
        // discards every JS variable on this page, which is the entire
        // reason HeroesTrust puts it in sessionStorage.
        if (data.trust && window.HeroesTrust) {
          window.HeroesTrust.save(KIND, data.trust);
        }
        toast("Rescan done · " + (data.count == null ? 0 : data.count) + " rows", true);
        await purgeCaches();
        var bust = data.cache_bust || String(Date.now());
        var target = btn.dataset.reloadUrl || "";
        window.location.replace(target + "?v=" + encodeURIComponent(bust));
      } catch (err) {
        toast(String((err && err.message) || err), false);
        btn.disabled = false;
        btn.classList.remove("busy");
        btn.textContent = label;
      }
    });
  }

  /* --- removing a piece ----------------------------------------------------- */

  /** Take a deleted row out of everything that still refers to it.
   *
   *  Not only the DOM: `rows` drives the filter counts and `byId` the trust
   *  bookkeeping, so a row left in either would keep a piece that no longer
   *  exists inside "2 of 3 shown" and could keep its flag pinning the banner
   *  open with nothing on screen to review. */
  function dropRow(state) {
    cancelPending(state);
    clearTimeout(state.flashTimer);
    clearTrustFor(state.id); // needs byId[state.id], so before the delete
    var at = rows.indexOf(state);
    if (at !== -1) rows.splice(at, 1);
    delete byId[state.id];
    state.tr.remove();
  }

  /**
   * The consume/delete path: irreversible, so it is deliberately two taps
   * apart and the first one is inert.
   *
   * The per-row button only *arms* the dialog — it never issues a request —
   * and the dialog names the piece before offering the destructive button.
   * `armed` is cleared by every exit (Cancel, backdrop, Escape, and the
   * delete itself), so a stray tap on a confirm button belonging to no open
   * dialog deletes nothing; the button is disabled while the request is in
   * flight, so an impatient double-tap sends one DELETE.
   */
  function wireRemoval() {
    var dialog = document.getElementById("remove-dialog");
    var confirmBtn = document.getElementById("remove-confirm");
    var cancelBtn = document.getElementById("remove-cancel");
    var targetEl = document.getElementById("remove-target");
    var buttons = slice(table.querySelectorAll("button.btn-remove"));
    // The heroes table has neither, and nothing on it is deletable.
    if (!dialog || !confirmBtn || !buttons.length) return;

    var armed = null;

    function close() {
      armed = null;
      dialog.classList.remove("open");
      dialog.setAttribute("aria-hidden", "true");
      confirmBtn.disabled = false;
    }

    function arm(state, name) {
      armed = { state: state, name: name };
      if (targetEl) targetEl.textContent = name;
      confirmBtn.disabled = false;
      dialog.classList.add("open");
      dialog.setAttribute("aria-hidden", "false");
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var state = byId[btn.dataset.removeId];
        if (!state) return;
        arm(state, btn.dataset.removeName || btn.dataset.removeId);
      });
    });

    // Cancel button, a click on the backdrop itself, and Escape — the same
    // three exits the hero detail sheet has, from app.js's one copy.
    window.bindDialogDismiss(dialog, cancelBtn, close);

    confirmBtn.addEventListener("click", async function () {
      if (!armed || confirmBtn.disabled) return;
      var target = armed;
      confirmBtn.disabled = true;
      try {
        // Same resource path the row PATCHes, different verb.
        var res = await fetch(PATCH_BASE + encodeURIComponent(target.state.id), {
          method: "DELETE",
          cache: "no-store",
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
        dropRow(target.state);
        applyFilters();
        close();
        toast("Removed " + target.name, true);
      } catch (err) {
        // Left open, still naming the piece: the user can retry or back out,
        // rather than being dropped onto a table that still shows a row they
        // were told nothing about.
        confirmBtn.disabled = false;
        toast(String((err && err.message) || err), false);
      }
    });
  }

  function wireAddGear() {
    var openBtn = document.getElementById("add-gear-btn");
    var dialog = document.getElementById("add-gear-dialog");
    var confirmBtn = document.getElementById("add-gear-confirm");
    var cancelBtn = document.getElementById("add-gear-cancel");
    var troopEl = document.getElementById("add-gear-troop");
    var slotEl = document.getElementById("add-gear-slot");
    var rarityEl = document.getElementById("add-gear-rarity");
    var errEl = document.getElementById("add-gear-error");
    if (!openBtn || !dialog || !confirmBtn || !troopEl || !slotEl || !rarityEl) {
      return;
    }

    function close() {
      dialog.classList.remove("open");
      dialog.setAttribute("aria-hidden", "true");
      confirmBtn.disabled = false;
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
    }

    function open() {
      confirmBtn.disabled = false;
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
      dialog.classList.add("open");
      dialog.setAttribute("aria-hidden", "false");
    }

    openBtn.addEventListener("click", open);
    window.bindDialogDismiss(dialog, cancelBtn, close);

    confirmBtn.addEventListener("click", async function () {
      if (confirmBtn.disabled) return;
      confirmBtn.disabled = true;
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
      try {
        var res = await fetch("/api/gear", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
          body: JSON.stringify({
            troop_type: troopEl.value,
            slot: slotEl.value,
            rarity: rarityEl.value,
          }),
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
        var name = (data.piece && data.piece.name) || "piece";
        close();
        toast("Added " + name, true);
        window.location.reload();
      } catch (err) {
        confirmBtn.disabled = false;
        var msg = String((err && err.message) || err);
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = msg;
        }
        toast(msg, false);
      }
    });
  }

  function wireAddHero() {
    var openBtn = document.getElementById("add-hero-btn");
    var dialog = document.getElementById("add-hero-dialog");
    var confirmBtn = document.getElementById("add-hero-confirm");
    var cancelBtn = document.getElementById("add-hero-cancel");
    var nameEl = document.getElementById("add-hero-name");
    var metaEl = document.getElementById("add-hero-meta");
    var errEl = document.getElementById("add-hero-error");
    if (!openBtn || !dialog || !confirmBtn || !nameEl) {
      return;
    }

    function syncMeta() {
      if (!metaEl) return;
      var opt = nameEl.options[nameEl.selectedIndex];
      if (!opt) {
        metaEl.textContent = "No catalog heroes left to add.";
        return;
      }
      var troop = opt.getAttribute("data-troop") || "—";
      var rarity = opt.getAttribute("data-rarity") || "—";
      metaEl.textContent = troop + " · " + rarity;
    }

    function close() {
      dialog.classList.remove("open");
      dialog.setAttribute("aria-hidden", "true");
      if (!confirmBtn.disabled || nameEl.options.length) {
        confirmBtn.disabled = nameEl.options.length === 0;
      }
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
    }

    function open() {
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
      syncMeta();
      dialog.classList.add("open");
      dialog.setAttribute("aria-hidden", "false");
    }

    nameEl.addEventListener("change", syncMeta);
    openBtn.addEventListener("click", open);
    window.bindDialogDismiss(dialog, cancelBtn, close);

    confirmBtn.addEventListener("click", async function () {
      if (confirmBtn.disabled) return;
      confirmBtn.disabled = true;
      if (errEl) {
        errEl.hidden = true;
        errEl.textContent = "";
      }
      try {
        var res = await fetch("/api/heroes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
          body: JSON.stringify({ name: nameEl.value }),
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
        var name = (data.hero && data.hero.name) || "hero";
        close();
        toast("Added " + name, true);
        window.location.reload();
      } catch (err) {
        confirmBtn.disabled = false;
        var msg = String((err && err.message) || err);
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = msg;
        }
        toast(msg, false);
      }
    });
  }

  /* --- wiring --------------------------------------------------------------- */

  rows.forEach(function (state) {
    // Snapshot what the server rendered, so tabbing through the table without
    // changing anything never fires a PATCH.
    state.lastSavedBody = JSON.stringify(readRow(state));

    state.inputs.forEach(function (input) {
      if (isPicker(input)) {
        // A picker has no half-typed state, so every value it can hold is
        // sendable — *including* the blank one, which is the release control
        // and must reach the server rather than waiting for a blur that
        // never comes on a tap-and-look-away. Still debounced, so flicking
        // through options coalesces into one PATCH.
        input.addEventListener("change", function () {
          syncSortKey(input);
          paintRarity(input);
          schedule(state);
        });
        input.addEventListener("blur", function () {
          save(state, input);
        });
        return;
      }

      input.addEventListener("input", function () {
        markValidity(input, true); // never nag mid-typing
        syncSortKey(input);
        if (isBlank(input) || readInt(input) === null) {
          // An empty (or unparseable) box must not fire a failing PATCH.
          // Blank commits on blur instead, where it is unambiguous.
          cancelPending(state);
          return;
        }
        schedule(state);
      });

      input.addEventListener("blur", function () {
        save(state, input);
      });
    });
  });

  headers.forEach(function (th) {
    function toggleSort() {
      var key = th.dataset.sort;
      var dir = th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
      sortTable(key, dir);
    }
    th.addEventListener("click", toggleSort);
    // The template gives these tabindex="0"; a <th> has no built-in
    // activation behaviour, so Enter/Space have to be wired by hand. They
    // stay columnheaders rather than becoming role="button", because
    // aria-sort is only meaningful on a columnheader.
    th.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault(); // Space would otherwise scroll the page
        toggleSort();
      }
    });
  });

  if (chipsEl) {
    slice(chipsEl.querySelectorAll(".chip")).forEach(function (chip) {
      chip.addEventListener("click", function () {
        activeFilter = chip.dataset.filter;
        slice(chipsEl.querySelectorAll(".chip")).forEach(function (other) {
          var on = other === chip;
          other.classList.toggle("on", on);
          other.setAttribute("aria-pressed", on ? "true" : "false");
        });
        applyFilters();
      });
    });
  }

  if (searchEl) {
    searchEl.addEventListener("input", function () {
      searchTerm = String(searchEl.value).trim().toLowerCase();
      applyFilters();
    });
  }

  if (markReviewedBtn) {
    markReviewedBtn.addEventListener("click", markAllReviewed);
  }

  wireRescan();
  wireRemoval();
  wireAddGear();
  wireAddHero();

  loadTrust();
  paintTrustRows();
  renderBanner();
  applyFilters();

  window.addEventListener("pagehide", function () {
    rows.forEach(function (state) {
      if (state.timer) save(state);
    });
  });
})();
