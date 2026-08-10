/* Academy research — same bonus cards as Radiant opponent / player bonuses. */
(function () {
  "use strict";

  var B = window.OptimiserBoard;
  if (!B) return;

  var editEl = document.getElementById("research-bonus-edit");
  var saveBtn = document.getElementById("research-save");
  var statusEl = document.getElementById("research-status");
  var noteEl = document.getElementById("research-note");
  var initialEl = document.getElementById("research-initial");
  if (!editEl || !saveBtn) return;

  var LINES = [
    { id: "squad", label: "Squad (all troops)" },
    { id: "infantry", label: "Infantry" },
    { id: "cavalry", label: "Cavalry" },
    { id: "archers", label: "Archers" },
  ];

  function initialBonuses() {
    var raw = {};
    try {
      raw = JSON.parse((initialEl && initialEl.textContent) || "{}") || {};
    } catch (err) {
      raw = {};
    }
    var troops = raw.troops || {};
    return {
      squad: raw.squad || {},
      infantry: troops.infantry || {},
      cavalry: troops.cavalry || {},
      archers: troops.archers || {},
    };
  }

  B.fillBonusesInto(editEl, initialBonuses(), LINES);

  saveBtn.addEventListener("click", async function () {
    saveBtn.disabled = true;
    if (statusEl) statusEl.textContent = "Saving…";
    var cards = B.readBonusesFrom(editEl, LINES);
    var payload = {
      note: noteEl ? noteEl.value : "",
      squad: cards.squad || {},
      troops: {
        infantry: cards.infantry || {},
        cavalry: cards.cavalry || {},
        archers: cards.archers || {},
      },
    };
    try {
      var res = await fetch("/api/research", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      var body = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        if (statusEl) {
          statusEl.textContent = body.detail || ("Save failed: " + res.status);
        }
        saveBtn.disabled = false;
        return;
      }
      if (statusEl) statusEl.textContent = "Saved.";
      saveBtn.disabled = false;
    } catch (err) {
      if (statusEl) statusEl.textContent = String(err);
      saveBtn.disabled = false;
    }
  });
})();
