/* Shared expedition formation collapse: power is summed by callers;
 * Attack/Defense/Health/Lethality are troop-share weighted averages.
 *
 * Mirrors ks.heroes.optimize.stat_contributions.weighted_expedition_totals.
 */
(function (global) {
  "use strict";

  var EXPEDITION_STATS = ["Attack", "Defense", "Health", "Lethality"];

  function labelTroop(label) {
    var low = String(label).toLowerCase();
    if (low.indexOf("infantry") === 0) return "infantry";
    if (low.indexOf("cavalry") === 0) return "cavalry";
    if (low.indexOf("archer") === 0) return "archers";
    return null;
  }

  function labelStat(label) {
    var text = String(label);
    for (var i = 0; i < EXPEDITION_STATS.length; i++) {
      var stat = EXPEDITION_STATS[i];
      if (text === stat || text.slice(-(stat.length + 1)) === " " + stat) {
        return stat;
      }
    }
    return null;
  }

  function addShare(left, right) {
    left = left || { hero: 0, skills: 0, gear: 0 };
    right = right || { hero: 0, skills: 0, gear: 0 };
    var hero = Number(left.hero || 0) + Number(right.hero || 0);
    var skills = Number(left.skills || 0) + Number(right.skills || 0);
    var gear = Number(left.gear || 0) + Number(right.gear || 0);
    return { hero: hero, skills: skills, gear: gear, total: hero + skills + gear };
  }

  function scaleShare(share, weight) {
    share = share || { hero: 0, skills: 0, gear: 0 };
    var hero = weight * Number(share.hero || 0);
    var skills = weight * Number(share.skills || 0);
    var gear = weight * Number(share.gear || 0);
    return { hero: hero, skills: skills, gear: gear, total: hero + skills + gear };
  }

  function weightedExpeditionTotals(stats, troopShares) {
    stats = stats || {};
    var byTroop = {};
    var passthrough = {};
    Object.keys(stats).forEach(function (label) {
      var troop = labelTroop(label);
      var stat = labelStat(label);
      if (!stat) return;
      if (!troop) {
        passthrough[stat] = addShare(stats[label], null);
        return;
      }
      byTroop[troop] = byTroop[troop] || {};
      byTroop[troop][stat] = addShare(byTroop[troop][stat], stats[label]);
    });
    var troops = Object.keys(byTroop);
    if (!troops.length) return passthrough;

    var raw = {};
    var mass = 0;
    troops.forEach(function (troop) {
      var value =
        troopShares && troopShares[troop] != null
          ? Math.max(0, Number(troopShares[troop]))
          : 1;
      if (!isFinite(value)) value = 0;
      raw[troop] = value;
      mass += value;
    });
    if (mass <= 0) {
      troops.forEach(function (troop) {
        raw[troop] = 1;
      });
      mass = troops.length;
    }

    var out = {};
    EXPEDITION_STATS.forEach(function (stat) {
      var acc = { hero: 0, skills: 0, gear: 0, total: 0 };
      var seen = false;
      troops.forEach(function (troop) {
        var share = byTroop[troop][stat];
        if (!share) return;
        seen = true;
        acc = addShare(acc, scaleShare(share, raw[troop] / mass));
      });
      if (seen) out[stat] = acc;
    });
    return out;
  }

  global.weightedExpeditionTotals = weightedExpeditionTotals;
})(typeof window !== "undefined" ? window : globalThis);
