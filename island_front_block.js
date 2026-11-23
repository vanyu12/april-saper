/* ============================================================
   «Острова» — пассивный доход в GMPOINT с merge-прогрессией
   Клиентский блок. Подключён в index.html после app.js.
   Использует глобальные функции проекта: api(), fmtNum(), toast(),
   escapeHtml(), глобальный state.
   ============================================================ */

/* Картинки-острова (фоны уже в web/), сопоставление с типами */
var ISLAND_IMG = {
  sand:    "bg_ocean.jpg",
  palm:    "bg_forest.jpg",
  volcano: "bg_night.jpg",
  ice:     "bg_mountains.jpg",
  city:    "bg_desert.jpg",
  zen:     "bg_aurora.jpg",
};

/* ---- рендер всего блока ---- */
function renderIslands(data) {
  if (data && typeof data === "object") state.islands = data;
  var box = document.getElementById("islandsBox");
  if (!box) return;
  var d = (state && state.islands) || {};
  var islands = d.islands || {};
  var types = Array.isArray(d.types) ? d.types : [];
  var gained = Number(d.income_gained) || 0;
  var rate = Number(d.income_rate) || 0;
  var total = Number(d.total_earned) || 0;
  var gmpoint = Number(d.gmpoint) || 0;

  var html = "" +
    '<div class="isl-stats">' +
      '<div class="isl-stat"><span>Доход</span><b class="club-gold">' + fmtNum(rate) + ' GMP/ч</b></div>' +
      '<div class="isl-stat"><span>Накоплено</span><b class="club-gold">' + fmtNum(gained) + ' GMP</b></div>' +
      '<div class="isl-stat"><span>Всего собрано</span><b>' + fmtNum(total) + ' GMP</b></div>' +
    '</div>' +
    '<button class="primary small isl-collect-btn"' + (gained > 0 ? '' : ' disabled') + '>💰 Забрать доход (' + fmtNum(gained) + ' GMP)</button>' +
    '<div class="isl-grid">';

  for (var i = 0; i < types.length; i++) {
    var t = types[i];
    var item = islands[t.key] || {};
    var owned = !!item.owned;
    var level = Number(item.level) || 1;
    var img = ISLAND_IMG[t.key] || "bg_ocean.jpg";
    html += '<div class="isl-card' + (owned ? ' isl-owned' : '') + '">' +
      '<div class="isl-img-wrap"><img class="isl-img" src="/static/' + escapeHtml(img) + '" alt=" остров" loading="lazy">' +
      (owned ? '<span class="isl-lvl">ур. ' + level + '</span>' : '<span class="isl-lock">🔒</span>') +
      '</div>' +
      '<div class="isl-info">' +
        '<div class="isl-name">' + escapeHtml(t.emoji) + ' ' + escapeHtml(t.name) + '</div>' +
        '<div class="isl-income">' + fmtNum(t.income) + ' GMP/ч</div>' +
        (owned
          ? (level >= (t.max_level || 5)
              ? '<span class="isl-max">МАКС</span>'
              : '<button class="secondary small isl-upg-btn" data-island="' + escapeHtml(t.key) + '">⬆ Улучшить · ' + fmtNum(t.income * level) + ' GMP</button>')
          : '<button class="secondary small isl-buy-btn" data-island="' + escapeHtml(t.key) + '">🏝 Купить · ' + fmtNum(t.cost) + ' GMP</button>') +
      '</div>' +
    '</div>';
  }

  html += '</div>';
  html += '<p class="isl-bal">Баланс: <b class="club-gold">' + fmtNum(gmpoint) + ' GMP</b></p>';

  box.innerHTML = html;
  box.removeEventListener("click", islHandleClick);
  box.addEventListener("click", islHandleClick);
}

/* Делегированный обработчик кликов */
async function islHandleClick(evt) {
  var btn = evt.target && evt.target.closest
    ? evt.target.closest(".isl-collect-btn, .isl-buy-btn, .isl-upg-btn") : null;
  if (!btn) return;
  evt.preventDefault();

  if (btn.classList.contains("isl-collect-btn")) {
    try {
      var rc = await api("/api/island/collect", {});
      if (rc && rc.ok === false) throw new Error(rc.error || "Не удалось собрать");
      toast("Доход собран ⛵");
      renderIslands(rc);
    } catch (e) {
      toast(e.message || "Ошибка");
    }
    return;
  }

  var key = btn.getAttribute && btn.getAttribute("data-island");
  if (!key) return;
  var url = btn.classList.contains("isl-buy-btn")
    ? "/api/island/buy" : "/api/island/upgrade";
  var verb = btn.classList.contains("isl-buy-btn") ? "Остров куплен" : "Остров улучшен";
  try {
    var r = await api(url, { key: key });
    if (r && r.ok === false) throw new Error(r.error || "Недостаточно GMPOINT");
    toast(verb + " 🏝");
    renderIslands(r);
  } catch (e) {
    toast(e.message || "Ошибка");
  }
}

/* ---- загрузка данных с API ---- */
async function loadIslands() {
  var box = document.getElementById("islandsBox");
  if (box) box.innerHTML = '<div class="pet-loading">Загрузка…</div>';
  try {
    var data = await api("/api/islands", {});
    if (data && data.ok === false) throw new Error(data.error || "Ошибка");
    renderIslands(data);
  } catch (e) {
    if (box) box.innerHTML = '<div class="pet-err">⚠ ' + escapeHtml(e.message || "Острова недоступны") + '</div>';
  }
}