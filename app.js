const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const state = {
  user: null,
  round: null,
  mines: 3,
  bet: 50,
  lastBet: 50,
  settings: { min_bet: 10, max_bet: 100000, min_mines: 1, max_mines: 24, daily_bonus: 500, maintenance: 0 },
  isAdmin: false,
  sound: true,
  game: "mines",
  quests: [],
  leaderboard: { by_balance: [], by_multiplier: [], me: 0 },
  history: [],
  referrals: { total: 0, active: 0 },
  fair: { seed_hash: "", client_seed: "", nonce: 0 },
  started: false,
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat("ru-RU").format(Math.round(n));
const fmtMult = (m) => "×" + Number(m).toFixed(2).replace(".", ",");

function haptic(type) {
  if (!tg || !tg.HapticFeedback) return;
  try {
    if (type === "error") tg.HapticFeedback.notificationOccurred("error");
    else if (type === "success") tg.HapticFeedback.notificationOccurred("success");
    else tg.HapticFeedback.impactOccurred("light");
  } catch (e) {}
}

let audioCtx = null;

function tone(freq, duration, type, gain) {
  if (!state.sound) return;
  try {
    if (!audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioCtx = new Ctx();
    }
    if (audioCtx.state === "suspended") audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const vol = audioCtx.createGain();
    osc.type = type || "sine";
    osc.frequency.value = freq;
    vol.gain.value = gain == null ? 0.05 : gain;
    osc.connect(vol);
    vol.connect(audioCtx.destination);
    const now = audioCtx.currentTime;
    vol.gain.setValueAtTime(vol.gain.value, now);
    vol.gain.exponentialRampToValueAtTime(0.0001, now + duration);
    osc.start(now);
    osc.stop(now + duration);
  } catch (e) {}
}

const sfx = {
  open() { tone(520, 0.09, "triangle", 0.05); },
  coin() { tone(700, 0.09, "sine", 0.05); setTimeout(() => tone(980, 0.1, "sine", 0.04), 70); },
  boom() { tone(110, 0.42, "sawtooth", 0.09); setTimeout(() => tone(70, 0.5, "sawtooth", 0.07), 90); },
  cash() { [660, 880, 1180].forEach((f, i) => setTimeout(() => tone(f, 0.12, "sine", 0.05), i * 80)); },
};

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2200);
}

function modal(emoji, title, text, btnText) {
  $("modalEmoji").textContent = emoji;
  $("modalTitle").textContent = title;
  $("modalText").textContent = text;
  $("modalBtn").textContent = btnText || "Ещё раз";
  $("modal").classList.add("show");
}

async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
  if (startParam) headers["X-Start-Param"] = startParam;
  const res = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    throw new Error("Сервер не ответил");
  }
  if (!res.ok || !data.ok) throw new Error(data.error || "Ошибка запроса");
  return data;
}

const startParam = (() => {
  try {
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) return tg.initDataUnsafe.start_param;
    return new URLSearchParams(location.search).get("startapp") || "";
  } catch (e) {
    return "";
  }
})();

/* ---------- rendering ---------- */

function renderBalance() {
  $("balanceValue").textContent = fmt(state.user ? state.user.balance : 0);
  $("statBalance").textContent = fmt(state.user ? state.user.balance : 0);
}

function renderDaily() {
  const btn = $("dailyBtn");
  const ready = state.user && state.user.daily_ready;
  btn.classList.toggle("ready", !!ready);
  btn.title = ready ? "Забрать 500 сапов" : "Бонус уже получен";
}

function renderGrid() {
  const grid = $("grid");
  grid.innerHTML = "";
  const round = state.round;
  const opened = round ? round.opened : [];
  const mineSet = round && round.mine_positions ? new Set(round.mine_positions) : null;

  for (let i = 0; i < 25; i++) {
    const cell = document.createElement("button");
    cell.className = "cell";
    cell.dataset.index = i;
    cell.type = "button";

    if (opened.includes(i)) {
      if (mineSet && mineSet.has(i)) {
        cell.classList.add("mine");
        cell.innerHTML = '<span class="bomb"></span>';
      } else {
        cell.classList.add("safe");
        cell.innerHTML = '<span class="gem"></span>';
      }
      cell.style.animationDelay = ((i % 5) * 22) + "ms";
      cell.classList.add("locked");
    } else if (mineSet) {
      if (mineSet.has(i)) {
        cell.classList.add("mine");
        cell.innerHTML = '<span class="bomb"></span>';
      } else if (round.status !== "active") {
        cell.classList.add("dim");
        cell.innerHTML = '<span class="gem"></span>';
      }
      cell.classList.add("locked");
    } else if (!round) {
      cell.innerHTML = "";
    }

    if (round && round.status === "active" && !opened.includes(i)) {
      cell.addEventListener("click", () => openCell(i));
    }
    grid.appendChild(cell);
  }
}

function previewLadder(mines, steps) {
  const safe = 25 - mines;
  const out = [];
  for (let k = 1; k <= Math.min(steps, safe); k++) {
    let p = 1;
    for (let i = 0; i < k; i++) p *= (safe - i) / (25 - i);
    const mult = Math.max(1, Math.floor((0.99 / p) * 100) / 100);
    const chance = (safe - k + 1) / (25 - k + 1);
    out.push({ opened: k, multiplier: mult, chance });
  }
  return out;
}

function renderLadder() {
  const box = $("ladder");
  if (!box) return;
  const round = state.round;
  const steps = round && round.ladder && round.ladder.length
    ? round.ladder
    : previewLadder(state.mines, 5);
  if (!steps.length) {
    box.innerHTML = '<div class="ladder-empty">Поле почти вскрыто</div>';
    return;
  }
  box.innerHTML = steps
    .map((step, i) => {
      const chance = Math.round((step.chance || 0) * 100);
      return `<div class="ladder-step${i === 0 ? " next" : ""}">
        <span class="ladder-mult">${fmtMult(step.multiplier)}</span>
        <span class="ladder-chance">${chance}%</span>
      </div>`;
    })
    .join("");
}

function renderHud() {
  const round = state.round;
  const mult = round ? round.multiplier : 1;
  const bet = round ? round.bet : state.bet;
  const payout = round ? Math.floor(bet * mult) : 0;
  $("hudMult").textContent = fmtMult(mult);
  $("hudPayout").textContent = fmt(payout);
  let chance = 0;
  if (round) {
    chance = round.next_chance != null ? round.next_chance : 0;
  } else {
    chance = (25 - state.mines) / 25;
  }
  $("hudChance").textContent = Math.round(chance * 100) + "%";
}

function renderControls() {
  const round = state.round;
  const cta = $("ctaBtn");
  const setup = $("setupPanel");

  if (round && round.status === "active") {
    setup.classList.add("hidden");
    setup.style.display = "none";
    const payout = Math.floor(round.bet * round.multiplier);
    cta.textContent = round.opened.length ? `Забрать ${fmt(payout)} сапов` : "Открой первую клетку";
    cta.classList.add("cashout");
    cta.disabled = round.opened.length === 0;
    $("hint").textContent = `Мин: ${round.mines} · ставка ${fmt(round.bet)}`;
  } else {
    setup.style.display = "";
    setup.classList.remove("hidden");
    cta.textContent = "Начать игру";
    cta.classList.remove("cashout");
    cta.disabled = false;
    $("hint").textContent = "Открой первую клетку и реши, когда забрать.";
  }
  renderHud();
}

function renderMines() {
  $("minesValue").textContent = state.mines;
  $("minesSlider").value = state.mines;
  document.querySelectorAll("#minesChips .chip").forEach((c) => {
    c.classList.toggle("active", Number(c.dataset.mines) === Number(state.mines));
  });
  const risk = state.mines <= 3 ? "низкий" : state.mines <= 10 ? "средний" : "высокий";
  $("riskLabel").textContent = "Риск: " + risk;
  const maxMult = maxMultiplier(state.mines);
  $("maxMultLabel").textContent = "макс " + fmtMult(maxMult);
}

function maxMultiplier(mines) {
  const safe = 25 - mines;
  let p = 1;
  for (let i = 0; i < safe; i++) p *= (safe - i) / (25 - i);
  return Math.max(1, Math.floor((0.99 / p) * 100) / 100);
}

function renderProfile() {
  if (!state.user) return;
  const u = state.user;
  $("profileName").textContent = u.first_name || u.username || "Игрок";
  $("profileId").textContent = "id " + u.id;
  $("avatar").textContent = (u.first_name || u.username || "И").trim().charAt(0).toUpperCase();
  $("statGames").textContent = fmt(u.games_played);
  $("statWins").textContent = fmt(u.games_won);
  $("statBest").textContent = fmtMult(u.best_multiplier || 1);
  $("refTotal").textContent = state.referrals.total || 0;
  $("refActive").textContent = state.referrals.active || 0;
  $("refLink").textContent = botLink(u.ref_code);

  const ach = [
    { icon: "🎯", name: "Первая партия", done: u.games_played >= 1 },
    { icon: "🔥", name: "10 партий", done: u.games_played >= 10 },
    { icon: "💎", name: "Кэшаут ×2", done: (u.best_multiplier || 0) >= 2 },
    { icon: "🏆", name: "Кэшаут ×10", done: (u.best_multiplier || 0) >= 10 },
    { icon: "🧠", name: "100 партий", done: u.games_played >= 100 },
  ];
  $("achievements").innerHTML = ach
    .map(
      (a) =>
        `<div class="ach ${a.done ? "done" : "locked"}"><div class="ach-icon">${a.icon}</div><div class="ach-name">${a.name}</div>${a.done ? '<div class="ach-check">✓</div>' : ""}</div>`
    )
    .join("");
}

function botLink(code) {
  const username = state.botUsername || (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && window.BOT_USERNAME) || "AprilSaperBot";
  return `https://t.me/${username}?start=${code}`;
}

function renderHistory() {
  const list = $("historyList");
  if (!state.history.length) {
    list.innerHTML = '<div class="empty">Пока ни одной игры</div>';
    return;
  }
  list.innerHTML = state.history
    .map((r) => {
      const win = r.payout > 0;
      const date = new Date(r.created_at * 1000);
      const opened = (r.opened || []).length;
      return `<div class="row">
        <div class="row-icon ${win ? "win" : "lose"}">${win ? "💎" : "💥"}</div>
        <div class="row-main">
          <div class="row-title">${fmt(r.bet)} сапов · ${r.mines} мин</div>
          <div class="row-sub">${opened} клеток · ${date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</div>
        </div>
        <div class="row-value ${win ? "plus" : "minus"}">${win ? "+" + fmt(r.payout) : "−" + fmt(r.bet)}</div>
      </div>`;
    })
    .join("");
}

function renderTop(tab) {
  const list = $("topList");
  let rows = [];
  if (tab === "mult") {
    rows = (state.leaderboard.by_multiplier || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: fmtMult(u.best_multiplier),
      id: u.user_id,
    }));
  } else {
    rows = (state.leaderboard.by_balance || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: fmt(u.balance) + " сапов",
      id: u.user_id,
    }));
  }
  if (!rows.length) {
    list.innerHTML = '<div class="empty">Рейтинг пока пуст</div>';
    return;
  }
  const medals = ["🥇", "🥈", "🥉"];
  list.innerHTML = rows
    .map(
      (r) => `<div class="row" style="${r.id === state.leaderboard.me ? "border-color:rgba(46,230,168,.45)" : ""}">
        <div class="row-icon">${medals[r.place - 1] || r.place}</div>
        <div class="row-main"><div class="row-title">${escapeHtml(r.name)}</div></div>
        <div class="row-value">${r.value}</div>
      </div>`
    )
    .join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderFair() {
  $("fairHash").textContent = state.fair.seed_hash || "—";
  $("fairNonce").textContent = state.fair.nonce || 0;
  if (document.activeElement !== $("clientSeed")) {
    $("clientSeed").value = state.fair.client_seed || "";
  }
}

/* ---------- admin ---------- */

function renderAdminStats() {
  const stats = state.admin && state.admin.stats;
  if (!stats) return;
  const cards = [
    ["Игроки", fmt(stats.users)],
    ["Бан", fmt(stats.banned)],
    ["Партий", fmt(stats.rounds)],
    ["Активных", fmt(stats.active_rounds)],
    ["Оборот", fmt(stats.wagered)],
    ["Выплаты", fmt(stats.paid)],
    ["Профит", fmt(stats.profit)],
    ["RTP", (stats.rtp || 0) + "%"],
  ];
  $("adminStats").innerHTML = cards
    .map(([label, value]) =>
      `<div class="stat"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`)
    .join("");
}

function playerName(row) {
  if (row.username) return "@" + row.username;
  return row.first_name || "id" + row.user_id;
}

function renderAdminRecent() {
  const box = $("adminRecent");
  const items = (state.admin && state.admin.recent) || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Ставок пока нет</div>';
    return;
  }
  box.innerHTML = items
    .map((r) => {
      const win = r.payout > 0;
      return `<div class="row">
        <div class="row-icon ${win ? "win" : "lose"}">${win ? "💎" : "💥"}</div>
        <div class="row-main">
          <div class="row-title">${escapeHtml(playerName(r))} · ${fmt(r.bet)}</div>
          <div class="row-sub">${r.mines} мин · ${fmtMult(r.multiplier)} · ${r.status}</div>
        </div>
        <div class="row-value ${win ? "plus" : "minus"}">${win ? "+" + fmt(r.payout) : "−" + fmt(r.bet)}</div>
      </div>`;
    })
    .join("");
}

function renderAdminUsers() {
  const box = $("adminUsers");
  const items = state.adminUsers || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Никого не нашли</div>';
    return;
  }
  box.innerHTML = items
    .map((u) => `<div class="row admin-row" data-id="${u.user_id}">
      <div class="row-main">
        <div class="row-title">${escapeHtml(playerName(u))}${u.is_banned ? '<span class="ban-mark">БАН</span>' : ""}</div>
        <div class="row-sub">id ${u.user_id} · партий ${u.games_played} · лучший ${fmtMult(u.best_multiplier)}</div>
      </div>
      <div class="row-value">${fmt(u.balance)}</div>
      <div class="admin-actions">
        <input class="mini-input" type="number" value="500" min="1">
        <button class="chip-btn" data-act="grant">Начислить</button>
        <button class="chip-btn" data-act="take">Списать</button>
        <button class="chip-btn" data-act="${u.is_banned ? "unban" : "ban"}">${u.is_banned ? "Разбан" : "Бан"}</button>
      </div>
    </div>`)
    .join("");
}

function fillSettingsForm(settings) {
  if (!settings) return;
  $("setMinBet").value = settings.min_bet;
  $("setMaxBet").value = settings.max_bet;
  $("setMinMines").value = settings.min_mines;
  $("setMaxMines").value = settings.max_mines;
  $("setDaily").value = settings.daily_bonus;
  $("setMaintenance").checked = !!settings.maintenance;
}

async function loadAdmin() {
  try {
    const data = await api("/api/admin/overview");
    state.admin = data;
    renderAdminStats();
    renderAdminRecent();
    fillSettingsForm(data.settings);
    if (!state.adminUsers) await adminSearch("");
  } catch (e) {
    toast(e.message);
  }
}

async function adminSearch(query) {
  try {
    const data = await api("/api/admin/users", { query: query || "", limit: 20 });
    state.adminUsers = data.items;
    renderAdminUsers();
  } catch (e) {
    toast(e.message);
  }
}

async function adminBalance(userId, delta) {
  try {
    const data = await api("/api/admin/balance",
      { user_id: userId, value: delta, mode: "grant" });
    toast("Баланс: " + fmt(data.balance));
    await adminSearch($("adminSearch").value.trim());
    await loadAdmin();
  } catch (e) {
    toast(e.message);
  }
}

async function adminBan(userId, banned) {
  try {
    await api("/api/admin/ban", { user_id: userId, banned });
    await adminSearch($("adminSearch").value.trim());
  } catch (e) {
    toast(e.message);
  }
}

async function saveAdminSettings() {
  try {
    const payload = {
      min_bet: Number($("setMinBet").value),
      max_bet: Number($("setMaxBet").value),
      min_mines: Number($("setMinMines").value),
      max_mines: Number($("setMaxMines").value),
      daily_bonus: Number($("setDaily").value),
      maintenance: $("setMaintenance").checked ? 1 : 0,
    };
    const data = await api("/api/admin/settings", payload);
    state.settings = data.settings;
    fillSettingsForm(data.settings);
    toast("Настройки сохранены");
  } catch (e) {
    toast(e.message);
  }
}

/* ---------- другие игры и квесты ---------- */

function switchGame(name) {
  state.game = name;
  document.querySelectorAll("#gameSwitch .gs-btn").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.game === name));
  document.querySelectorAll(".game-pane").forEach((pane) =>
    pane.classList.toggle("active", pane.id === "game-pane-" + name));
  if (name === "wheel") renderWheel();
}

function clampBet(value) {
  const min = state.settings.min_bet || 10;
  const max = state.settings.max_bet || 100000;
  return Math.max(min, Math.min(max, Math.round(value || 0)));
}

function renderWheel(highlight) {
  const box = $("wheelView");
  if (!box) return;
  const segments = state.wheelSegments && state.wheelSegments.length
    ? state.wheelSegments
    : [{ multiplier: 0 }, { multiplier: 1.1 }, { multiplier: 1.35 },
       { multiplier: 1.7 }, { multiplier: 2.3 }, { multiplier: 3.2 }];
  box.innerHTML = segments
    .map((seg, i) => {
      const zero = !seg.multiplier;
      return `<div class="wheel-seg${highlight === i ? " hit" : ""}${zero ? " zero" : ""}">
        ${zero ? "×0" : fmtMult(seg.multiplier)}
      </div>`;
    })
    .join("");
}

function renderQuests() {
  const box = $("questsList");
  if (!box) return;
  const items = state.quests || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Задания появятся после первой партии</div>';
    return;
  }
  box.innerHTML = items
    .map((q) => {
      const pct = Math.min(100, Math.round((q.progress / q.target) * 100));
      const label = q.claimed
        ? "Получено"
        : q.ready
          ? `Забрать +${fmt(q.reward)}`
          : `${fmt(q.progress)} / ${fmt(q.target)}`;
      return `<div class="quest${q.ready ? " ready" : ""}${q.claimed ? " done" : ""}">
        <div class="quest-main">
          <div class="quest-title">${escapeHtml(q.title)}</div>
          <div class="quest-bar"><span style="width:${pct}%"></span></div>
        </div>
        <button class="chip-btn quest-claim" data-quest="${q.key}"
          ${q.ready ? "" : "disabled"}>${label}</button>
      </div>`;
    })
    .join("");
}

async function playDice(pick) {
  const input = $("diceBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  try {
    const data = await api("/api/games/dice", { bet, pick });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    const face = $("diceFace");
    face.textContent = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"][data.roll - 1] || "🎲";
    face.classList.remove("roll");
    void face.offsetWidth;
    face.classList.add("roll");
    if (data.win) {
      sfx.coin();
      haptic("success");
      toast(`+${fmt(data.payout)} сапов`);
    } else {
      sfx.boom();
      haptic("error");
      toast("Не угадал");
    }
    $("diceHint").textContent =
      `Выпало ${data.roll} — ${data.roll % 2 === 0 ? "чёт" : "нечёт"}`;
    renderAll();
  } catch (e) {
    toast(e.message);
  }
}

async function spinWheel() {
  const input = $("wheelBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const btn = $("wheelSpin");
  btn.disabled = true;
  try {
    const data = await api("/api/games/wheel", { bet });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    state.wheelSegments = data.segments || state.wheelSegments;
    renderWheel(data.segment);
    if (data.multiplier > 0) {
      sfx.cash();
      haptic("success");
      toast(`+${fmt(data.payout)} сапов`);
    } else {
      sfx.boom();
      haptic("error");
      toast("Пустой сектор");
    }
    $("wheelHint").textContent = data.multiplier > 0
      ? `Сектор ${fmtMult(data.multiplier)} — выигрыш ${fmt(data.payout)}`
      : "Пустой сектор — ставка сгорела";
    renderAll();
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

function renderAll() {
  renderBalance();
  renderDaily();
  renderMines();
  renderControls();
  renderGrid();
  renderLadder();
  renderProfile();
  renderQuests();
  renderHistory();
    const topTab = document.querySelector("#view-top .tab.active");
    renderTop(topTab ? topTab.dataset.tab : "balance");
  renderFair();
}

/* ---------- actions ---------- */

async function loadState() {
  const data = await api("/api/state");
  state.user = data.user;
  state.botUsername = data.bot_username || "";
  state.settings = data.settings || state.settings;
  state.isAdmin = !!data.is_admin;
  state.quests = data.quests || state.quests;
  const adminNav = $("adminNav");
  if (adminNav) adminNav.hidden = !state.isAdmin;
  state.referrals = data.referrals;
  state.leaderboard = {
    by_balance: data.leaderboard || [],
    by_multiplier: state.leaderboard.by_multiplier || [],
    me: data.user.id,
  };
  state.history = data.history || [];
  state.fair = data.fair;
  state.round = data.active_round;
  if (state.round) {
    state.bet = state.round.bet;
    state.mines = state.round.mines;
  }
  renderAll();
}

async function openCell(index) {
  if (!state.round || state.round.status !== "active") return;
  if (state.round.opened.includes(index)) return;
  haptic();
  try {
    const data = await api("/api/game/open", { cell: index });
    if (data.lost) {
      state.round = {
        ...state.round,
        status: "lost",
        mine_positions: data.mine_positions,
        multiplier: data.multiplier,
      };
      state.user.balance = data.balance;
      renderAll();
      const grid = $("grid");
      grid.classList.add("shake");
      setTimeout(() => grid.classList.remove("shake"), 420);
      sfx.boom();
      haptic("error");
      modal("💥", "Мина!", `Ставка ${fmt(state.round.bet)} сапов сгорела. Попробуешь ещё?`, "Ещё раз");
      await refreshMeta();
      return;
    }
    state.round = {
      ...state.round,
      opened: data.opened,
      multiplier: data.multiplier,
      status: data.status,
      payout: data.payout,
      next_chance: data.next_chance,
      mine_positions: data.mine_positions || state.round.mine_positions,
    };
    state.user.balance = data.balance;
    if (data.finished) sfx.cash(); else sfx.open();
    renderAll();
    if (data.finished) {
      haptic("success");
      modal("💎", "Поле очищено!", `Ты забрал ${fmt(data.payout)} сапов с множителем ${fmtMult(data.multiplier)}.`, "Ещё раз");
      await refreshMeta();
    }
  } catch (e) {
    toast(e.message);
  }
}

async function startGame() {
  const minBet = state.settings.min_bet || 10;
  const maxBet = state.settings.max_bet || 100000;
  const bet = Math.max(minBet, Math.min(maxBet, parseInt($("betInput").value || "0", 10) || 0));
  state.bet = bet;
  state.lastBet = bet;
  try {
    const data = await api("/api/game/start", { bet, mines: state.mines });
    state.round = data.round;
    state.user.balance = data.balance;
    haptic("success");
    renderAll();
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

async function cashout() {
  if (!state.round) return;
  try {
    const data = await api("/api/game/cashout");
    state.user.balance = data.balance;
    state.round = {
      ...state.round,
      status: "cashed",
      multiplier: data.multiplier,
      payout: data.payout,
      mine_positions: data.mine_positions,
    };
    sfx.cash();
    haptic("success");
    renderAll();
    modal("💰", "Забрано!", `${fmt(data.payout)} сапов на множителе ${fmtMult(data.multiplier)}.`, "Продолжить");
    await refreshMeta();
  } catch (e) {
    toast(e.message);
  }
}

async function claimDaily() {
  try {
    const data = await api("/api/daily");
    state.user.balance = data.balance;
    state.user.daily_ready = false;
    haptic("success");
    renderAll();
    toast(`Бонус +${fmt(data.amount)} сапов`);
    await refreshMeta();
  } catch (e) {
    toast(e.message);
  }
}

async function refreshMeta() {
  setTimeout(() => {
    loadState().catch(() => {});
  }, 250);
}

/* ---------- events ---------- */

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "top") loadTop();
  if (name === "history") loadHistory();
  if (name === "admin") loadAdmin();
}

async function loadTop() {
  try {
    const data = await api("/api/leaderboard");
    state.leaderboard.by_balance = data.by_balance;
    state.leaderboard.by_multiplier = data.by_multiplier;
    state.leaderboard.me = data.me;
  const topTab = document.querySelector("#view-top .tab.active");
  renderTop(topTab ? topTab.dataset.tab : "balance");
  } catch (e) {}
}

async function loadHistory() {
  try {
    const data = await api("/api/history");
    state.history = data.items;
    renderHistory();
  } catch (e) {}
}

function bind() {
  document.querySelectorAll(".nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );

  document.querySelectorAll("#view-top .tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll("#view-top .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      renderTop(tab.dataset.tab);
    })
  );

  document.querySelectorAll("#minesChips .chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      if (state.round && state.round.status === "active") return;
      state.mines = Number(chip.dataset.mines);
      renderMines();
      renderControls();
    })
  );

  $("minesSlider").addEventListener("input", (e) => {
    if (state.round && state.round.status === "active") return;
    state.mines = Number(e.target.value);
    renderMines();
    renderControls();
  });

  $("betInput").addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10) || 0;
    state.bet = v;
    renderControls();
  });

  document.querySelectorAll("[data-bet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      if (state.round && state.round.status === "active") return;
      const input = $("betInput");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.bet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = Math.max(state.user ? state.user.balance : 1000, 10);
      if (mode === "repeat") v = state.lastBet || v;
      v = Math.max(state.settings.min_bet || 10,
                   Math.min(state.settings.max_bet || 100000, v));
      input.value = v;
      state.bet = v;
      haptic();
      renderControls();
    })
  );

  $("ctaBtn").addEventListener("click", () => {
    if (state.round && state.round.status === "active") cashout();
    else startGame();
  });

  $("dailyBtn").addEventListener("click", () => {
    if (state.user && state.user.daily_ready) claimDaily();
    else toast("Бонус уже получен. Возвращайся позже!");
  });

  $("soundBtn").addEventListener("click", () => {
    state.sound = !state.sound;
    try {
      localStorage.setItem("saper_sound", state.sound ? "1" : "0");
    } catch (e) {}
    $("soundBtn").textContent = state.sound ? "🔊" : "🔇";
    if (state.sound) sfx.open();
    toast(state.sound ? "Звук включён" : "Звук выключен");
  });

  $("modalBtn").addEventListener("click", () => {
    $("modal").classList.remove("show");
    state.round = null;
    renderAll();
  });

  $("copyRef").addEventListener("click", async () => {
    const link = $("refLink").textContent;
    try {
      await navigator.clipboard.writeText(link);
      toast("Ссылка скопирована");
    } catch (e) {
      toast(link);
    }
  });

  $("saveSeed").addEventListener("click", async () => {
    try {
      const data = await api("/api/fairness/rotate", { client_seed: $("clientSeed").value.trim() });
      state.fair = { seed_hash: data.seed_hash, client_seed: data.client_seed, nonce: data.nonce };
      $("revealedSeed").innerHTML = `Предыдущий серверный seed раскрыт:<br><code>${data.revealed_server_seed}</code><br>Хеш: <code>${data.revealed_hash}</code>`;
      renderFair();
      toast("Seed обновлён");
    } catch (e) {
      toast(e.message);
    }
  });

  document.querySelectorAll("#adminTabs .tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll("#adminTabs .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll(".admin-pane").forEach((pane) => {
        pane.classList.toggle("active", pane.id === "pane-" + tab.dataset.atab);
      });
    })
  );

  $("adminSearch").addEventListener("input", (e) => {
    clearTimeout(e.target._t);
    e.target._t = setTimeout(() => adminSearch(e.target.value.trim()), 350);
  });

  $("adminUsers").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const row = btn.closest(".admin-row");
    if (!row) return;
    const userId = Number(row.dataset.id);
    const input = row.querySelector(".mini-input");
    const amount = Math.max(1, Number(input ? input.value : 0) || 0);
    const act = btn.dataset.act;
    if (act === "grant") adminBalance(userId, amount);
    else if (act === "take") adminBalance(userId, -amount);
    else if (act === "ban") adminBan(userId, true);
    else if (act === "unban") adminBan(userId, false);
  });

  $("saveSettings").addEventListener("click", saveAdminSettings);

  document.querySelectorAll("#gameSwitch .gs-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchGame(btn.dataset.game)));

  document.querySelectorAll("[data-pick]").forEach((btn) =>
    btn.addEventListener("click", () => playDice(btn.dataset.pick)));

  document.querySelectorAll("[data-dbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("diceBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.dbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  document.querySelectorAll("[data-wbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("wheelBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.wbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  $("wheelSpin").addEventListener("click", spinWheel);

  $("questsList").addEventListener("click", async (e) => {
    const btn = e.target.closest(".quest-claim");
    if (!btn || btn.disabled) return;
    try {
      const data = await api("/api/quests/claim", { key: btn.dataset.quest });
      state.quests = data.quests || state.quests;
      state.user.balance = data.balance;
      sfx.cash();
      toast(`Награда +${fmt(data.reward)} сапов`);
      renderAll();
    } catch (err) {
      toast(err.message);
    }
  });
}

async function init() {
  if (tg) {
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("#0e1016");
      tg.setBackgroundColor("#0e1016");
    } catch (e) {}
  }
  try {
    const saved = localStorage.getItem("saper_sound");
    if (saved !== null) state.sound = saved === "1";
  } catch (e) {}
  const soundBtn = $("soundBtn");
  if (soundBtn) soundBtn.textContent = state.sound ? "🔊" : "🔇";

  bind();
  renderControls();
  try {
    await loadState();
  } catch (e) {
    toast(e.message === "unauthorized" ? "Откройте игру через Telegram" : e.message);
  }
}

init();
