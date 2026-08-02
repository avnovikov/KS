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
    this.inputs = slice(tr.querySelectorAll("input.cell-input"));
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
   *  box is *not* unsendable — it is the row's "unknown" state. */
  function isUnsendable(input) {
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

  function applyServerRow(state, payload) {
    if (!payload) return;
    var power = payload.power;
    var cell = state.tr.querySelector(".power-cell");
    // Plain String(), not toLocaleString(): the server-rendered cell this
    // replaces is an ungrouped Jinja "{{ p.power }}", and a locale-grouped
    // replacement would change style the moment the user typed.
    if (cell) cell.textContent = power === null || power === undefined ? "—" : String(power);
    state.tr.dataset.power = power === null || power === undefined ? "" : String(power);
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
    if (body === state.lastSavedBody) return;

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
      refreshIncomplete(state);
      clearTrustFor(state.id);
      flashSaved(state);
    } catch (err) {
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

  /** "Needs attention" is the union of the two signals the user cares about:
   *  a flag from the last rescan (session-scoped, cleared as rows are
   *  reviewed) and an incompleteness the server computed from trust.py's own
   *  predicate — the latter so the chip still means something on a plain page
   *  load, long after any rescan payload is gone. */
  function needsAttention(state) {
    return !!state.tr.dataset.trust || state.tr.dataset.incomplete === "1";
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
  var NUMERIC_SORTS = { power: 1, enhancement: 1, mastery: 1, stars: 1, pellets: 1 };

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

  /* --- wiring --------------------------------------------------------------- */

  rows.forEach(function (state) {
    // Snapshot what the server rendered, so tabbing through the table without
    // changing anything never fires a PATCH.
    state.lastSavedBody = JSON.stringify(readRow(state));

    state.inputs.forEach(function (input) {
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
    th.addEventListener("click", function () {
      var key = th.dataset.sort;
      var dir = th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
      sortTable(key, dir);
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
