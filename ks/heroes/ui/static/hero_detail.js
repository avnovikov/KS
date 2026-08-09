/* Hero detail sheet for /inventory/heroes.
 *
 * Catalog-backed skill grid (2 columns) with level 1–5 controls that overwrite
 * OCR skill rows via PATCH /api/heroes/{name}/skills.
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

  var esc = window.escapeHtml;
  var safeUrl = window.safeUrl;

  var currentHero = null;
  var catalogSkills = [];
  var levelBySlot = {};
  var saving = false;

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

  function syncLevelsFromHero(hero) {
    levelBySlot = {};
    (hero.skills || []).forEach(function (s) {
      if (s && s.level != null) levelBySlot[String(s.slot)] = Number(s.level);
    });
  }

  function skillsPayload() {
    return catalogSkills.map(function (cs) {
      var level = levelBySlot[String(cs.slot)];
      if (level == null) level = 1;
      return { slot: cs.slot, name: cs.name, level: level };
    });
  }

  function skillsEditorHtml() {
    if (!catalogSkills.length) {
      return '<h3 class="section-title">Skills</h3><p class="empty">No catalog skills for this hero.</p>';
    }
    var cards = catalogSkills
      .map(function (cs) {
        var level = levelBySlot[String(cs.slot)];
        var levelLabel = level == null ? "—" : String(level);
        return (
          '<article class="skill-card" data-slot="' +
          esc(cs.slot) +
          '">' +
          "<h4>" +
          esc(cs.name) +
          "</h4>" +
          '<p class="muted">' +
          esc(cs.family) +
          (cs.effect_kind ? " · " + esc(cs.effect_kind) : "") +
          "</p>" +
          '<div class="skill-level-row">' +
          '<button type="button" class="btn skill-dec" data-slot="' +
          esc(cs.slot) +
          '" aria-label="Decrease level">−</button>' +
          '<span class="skill-level" data-slot="' +
          esc(cs.slot) +
          '">Lv ' +
          esc(levelLabel) +
          "</span>" +
          '<button type="button" class="btn skill-inc" data-slot="' +
          esc(cs.slot) +
          '" aria-label="Increase level">+</button>' +
          "</div></article>"
        );
      })
      .join("");
    return (
      '<h3 class="section-title">Skills</h3>' +
      '<p class="hint">Catalog skills · levels 1–5 overwrite OCR.</p>' +
      '<div class="skill-grid" id="skill-grid">' +
      cards +
      "</div>" +
      '<style>' +
      ".skill-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem;margin-top:.5rem;}" +
      ".skill-card{border:1px solid var(--border,#444);border-radius:8px;padding:.75rem;}" +
      ".skill-card h4{margin:0 0 .25rem;font-size:1rem;}" +
      ".skill-level-row{display:flex;align-items:center;gap:.5rem;margin-top:.5rem;}" +
      ".skill-level{min-width:3.5rem;text-align:center;font-variant-numeric:tabular-nums;}" +
      "@media (max-width:520px){.skill-grid{grid-template-columns:1fr;}}" +
      "</style>"
    );
  }

  function renderHeroDetail(hero, catalog) {
    currentHero = hero;
    catalogSkills = catalog || [];
    syncLevelsFromHero(hero);

    if (iconEl) {
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
      [
        "Roster",
        "p" +
          (hero.roster_page == null ? 0 : hero.roster_page) +
          " #" +
          (hero.roster_index == null ? 0 : hero.roster_index),
      ],
      ["Scraped", hero.scraped_at],
    ];
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
        skillsEditorHtml();
      bindSkillControls();
    }
  }

  function bindSkillControls() {
    if (!bodyEl) return;
    bodyEl.querySelectorAll(".skill-inc, .skill-dec").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var slot = btn.getAttribute("data-slot");
        var cur = levelBySlot[slot];
        if (cur == null) cur = 1;
        if (btn.classList.contains("skill-inc")) cur = Math.min(5, cur + 1);
        else cur = Math.max(1, cur - 1);
        levelBySlot[slot] = cur;
        var label = bodyEl.querySelector('.skill-level[data-slot="' + slot + '"]');
        if (label) label.textContent = "Lv " + cur;
        saveSkills();
      });
    });
  }

  function saveSkills() {
    if (!currentHero || saving || !catalogSkills.length) return;
    saving = true;
    fetch("/api/heroes/" + encodeURIComponent(currentHero.name) + "/skills", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skills: skillsPayload() }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) throw new Error(result.data.detail || "Save failed");
        currentHero = result.data.hero;
        catalogSkills = result.data.catalog_skills || catalogSkills;
        syncLevelsFromHero(currentHero);
        if (window.showToast) window.showToast("Skills saved");
      })
      .catch(function (err) {
        if (window.showToast) window.showToast(String(err.message || err), "err");
        else alert(String(err.message || err));
      })
      .finally(function () {
        saving = false;
      });
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
        renderHeroDetail(result.data.hero, result.data.catalog_skills || []);
      })
      .catch(function (err) {
        if (bodyEl) bodyEl.innerHTML = '<p class="empty">' + esc(err.message || err) + "</p>";
      });
  }

  function closeHeroModal() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }

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
