/* ============================================================
   «Питомец» — пассивный доход в G-токенах
   Клиентский блок. Подключён в index.html после app.js.
   Использует глобальные функции проекта: api(), fmtNum(), toast(),
   escapeHtml(), глобальный state.
   ============================================================ */

var PET_HUNGRY_MS = 4 * 3600 * 1000;

/* ---- рендер всего блока ---- */
function renderPet(data) {
  if (data && typeof data === "object") state.pet = data;
  var box = document.getElementById("petBox");
  if (!box) return;
  var d = (state && state.pet) || {};
  var pet = d.pet || {};
  var types = Array.isArray(d.types) ? d.types : [];
  var hungry = !!d.hungry;
  var level = Number(d.level) || 1;
  var xp = Number(d.xp) || 0;
  var income = Number(d.income) || 0;
  var gold = Number(d.gold) || 0;

  var status = hungry
    ? '<span class="pet-status pet-hungry">😾 Голоден</span>'
    : '<span class="pet-status pet-fed">😺 Сыт</span>';

  var html = "" +
    '<div class="pet-top">' +
      '<div class="pet-emoji">' + escapeHtml(d.emoji || "🐱") + '</div>' +
      '<div class="pet-info">' +
        '<div class="pet-name">' + escapeHtml(d.name || "Питомец") + ' <span class="pet-level">ур. ' + level + '</span></div>' +
        '<div class="pet-xp">Опыт: ' + fmtNum(xp) + ' / 100</div>' +
        '<div class="pet-income">Доход: <b class="club-gold">' + fmtNum(income) + ' G</b>/ч</div>' +
        status +
      '</div>' +
    '</div>' +
    '<div class="pet-actions">' +
      '<button class="secondary small pet-feed-btn" id="petFeedBtn"' + (income <= 0 ? '' : '') + '>🍖 Покормить (−' + fmtNum(d.feed_cost || 50) + ' G)</button>' +
      '<button class="secondary small pet-collect-btn" id="petCollectBtn">💰 Забрать доход</button>' +
      '<button class="secondary small pet-play-btn" id="petPlayBtn">🎾 Поиграть</button>' +
    '</div>' +
    '<div class="pet-shop">' +
      '<span class="pet-shop-title">Другие питомцы</span>' +
      '<div class="pet-shop-list">';
  for (var i = 0; i < types.length; i++) {
    var t = types[i];
    var owned = t.key === d.type;
    html += '<div class="pet-shop-item">' +
      '<span>' + escapeHtml(t.emoji) + ' ' + escapeHtml(t.name) + '</span>' +
      '<span class="club-gold">' + fmtNum(t.income) + ' G/ч</span>' +
      (owned
        ? '<span class="pet-owned">У вас</span>'
        : '<button class="secondary small pet-buy-btn" data-pet="' + escapeHtml(t.key) + '">Купить · ' + fmtNum(t.cost) + '</button>') +
    '</div>';
  }
  html += '</div></div>';

  box.innerHTML = html;
  box.removeEventListener("click", petHandleClick);
  box.addEventListener("click", petHandleClick);
}

/* Делегированный обработчик кликов */
async function petHandleClick(evt) {
  var btn = evt.target && evt.target.closest ? evt.target.closest("#petFeedBtn, #petCollectBtn, #petPlayBtn, .pet-buy-btn") : null;
  if (!btn) return;

  if (btn.id === "petPlayBtn") {
    evt.preventDefault();
    try {
      var rp = await api("/api/pet/play", {});
      if (rp && rp.ok === false) {
        if (rp.error === "cooldown") {
          var left = Math.ceil((rp.cooldown_left || 0) / 60);
          toast("Подожди " + left + " мин");
        } else {
          throw new Error(rp.error || "Не удалось поиграть");
        }
        return;
      }
      var res = rp && rp.play ? rp.play.result : "normal";
      var rew = rp && rp.play ? rp.play.reward : 0;
      var msgs = { miss: "😿 Мимо мячика", normal: "🐾 Принёс мяч", good: "🎾 Отличный бросок!", perfect: "🌟 Идеально!" };
      toast((msgs[res] || "Игра") + (rew > 0 ? "  +" + fmtNum(rew) + " G" : ""));
      renderPet(rp);
    } catch (e) {
      toast(e.message || "Ошибка");
    }
    return;
  }

  if (btn.id === "petFeedBtn") {
    evt.preventDefault();
    try {
      var r = await api("/api/pet/feed", {});
      if (r && r.ok === false) throw new Error(r.error || "Не удалось покормить");
      toast("Питомец покормлен 🍖");
      renderPet(r);
    } catch (e) {
      toast(e.message || "Ошибка");
    }
    return;
  }

  if (btn.id === "petCollectBtn") {
    evt.preventDefault();
    try {
      var r2 = await api("/api/pet/collect", {});
      if (r2 && r2.ok === false) throw new Error(r2.error || "Не удалось забрать");
      toast(r2 && r2.pet && r2.pet.total_earned != null ? "Собрано" : "Собрано");
      renderPet(r2);
    } catch (e) {
      toast(e.message || "Ошибка");
    }
    return;
  }

  var petType = btn.getAttribute && btn.getAttribute("data-pet");
  if (petType) {
    evt.preventDefault();
    try {
      var r3 = await api("/api/pet/buy", { pet_type: petType });
      if (r3 && r3.ok === false) throw new Error(r3.error || "Недостаточно G");
      toast("Куплен питомец");
      renderPet(r3);
    } catch (e) {
      toast(e.message || "Ошибка");
    }
  }
}

/* ---- загрузка данных с API ---- */
async function loadPet() {
  var box = document.getElementById("petBox");
  if (box) box.innerHTML = '<div class="pet-loading">Загрузка…</div>';
  try {
    var data = await api("/api/pet", {});
    if (data && data.ok === false) throw new Error(data.error || "Ошибка");
    renderPet(data);
    loadPetTop();
  } catch (e) {
    if (box) box.innerHTML = '<div class="pet-err">⚠ ' + escapeHtml(e.message || "Питомец недоступен") + '</div>';
  }
}

/* ---- Топ питомцев (лидерборд по заработку) ---- */
async function loadPetTop() {
  var box = document.getElementById("petTopBox");
  if (!box) return;
  try {
    var data = await api("/api/pet/top", {});
    if (data && data.ok === false) return;
    var top = Array.isArray(data.top) ? data.top : [];
    if (!top.length) return;
    var rows = "";
    for (var i = 0; i < top.length; i++) {
      var t = top[i];
      rows += '<div class="pet-top-row' + (i < 3 ? ' pet-top-medal' : '') + '">' +
        '<span class="pet-top-place">' + (i + 1) + '.</span>' +
        '<span class="pet-top-emoji">' + escapeHtml(t.emoji || "🐱") + '</span>' +
        '<span class="pet-top-nick">' + escapeHtml(t.nick || "—") + '</span>' +
        '<span class="club-gold">' + fmtNum(t.total_earned) + ' G</span>' +
      '</div>';
    }
    box.innerHTML = '<details class="ec-block" open><summary>🏆 Топ питомцев</summary>' +
      '<div class="pet-top-list">' + rows + '</div></details>';
  } catch (e) {}
}