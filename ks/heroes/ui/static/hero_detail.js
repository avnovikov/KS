/* Hero detail sheet for /inventory/heroes.
 *
 * Split out of inventory_heroes.html's inline <script> so that page ships
 * pure markup, and kept out of inventory.js because none of it applies to the
 * gear table: this is a read-only GET /api/heroes/{name} view of stats and
 * skills, opened from the name/icon in the first column.
 */
(function () {
  "use strict";

  var modal = document.getElementById("hero-detail-modal");
  if (!modal) return;

  var iconEl = document.getElementById("hero-detail-icon");
  var titleEl = document.getElementById("hero-detail-title");
  var subEl = document.getElementById("hero-detail-sub");
  var bodyEl = document.getElementById("hero-detail-body");
  var closeBtn = document.getElementById("hero-detail-close");

  // The shared escaper from app.js, which _layout.html loads first. This
  // file used to carry its own four-character copy; the event lineups board
  // carried a five-character one. See app.js for why there is now one.
  var esc = window.escapeHtml;

  // …and the shared origin check, which this file was the one page script not
  // to apply. `hero.icon_url` here is the same field the board runs through
  // safeUrl before it builds a portrait, arriving from the same store.
  var safeUrl = window.safeUrl;

  function fmt(value) {
    return value === null || value === undefined || value === "" ? "—" : String(value);
  }

  function rarityClass(rarity) {
    return (rarity || "").toLowerCase();
  }

  function statsTable(title, obj) {
    var entries = Object.keys(obj || {});
    if (!entries.length) return "";
    var body = entries
      .map(function (key) {
        return "<tr><td>" + esc(key) + '</td><td class="fact-v">' + esc(obj[key]) + "</td></tr>";
      })
      .join("");
    return (
      '<h3 class="section-title">' +
      esc(title) +
      '</h3><table class="stat-table"><thead><tr><th>Stat</th><th>Value</th></tr></thead>' +
      "<tbody>" +
      body +
      "</tbody></table>"
    );
  }

  function skillsTable(skills) {
    if (!skills || !skills.length) {
      return '<h3 class="section-title">Skills</h3><p class="empty">No skills scraped.</p>';
    }
    var body = skills
      .map(function (skill) {
        var bonus = skill.current_bonus != null ? " · bonus " + skill.current_bonus : "";
        var desc = skill.description || skill.upgrade_preview || skill.raw_text || "";
        return (
          "<tr><td>" +
          esc(skill.slot) +
          "</td><td><strong>" +
          esc(skill.name || "—") +
          '</strong><div class="skill-desc">Lv ' +
          esc(fmt(skill.level)) +
          esc(bonus) +
          "</div>" +
          (desc ? '<div class="skill-desc">' + esc(desc) + "</div>" : "") +
          "</td></tr>"
        );
      })
      .join("");
    return (
      '<h3 class="section-title">Skills</h3>' +
      '<table class="skill-table"><thead><tr><th>Slot</th><th>Skill</th></tr></thead>' +
      "<tbody>" +
      body +
      "</tbody></table>"
    );
  }

  function renderHeroDetail(hero) {
    if (iconEl) {
      // The *checked* URL decides both the src and whether the <img> is shown
      // at all, so a rejected one leaves no broken frame behind.
      var iconSrc = safeUrl(hero.icon_url);
      iconEl.src = iconSrc;
      iconEl.className = "rarity-" + rarityClass(hero.rarity);
      iconEl.style.display = iconSrc ? "block" : "none";
    }
    if (titleEl) titleEl.textContent = hero.name || "Hero";
    if (subEl) {
      subEl.innerHTML =
        '<span class="rarity ' +
        esc(rarityClass(hero.rarity)) +
        '">' +
        esc(fmt(hero.rarity)) +
        "</span> · " +
        esc(fmt(hero.troop_type)) +
        " · " +
        esc(hero.stars == null ? 0 : hero.stars) +
        "★ + " +
        esc(hero.pellets == null ? 0 : hero.pellets) +
        "p";
    }

    var facts = [
      ["Power", hero.power],
      ["Level", hero.level],
      ["Escorts", hero.escorts],
      ["Stars", hero.stars],
      ["Pellets", hero.pellets],
      ["Roster", "p" + (hero.roster_page == null ? 0 : hero.roster_page) + " #" + (hero.roster_index == null ? 0 : hero.roster_index)],
      ["Scraped", hero.scraped_at],
    ];
    var eg = hero.exclusive_gear;
    if (eg && (eg.level || eg.widget_name)) {
      var egBits = [];
      if (eg.widget_name) egBits.push(eg.widget_name);
      if (eg.widget_type) egBits.push(eg.widget_type);
      if (eg.level != null) egBits.push("Lv " + eg.level + "/" + (eg.max_level == null ? 10 : eg.max_level));
      facts.splice(2, 0, ["Exclusive gear", egBits.join(" · ")]);
    }
    var factHtml = facts
      .map(function (pair) {
        return (
          '<div class="fact"><span class="fact-k">' +
          esc(pair[0]) +
          '</span><span class="fact-v">' +
          esc(fmt(pair[1])) +
          "</span></div>"
        );
      })
      .join("");

    var stats = hero.stats || {};
    if (bodyEl) {
      bodyEl.innerHTML =
        '<div class="fact-grid">' +
        factHtml +
        "</div>" +
        statsTable("Conquest", stats.conquest) +
        statsTable("Expedition", stats.expedition) +
        skillsTable(hero.skills);
    }
  }

  function openHeroModal(name) {
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    if (bodyEl) bodyEl.innerHTML = '<p class="empty">Loading ' + esc(name) + "…</p>";
    fetch("/api/heroes/" + encodeURIComponent(name))
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.detail || "Failed to load hero");
        renderHeroDetail(result.data.hero);
      })
      .catch(function (err) {
        if (bodyEl) bodyEl.innerHTML = '<p class="empty">' + esc(err.message || err) + "</p>";
      });
  }

  function closeHeroModal() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }

  // Close button + backdrop click + Escape, from app.js. closeHeroModal is
  // idempotent, so the old `contains("open")` guard on Escape is not needed.
  window.bindDialogDismiss(modal, closeBtn, closeHeroModal);

  Array.prototype.slice
    .call(document.querySelectorAll(".hero-open"))
    .forEach(function (el) {
      function open() {
        openHeroModal(el.dataset.name);
      }
      el.addEventListener("click", open);
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    });
})();
