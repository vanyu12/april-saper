/* ============================================================
   «Шахматный клуб» — недельный турнир на G-токенах
   Клиентский блок (фронтенд). Подключается как обычный скрипт:
   - в index.html после app.js добавить <script src="club_front_block.js"></script>
   - в список вызовов renderNewPanels() добавить renderClub();
   - в список loadSocialLazy() добавить строку ["club", loadClub];
   Никаких import/export (игра без сборщика, всё глобально).
   Использует глобальные функции проекта: api(), fmtNum(), fmt(),
   toast(), escapeHtml(), а также глобальный state.
   ============================================================ */

/* Данные API /api/club:
   {
     ok: true,
     season: { number, status, start, end, end_ts, ... },
     entry:  { joined, ... } | null,      // запись участия в текущем сезоне
     bosses: [ { n|round, gold|reward, status }, ... ],  // лестница из 7 боссов
     my_round: <int>,                     // мой текущий раунд/босс
     week_won: <int>,                     // мой выигрыш за неделю
     playoff: [ { place, nick, round }, ... ],  // топ-8
     levels: [ ... ]                       // доп. уровни/награды (опц.)
   }
   status босса: "closed" | "open" | "done" | "todo"
*/

var CLUB_WEEK_LIMIT = 1200;   // недельный лимит выигрыша в G
var CLUB_ENTRY_FEE = 50;      // плата за вступление в G

/* Метки статуса босса -> русский текст */
function clubStatusLabel(s) {
  switch (String(s || "").toLowerCase()) {
    case "closed": return "Закрыт";
    case "open": return "Доступен";
    case "done": return "Пройден";
    case "todo": return "Выполнить";
    default: return s || "—";
  }
}

/* Формат даты/времени, защита от кривых значений */
function clubFmtDate(ts) {
  var n = Number(ts);
  if (!n) return "—";
  try {
    return new Date(n * 1000).toLocaleString("ru-RU");
  } catch (e) {
    return "—";
  }
}

/* ---- рендер всего блока ---- */
function renderClub(data) {
  if (data && typeof data === "object") state.club = data;
  var box = document.getElementById("clubBox");
  if (!box) return;

  var d = (state && state.club) || {};
  var season = d.season || {};
  var entry = d.entry || null;
  var bosses = Array.isArray(d.bosses) ? d.bosses : [];
  var myRound = Number(d.my_round) || 0;
  var weekWon = Number(d.week_won) || 0;
  var playoff = Array.isArray(d.playoff) ? d.playoff : [];

  var joined = !!(entry && (entry.joined || entry.id || entry.user_id || entry.round));

  /* --- сезон: номер, статус, даты, мой прогресс --- */
  var seasonHtml = "" +
    '<div class="club-season">' +
      '<div class="club-season-meta">' +
        '<span class="club-badge">Сезон #' + escapeHtml(season.number != null ? season.number : "—") + '</span>' +
        '<span class="club-status club-st-' + escapeHtml(String(season.status || "active").toLowerCase()) + '">' + escapeHtml(String(season.status || "Активен")) + '</span>' +
      '</div>' +
      '<div class="club-dates"><span>' + clubFmtDate(season.start) + ' — ' + clubFmtDate(season.end_ts != null ? season.end_ts : season.end) + '</span></div>' +
      (joined
        ? '<div class="club-my">Мой прогресс: босс <b>' + (myRound ? myRound : "—") + '</b> из ' + (bosses.length || "—") + '</div>'
        : '<div class="club-join-row">' +
            '<span>Участие: <b class="club-gold">−' + CLUB_ENTRY_FEE + ' G</b></span>' +
            '<button class="secondary small club-join" id="clubJoinBtn">Вступить</button>' +
          '</div>') +
    '</div>';

  /* --- лестница боссов --- */
  var bossesHtml = "";
  if (bosses.length) {
    var bossRows = "";
    for (var i = 0; i < bosses.length; i++) {
      var b = bosses[i];
      var num = b.n != null ? b.n : (b.round != null ? b.round : (i + 1));
      var gold = b.gold != null ? b.gold : b.reward;
      var st = clubStatusLabel(b.status);
      var stKey = String(b.status || "closed").toLowerCase();
      var clickable = (stKey === "open" || stKey === "todo");
      bossRows += '<div class="club-boss club-boss-' + escapeHtml(stKey) + '">' +
        '<span class="club-boss-num">' + num + '</span>' +
        '<span class="club-boss-reward">Награда: <b class="club-gold">' + fmtNum(gold) + ' G</b></span>' +
        '<span class="club-boss-st">' + escapeHtml(st) + '</span>' +
        (clickable ? '<button class="secondary small club-boss-go" data-round="' + num + '">Выполнить</button>' : "") +
      '</div>';
    }
    bossesHtml = '<div class="ec-block club-bosses-block">' +
      '<span class="club-bosses-title">♟ Лестница боссов</span>' +
      '<div class="club-bosses">' + bossRows + '</div>' +
    '</div>';
  }

  /* --- дополнительные уровни/награды (если есть) --- */
  var levelsHtml = "";
  if (Array.isArray(d.levels) && d.levels.length) {
    var levelRows = "";
    for (var j = 0; j < d.levels.length; j++) {
      var l = d.levels[j];
      var nm = l.n != null ? l.n : (l.level != null ? l.level : "");
      var rw = l.gold != null ? l.gold : l.reward;
      levelRows += '<div class="club-level"><span>Ур. ' + escapeHtml(String(nm)) + '</span><span class="club-gold">' + fmtNum(rw) + ' G</span></div>';
    }
    levelsHtml = '<div class="ec-block"><span class="club-bosses-title">🏅 Уровни турнира</span>' +
      '<div class="club-levels">' + levelRows + '</div></div>';
  }

  /* --- плей-офф: топ-8 и победитель --- */
  var playoffHtml = "";
  if (playoff.length) {
    var pfRows = "";
    for (var p = 0; p < playoff.length; p++) {
      var pl = playoff[p];
      var place = pl.place != null ? pl.place : (p + 1);
      pfRows += '<div class="club-pf-row' + (place <= 3 ? ' club-pf-top' : '') + '">' +
        '<span class="club-pf-place">' + place + '.</span>' +
        '<span class="club-pf-nick">' + escapeHtml(pl.nick || pl.username || "—") + '</span>' +
        '<span class="club-pf-round">раунд ' + escapeHtml(pl.round != null ? pl.round : "—") + '</span>' +
      '</div>';
    }
    playoffHtml = '<details class="ec-block" open><summary>🏁 Плей-офф · топ-' + playoff.length + '</summary>' +
      '<div class="club-pf-list">' + pfRows + '</div>' +
      ((d.winner || d.champion) ? '<div class="club-winner">🏆 Победитель: <b>' + escapeHtml((d.winner || d.champion) || "—") + '</b></div>' : "") +
    '</details>';
  }

  /* --- недельный лимит выигрыша --- */
  var pct = Math.max(0, Math.min(100, (weekWon / CLUB_WEEK_LIMIT) * 100));
  var limitHtml = '<div class="club-limit">' +
    '<div class="club-limit-head">' +
      '<span>Недельный лимит выигрыша</span>' +
      '<span class="club-gold">' + fmtNum(weekWon) + ' / ' + fmtNum(CLUB_WEEK_LIMIT) + ' G</span>' +
    '</div>' +
    '<div class="club-bar"><div class="club-bar-fill" style="width:' + pct.toFixed(1) + '%"></div></div>' +
    (weekWon >= CLUB_WEEK_LIMIT ? '<div class="club-limit-done">Лимит исчерпан — жди новый сезон</div>' : "") +
  '</div>';

  box.innerHTML = '<div class="club-body-inner">' +
      seasonHtml + bossesHtml + levelsHtml + limitHtml + playoffHtml +
    '</div>';

  /* --- делегирование кликов на контейнер --- */
  box.removeEventListener("click", clubHandleClick);
  box.addEventListener("click", clubHandleClick);
}

/* Делегированный обработчик кликов для #clubBox */
async function clubHandleClick(evt) {
  var btn = evt.target && evt.target.closest ? evt.target.closest("[data-round], #clubJoinBtn") : null;
  if (!btn) return;

  /* кнопка «Вступить» */
  if (btn.id === "clubJoinBtn") {
    evt.preventDefault();
    try {
      var r = await api("/api/club/join", {});
      if (r && r.ok === false) throw new Error(r.error || "Не удалось вступить");
      toast("Вступили в турнир клуба ♟");
      await loadClub();
    } catch (e) {
      toast(e.message || "Ошибка вступления");
    }
    return;
  }

  /* кнопка на боссе: data-round */
  var round = btn.getAttribute && btn.getAttribute("data-round");
  if (round != null) {
    evt.preventDefault();
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "…";
    try {
      var r2 = await api("/api/club/boss-result", { round: Number(round) });
      if (r2 && r2.ok === false) throw new Error(r2.error || "Ошибка боя");
      toast(r2 && r2.reward != null ? "Награда +" + fmtNum(r2.reward) + " G" : "Победа!");
      await loadClub();
    } catch (e) {
      toast(e.message || "Ошибка боя");
      btn.disabled = false;
      btn.textContent = original;
    }
  }
}

/* ---- загрузка данных с API ---- */
async function loadClub() {
  var box = document.getElementById("clubBox");
  if (box) box.innerHTML = '<div class="club-loading">Загрузка…</div>';
  try {
    var data = await api("/api/club", {});
    if (data && data.ok === false) {
      throw new Error(data.error || "Ошибка загрузки клуба");
    }
    renderClub(data);
    loadClubHistory();
  } catch (e) {
    if (box) {
      box.innerHTML = '<div class="club-err">⚠ ' + escapeHtml(e.message || "Клуб недоступен") + '</div>';
    }
  }
}

/* ---- История завершённых сезонов ---- */
async function loadClubHistory() {
  var box = document.getElementById("clubHistoryBox");
  if (!box) return;
  try {
    var data = await api("/api/club/history", {});
    if (data && data.ok === false) return;
    var hist = Array.isArray(data.history) ? data.history : [];
    if (!hist.length) return;
    var rows = "";
    for (var i = 0; i < hist.length; i++) {
      var h = hist[i];
      rows += '<div class="club-hist-row">' +
        '<span class="club-hist-season">Сезон #' + escapeHtml(String(h.id || "—")) + '</span>' +
        '<span class="club-hist-winner">🏆 ' + escapeHtml(h.winner_nick || "—") + '</span>' +
      '</div>';
    }
    box.innerHTML = '<details class="ec-block"><summary>📜 История сезонов</summary>' +
      '<div class="club-hist-list">' + rows + '</div></details>';
  } catch (e) {}
}