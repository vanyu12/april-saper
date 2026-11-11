const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

const state = {
  user: null,
  account: null,
  chatUrl: "",
  promos: [],
  round: null,
  mines: 3,
  bet: 50,
  lastBet: 50,
  autoTarget: 0,
  settings: { min_bet: 10, max_bet: 100000, min_mines: 1, max_mines: 24, daily_bonus: 500, maintenance: 0 },
  isAdmin: false,
  isSuper: false,
  sound: true,
  game: "mines",
  quests: [],
  shop: { items: [], bundles: [], donate: [], prefixes: [], inventory: {}, gmpoint: 0 },
  leaderboard: { by_balance: [], by_multiplier: [], by_level: [], me: 0 },
  levels: { level: 1, pending: 0, pending_levels: [], next: 2, to_next: 0 },
  history: [],
  achievements: [],
  referrals: { total: 0, active: 0 },
  invites: { total: 0, ladder: [] },
  sponsors: [],
  deposits: { plans: [], items: [], savings: null, min: 100, max: 1000000 },
  spin: { prizes: [] },
  gamesHub: { players: {}, last: null },
  depositPlan: 0,
  fair: { seed_hash: "", client_seed: "", nonce: 0 },
  started: false,
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat("ru-RU").format(Math.round(n));
const fmtMult = (m) => "×" + Number(m).toFixed(2).replace(".", ",");

function awardsNote(awards) {
  if (!awards || !awards.length) return "";
  const sum = awards.reduce((total, item) => total + (item.reward || 0), 0);
  const titles = awards.map((item) => item.title).join(", ");
  return ` · ${titles} +${fmt(sum)} mCoin`;
}

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

function confetti() {
  const canvas = $("confetti");
  if (!canvas) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.floor(window.innerWidth * dpr);
  canvas.height = Math.floor(window.innerHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const colors = ["#7c5cff", "#2ee6a8", "#ffb02e", "#ff5d7a", "#f4f6ff"];
  const parts = [];
  for (let i = 0; i < 90; i++) {
    parts.push({
      x: window.innerWidth / 2 + (Math.random() - 0.5) * 180,
      y: window.innerHeight * 0.42 + (Math.random() - 0.5) * 60,
      vx: (Math.random() - 0.5) * 8,
      vy: -Math.random() * 10 - 2,
      size: 4 + Math.random() * 7,
      color: colors[Math.floor(Math.random() * colors.length)],
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.35,
      life: 70 + Math.floor(Math.random() * 45),
    });
  }
  let frame = 0;
  const tick = () => {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    let alive = false;
    for (const p of parts) {
      if (p.life <= 0) continue;
      alive = true;
      p.life -= 1;
      p.vy += 0.3;
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.globalAlpha = Math.max(0, Math.min(1, p.life / 35));
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.62);
      ctx.restore();
    }
    frame += 1;
    if (alive && frame < 170) requestAnimationFrame(tick);
    else ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
  };
  requestAnimationFrame(tick);
}

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2200);
}

function modal(emoji, title, text, btnText) {
  if (!$("modal")) {
    toast(`${title} — ${text}`);
    return;
  }
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
  try {
    const token = localStorage.getItem("saper_token");
    if (token) headers["X-Auth-Token"] = token;
  } catch (e) {}
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
  if ($("gmpValue")) $("gmpValue").textContent = fmt(state.user ? (state.user.gmpoint || 0) : 0);
  if ($("statGmpoint")) $("statGmpoint").textContent = fmt(state.user ? (state.user.gmpoint || 0) : 0);
}

function renderDaily() {
  const btn = $("dailyBtn");
  const ready = state.user && state.user.daily_ready;
  btn.classList.toggle("ready", !!ready);
  btn.title = ready
    ? `Забрать ${fmt(state.user.daily_amount || 300)} mCoin`
    : "Бонус уже получен";
}

function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function renderBonus() {
  const u = state.user;
  if (!u) return;
  const hourly = $("hourlyCard");
  if (hourly) {
    hourly.classList.toggle("ready", !!u.hourly_ready);
    $("hourlyBadge").textContent = u.hourly_ready ? "Забрать" : fmtTime(u.hourly_in);
    $("hourlyHint").textContent = "раз в час · +" + fmt(u.hourly_amount || 100);
  }
  const spin = $("spinCard");
  if (spin) {
    spin.classList.toggle("ready", !!u.spin_ready);
    $("spinBadge").textContent = u.spin_ready ? "Крутить" : fmtTime(u.spin_in);
    $("spinHint").textContent = "День " + (u.spin_day || 1);
  }
  const hint = $("dailySpinHint");
  if (hint) {
    hint.textContent = u.spin_ready
      ? "Доступна прокрутка · День " + (u.spin_day || 1)
      : "Следующая через " + fmtTime(u.spin_in);
  }
  const btn = $("dailySpinBtn");
  if (btn) btn.disabled = !u.spin_ready;
}

function renderTasks() {
  const box = $("inviteList");
  if (box) {
    const invites = state.invites || { total: 0, ladder: [] };
    const ladder = invites.ladder || [];
    box.innerHTML = ladder.length
      ? ladder
          .map((item) => {
            const label = item.claimed
              ? "Получено"
              : item.done
                ? `Забрать +${fmt(item.reward)}`
                : `${Math.min(invites.total, item.step)} / ${item.step}`;
            return `<div class="row${item.done && !item.claimed ? " ready" : ""}">
              <div class="row-icon">👥</div>
              <div class="row-main">
                <div class="row-title">Пригласи ${item.step} друзей</div>
                <div class="row-sub">${fmt(item.reward)} mCoin · приглашено ${invites.total}</div>
              </div>
              <button class="chip-btn" data-step="${item.step}"
                ${item.claimed || !item.done ? "disabled" : ""}>${label}</button>
            </div>`;
          })
          .join("")
      : '<div class="empty">Ступени появятся позже</div>';
  }
  const sponsors = state.sponsors || [];
  const card = $("sponsorCard");
  if (card) {
    card.hidden = !sponsors.length;
    $("sponsorList").innerHTML = sponsors
      .map((s) => `<div class="row">
        <div class="row-icon">📣</div>
        <div class="row-main">
          <div class="row-title">Подписка на ${escapeHtml(s.channel)}</div>
          <div class="row-sub">+${fmt(s.reward)} mCoin</div>
        </div>
        <button class="chip-btn" data-channel="${escapeHtml(s.channel.replace("@", ""))}"
          ${s.claimed ? "disabled" : ""}>${s.claimed ? "Получено" : "Перейти"}</button>
      </div>`)
      .join("");
  }
}

function renderBank() {
  const deposits = state.deposits || { plans: [], items: [], savings: null };
  const plans = deposits.plans || [];
  if (!state.depositPlan && plans.length) state.depositPlan = plans[0].days;
  const box = $("depositPlans");
  if (box) {
    box.innerHTML = plans
      .map((p) => `<button class="plan${p.days === state.depositPlan ? " active" : ""}" data-days="${p.days}">
        <b>${p.days} дн.</b><span>${String(p.percent).replace(".", ",")}%</span>
      </button>`)
      .join("");
  }
  updateDepositHint();
  const savings = deposits.savings;
  const sbox = $("savingsCard");
  if (sbox) {
    sbox.innerHTML = savings
      ? `<div class="row">
          <div class="row-main">
            <div class="row-title">${fmt(savings.amount)} mCoin</div>
            <div class="row-sub">начислено +${fmt(savings.accrued)} · 0,1% в день</div>
          </div>
          <div class="row-value">${fmt(savings.amount + savings.accrued)}</div>
        </div>`
      : '<div class="empty">Счёт пуст — пополните</div>';
  }
  const close = $("savingsClose");
  if (close) close.hidden = !savings;
  const list = $("depositList");
  if (list) {
    const items = deposits.items || [];
    list.innerHTML = items.length
      ? items
          .map((d) => `<div class="row">
            <div class="row-icon ${d.ready ? "win" : "lose"}">🏦</div>
            <div class="row-main">
              <div class="row-title">${fmt(d.amount)} mCoin · ${String(d.rate_bps / 100).replace(".", ",")}%</div>
              <div class="row-sub">${d.ready
                ? "готов к закрытию"
                : "закроется " + new Date(d.ends_at * 1000).toLocaleDateString("ru-RU")}</div>
            </div>
            <button class="chip-btn" data-dep="${d.id}" ${d.ready ? "" : "disabled"}>
              ${d.ready ? "Забрать " + fmt(d.payout) : "Ждём"}
            </button>
          </div>`)
          .join("")
      : '<div class="empty">Пока нет вкладов</div>';
  }
}

function updateDepositHint() {
  const hint = $("depositHint");
  if (!hint) return;
  const deposits = state.deposits || { plans: [] };
  const plans = deposits.plans || [];
  const plan = plans.find((p) => p.days === state.depositPlan) || plans[0];
  if (!plan) return;
  const input = $("depositAmount");
  const amount = Math.max(0, parseInt(input && input.value ? input.value : "0", 10) || 0);
  const interest = Math.floor((amount * plan.rate_bps) / 10000);
  hint.textContent = `${plan.days} дн. · ${String(plan.percent).replace(".", ",")}% → вернут ${fmt(amount + interest)} mCoin`;
}

const HUB_GAMES = [
  ["mines", "💣", "Сапёр", "Открывай клетки и забирай"],
  ["dice", "🎲", "Кости", "Чёт или нечёт ×1,96"],
  ["wheel", "🎡", "Колесо", "Шесть секторов до ×3,2"],
  ["crash", "📈", "Краш", "Забери до краша"],
  ["coinflip", "🪙", "Орёл и решка", "Монета 50/50 ×1,96"],
  ["blackjack", "♠️", "21", "Блэкджек против дилера"],
  ["basket", "🏀", "Баскет", "Один бросок в кольцо ×2,4"],
];

function renderGamesHub() {
  const hub = state.gamesHub || { players: {}, last: null };
  const lastBox = $("hubLast");
  if (lastBox) {
    const meta = HUB_GAMES.find((g) => g[0] === hub.last);
    lastBox.innerHTML = `<div class="hub-last-sub">Ваша последняя игра</div>
      <div class="hub-last-title">${meta ? meta[1] + " " + meta[2] : "Пока пусто"}</div>`;
  }
  const grid = $("hubGrid");
  if (grid) {
    grid.innerHTML = HUB_GAMES.map(([key, icon, title, desc]) => {
      const players = (hub.players && hub.players[key]) || 0;
      return `<button class="hub-card" data-hub-game="${key}">
        <span class="hub-icon">${icon}</span>
        <b>${title}</b>
        <small>${desc}</small>
        <span class="hub-players">${fmt(players)} играет</span>
      </button>`;
    }).join("");
  }
}

const SPIN_COLORS = ["#7c5cff", "#2ee6a8", "#ffb02e", "#ff5d7a",
  "#3d8bff", "#b06bff", "#36d1c4", "#ff8a3d"];
let dailySpinAngle = 0;

function renderDailySpin() {
  const disc = $("dailySpinDisc");
  const legend = $("dailySpinLegend");
  const prizes = (state.spin && state.spin.prizes) || [];
  if (!disc || !prizes.length) return;
  const step = 360 / prizes.length;
  const stops = prizes.map((p, i) => {
    const color = SPIN_COLORS[i % SPIN_COLORS.length];
    return `${color} ${i * step}deg ${(i + 1) * step}deg`;
  });
  disc.style.background = `conic-gradient(${stops.join(", ")})`;
  if (legend) {
    legend.innerHTML = prizes
      .map((p, i) => `<span class="wheel-chip"><i style="background:${SPIN_COLORS[i % SPIN_COLORS.length]}"></i>${escapeHtml(p.title)}</span>`)
      .join("");
  }
}

async function claimHourly() {
  try {
    const data = await api("/api/bonus/hourly");
    state.user = data.user;
    state.user.balance = data.balance;
    sfx.coin();
    haptic("success");
    renderAll();
    toast(`Бонус +${fmt(data.amount)} mCoin${awardsNote(data.awards)}`);
  } catch (e) {
    toast(e.message);
  }
}

async function spinDaily() {
  const btn = $("dailySpinBtn");
  const disc = $("dailySpinDisc");
  if (!state.user || !state.user.spin_ready || !disc) return;
  btn.disabled = true;
  try {
    const data = await api("/api/spin");
    state.user = data.user;
    state.user.balance = data.balance;
    const prizes = (state.spin && state.spin.prizes) || [];
    const step = 360 / Math.max(1, prizes.length);
    const mid = (data.index + 0.5) * step;
    const delta = ((-mid - (dailySpinAngle % 360)) % 360 + 360) % 360;
    dailySpinAngle += 360 * 5 + delta;
    disc.style.transform = `rotate(${dailySpinAngle}deg)`;
    await new Promise((resolve) => setTimeout(resolve, 3600));
    sfx.cash();
    haptic("success");
    renderAll();
    toast("Приз: " + data.prize.title + awardsNote(data.awards));
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = !(state.user && state.user.spin_ready);
  }
}

async function claimInvite(step) {
  try {
    const data = await api("/api/invites/claim", { step });
    sfx.cash();
    haptic("success");
    toast(`Награда +${fmt(data.reward)} mCoin`);
    await loadState();
  } catch (e) {
    toast(e.message);
  }
}

async function claimSponsor(channel) {
  if (channel) window.open("https://t.me/" + channel, "_blank");
  try {
    const data = await api("/api/sponsors/claim", { channel });
    sfx.cash();
    haptic("success");
    toast(`Спонсор +${fmt(data.reward)} mCoin${awardsNote(data.awards)}`);
    await loadState();
  } catch (e) {
    toast(e.message);
  }
}

function depositAmountValue() {
  const input = $("depositAmount");
  return parseInt(input && input.value ? input.value : "0", 10) || 0;
}

async function depositCreate() {
  try {
    const data = await api("/api/deposits/create",
      { kind: "fixed", days: state.depositPlan, amount: depositAmountValue() });
    state.user.balance = data.balance;
    state.deposits = data.deposits;
    haptic("success");
    renderAll();
    toast("Депозит открыт" + awardsNote(data.awards));
  } catch (e) {
    toast(e.message);
  }
}

async function savingsPut() {
  try {
    const data = await api("/api/deposits/create",
      { kind: "savings", amount: depositAmountValue() });
    state.user.balance = data.balance;
    state.deposits = data.deposits;
    haptic("success");
    renderAll();
    toast("Счёт пополнен" + awardsNote(data.awards));
  } catch (e) {
    toast(e.message);
  }
}

async function savingsClose() {
  const savings = state.deposits && state.deposits.savings;
  if (savings) await depositClose(savings.id);
}

async function depositClose(id) {
  try {
    const data = await api("/api/deposits/close", { id });
    state.user.balance = data.balance;
    state.deposits = data.deposits;
    haptic("success");
    renderAll();
    toast(`Закрыто, +${fmt(data.payout)} mCoin${awardsNote(data.awards)}`);
  } catch (e) {
    toast(e.message);
  }
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
    cta.textContent = round.opened.length ? `Забрать ${fmt(payout)} mCoin` : "Открой первую клетку";
    cta.classList.add("cashout");
    cta.disabled = round.opened.length === 0;
    const auto = round.auto_target ? ` · авто ${fmtMult(round.auto_target)}` : "";
    $("hint").textContent = `Мин: ${round.mines} · ставка ${fmt(round.bet)}${auto}`;
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
  if ($("autoTarget")) $("autoTarget").value = String(state.autoTarget || 0);
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
  if ($("myId")) $("myId").textContent = u.id;
  $("avatar").textContent = (u.first_name || u.username || "И").trim().charAt(0).toUpperCase();
  const prefBox = $("profilePrefix");
  if (prefBox) {
    if (u.prefix_title) {
      const bonus = u.prefix_bonus ? ` · +${Math.round(u.prefix_bonus * 100)}% к выигрышу` : "";
      prefBox.hidden = false;
      prefBox.textContent = `${u.prefix_title}${bonus}`;
      prefBox.style.color = u.prefix_color || "#e5e7eb";
      prefBox.style.borderColor = (u.prefix_color || "#e5e7eb") + "66";
    } else {
      prefBox.hidden = true;
    }
  }
  $("statGames").textContent = fmt(u.games_played);
  $("statWins").textContent = fmt(u.games_won);
  $("statBest").textContent = fmtMult(u.best_multiplier || 1);
  $("refTotal").textContent = state.referrals.total || 0;
  $("refActive").textContent = state.referrals.active || 0;
  $("refLink").textContent = botLink(u.ref_code);

  $("levelBadge").textContent = u.level || 1;
  $("levelTitle").textContent = `${u.level_title || "Новобранец"} · уровень ${u.level || 1}`;
  $("levelSub").textContent = `${fmt(u.level_into || 0)} / ${fmt(u.level_need || 100)} XP`;
  $("levelXp").textContent = `${fmt(u.xp || 0)} XP`;
  $("xpFill").style.width = Math.max(0, Math.min(100, u.level_percent || 0)) + "%";

  const levels = state.levels || {};
  const claimBtn = $("claimLevels");
  const rewardHint = $("levelRewardHint");
  if (claimBtn && rewardHint) {
    const pending = Number(levels.pending || 0);
    claimBtn.hidden = pending <= 0;
    claimBtn.textContent = `🎁 Забрать награды (${pending})`;
    if (pending > 0) {
      rewardHint.textContent = `Доступно наград за уровни: ${pending}`;
    } else {
      const reward = levels.next_reward || {};
      const bits = [];
      if (reward.coins) bits.push(`+${fmt(reward.coins)} mCoin`);
      if (reward.gmpoint) bits.push(`+${reward.gmpoint} GMPOINT`);
      if (reward.lootbox) bits.push(`+${reward.lootbox} лутбокс`);
      rewardHint.textContent = bits.length
        ? `До ${levels.next || (u.level || 1) + 1} ур.: ${bits.join(" · ")}`
        : "";
    }
  }

  if ($("chatLink")) $("chatLink").hidden = !state.chatUrl;

  const logged = $("accountLogged");
  const form = $("accountForm");
  if (logged && form) {
    const acc = state.account;
    logged.hidden = !acc;
    form.hidden = !!acc;
    if (acc) $("accountLogin").textContent = acc.login;
  }

  const ach = state.achievements || [];
  $("achievements").innerHTML = ach.length
    ? ach
        .map((a) => {
          const cls = a.claimed ? "done" : a.done ? "ready" : "locked";
          return `<div class="ach ${cls}">
            <div class="ach-icon">${a.icon}</div>
            <div class="ach-name">${escapeHtml(a.title)}<span class="ach-desc">${escapeHtml(a.desc)} · ${a.progress}/${a.target}</span></div>
            <div class="ach-reward">${a.claimed ? "✓" : "+" + fmt(a.reward)}</div>
          </div>`;
        })
        .join("")
    : '<div class="empty">Пока нет достижений</div>';
}

function botLink(code) {
  const username = state.botUsername || (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && window.BOT_USERNAME) || "AprilSaperBot";
  return `https://t.me/${username}?start=${code}`;
}

function saveAuthToken(token) {
  try {
    if (token) localStorage.setItem("saper_token", token);
    else localStorage.removeItem("saper_token");
  } catch (e) {}
}

async function accountRegister() {
  const login = ($("accountLoginInput") && $("accountLoginInput").value || "").trim();
  const password = ($("accountPasswordInput") && $("accountPasswordInput").value) || "";
  try {
    const data = await api("/api/auth/register", { login, password });
    state.account = { login: data.login };
    toast("Аккаунт создан");
    renderProfile();
  } catch (e) {
    toast(e.message);
  }
}

async function accountLogin() {
  const loginInput = $("accountLoginInput");
  const passInput = $("accountPasswordInput");
  const login = ((loginInput && loginInput.value) || ($("gateLogin") && $("gateLogin").value) || "").trim();
  const password = (passInput && passInput.value) || ($("gatePassword") && $("gatePassword").value) || "";
  const remember = $("accountRemember") ? $("accountRemember").checked
    : ($("gateRemember") ? $("gateRemember").checked : true);
  try {
    const data = await api("/api/auth/login", { login, password, remember });
    saveAuthToken(data.token);
    const gate = $("authGate");
    if (gate) gate.hidden = true;
    toast("Вход выполнен");
    await loadState();
  } catch (e) {
    toast(e.message);
  }
}

async function accountLogout() {
  try { await api("/api/auth/logout"); } catch (e) {}
  saveAuthToken(null);
  state.account = null;
  toast("Это устройство отвязано");
  renderProfile();
}

function showAuthGate() {
  const gate = $("authGate");
  if (gate) gate.hidden = false;
}

function renderPromos() {
  const box = $("promoList");
  if (!box) return;
  const items = state.promos || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Промокодов пока нет</div>';
    return;
  }
  box.innerHTML = items.map((p) => {
    const used = p.max_uses ? `${p.used}/${p.max_uses}` : `${p.used} / ∞`;
    const exp = p.expires_at
      ? new Date(p.expires_at * 1000).toLocaleDateString("ru-RU")
      : "бессрочно";
    const cur = p.currency === "gmpoint" ? "G" : "◈";
    const state = Number(p.active) ? "" : " · выключен";
    return `<div class="row" data-code="${escapeHtml(p.code)}">
      <div class="row-main">
        <div class="row-title">${escapeHtml(p.code)} · +${fmt(p.amount)} ${cur}</div>
        <div class="row-sub">Активаций: ${used} · до ${exp}${state}</div>
      </div>
      <button class="chip-btn" data-act="del-promo">Удалить</button>
    </div>`;
  }).join("");
}

async function loadPromos() {
  try {
    const data = await api("/api/admin/promo/list");
    state.promos = data.items || [];
    renderPromos();
  } catch (e) {
    toast(e.message);
  }
}

async function createPromo() {
  try {
    const data = await api("/api/admin/promo/create", {
      code: ($("promoCode").value || "").trim(),
      amount: Number($("promoAmount").value || 0),
      max_uses: Number($("promoMax").value || 0),
      days: Number($("promoDays").value || 0),
    });
    $("promoHint").textContent = `Создан ${data.code} на +${fmt(data.amount)} GMPOINT`;
    $("promoCode").value = "";
    await loadPromos();
  } catch (e) {
    $("promoHint").textContent = e.message;
  }
}

async function deletePromo(code) {
  try {
    await api("/api/admin/promo/delete", { code });
    toast("Промокод удалён");
    await loadPromos();
  } catch (e) {
    toast(e.message);
  }
}

async function redeemPromo() {
  const code = ($("promoRedeemInput").value || "").trim();
  if (!code) return;
  try {
    const data = await api("/api/promo/redeem", { code });
    state.user.gmpoint = data.gmpoint;
    toast(`+${fmt(data.amount)} GMPOINT`);
    $("promoRedeemInput").value = "";
    sfx.cash();
    renderAll();
  } catch (e) {
    toast(e.message);
  }
}

function toggleDrawer(show) {
  const drawer = $("drawer");
  if (!drawer) return;
  drawer.hidden = !show;
}

function applyTheme(name) {
  document.body.classList.remove("theme-neon", "theme-gold");
  if (name === "neon") document.body.classList.add("theme-neon");
  if (name === "gold") document.body.classList.add("theme-gold");
  try { localStorage.setItem("saper_theme", name); } catch (e) {}
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
          <div class="row-title">${fmt(r.bet)} mCoin · ${r.mines} мин</div>
          <div class="row-sub">${opened} клеток · ${date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</div>
        </div>
        <div class="row-value ${win ? "plus" : "minus"}">${win ? "+" + fmt(r.payout) : "−" + fmt(r.bet)}</div>
      </div>`;
    })
    .join("");
}

const PREFIX_META = {
  dracula: { title: "Дракула", color: "#e11d48" },
  owner: { title: "Владелец", color: "#ff3b30" },
  admin_prefix: { title: "Админ", color: "#ff9500" },
  moderator_prefix: { title: "Модератор", color: "#34c759" },
  tester_prefix: { title: "Тестер", color: "#64d2ff" },
  legend: { title: "Легенда", color: "#ffb020" },
  april: { title: "Апрель", color: "#ff5c8a" },
  king: { title: "Король", color: "#f7c948" },
  veteran: { title: "Ветеран", color: "#7c5cff" },
  saper: { title: "Сапёр", color: "#2ee6a8" },
  gmpoint: { title: "GMPOINT", color: "#ffd166" },
  sapper_10: { title: "Взрывотехник", color: "#57c7ff" },
  master_25: { title: "Гроссмейстер", color: "#c084fc" },
  immortal_50: { title: "Бессмертный", color: "#ff6b6b" },
};

function prefixBadge(key) {
  const meta = PREFIX_META[key];
  if (!meta) return "";
  return ` <span class="prefix-badge" style="color:${meta.color};border-color:${meta.color}55">${escapeHtml(meta.title)}</span>`;
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
      photo: u.photo_url,
    }));
  } else if (tab === "lvl") {
    rows = (state.leaderboard.by_level || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: `⭐ ${u.level || 1} ур. · ${fmt(u.xp || 0)} XP`,
      id: u.user_id,
      photo: u.photo_url,
      prefix: u.prefix,
    }));
  } else {
    rows = (state.leaderboard.by_balance || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: fmt(u.balance) + " mCoin",
      id: u.user_id,
      photo: u.photo_url,
      prefix: u.prefix,
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
        ${r.photo
          ? `<img class="row-avatar" src="${escapeHtml(r.photo)}" alt="">`
          : `<span class="row-avatar letter">${escapeHtml(String(r.name).replace("@", "").charAt(0).toUpperCase() || "?")}</span>`}
        <div class="row-main"><div class="row-title"><span class="top-place">${medals[r.place - 1] || r.place}</span> ${escapeHtml(r.name)}${prefixBadge(r.prefix)}</div></div>
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

const ADMIN_ITEMS = [
  ["insurance", "Страховка"],
  ["charm", "Талисман"],
  ["double_daily", "Двойной бонус"],
  ["relic_mines", "Реликвия сапёра"],
  ["relic_dice", "Кости судьбы"],
  ["relic_wheel", "Колесо фортуны"],
  ["relic_crash", "Краш-модуль"],
  ["theme_neon", "Неоновая тема"],
  ["theme_gold", "Золотые клетки"],
  ["gold_pick", "Золотая кирка"],
  ["lootbox", "Кейс удачи"],
];

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

function renderAdminEconomy() {
  const economy = state.admin && state.admin.economy;
  if (!economy) return;
  const cards = [
    ["Игроков", fmt(economy.players)],
    ["В обороте", fmt(economy.balance)],
    ["В депозитах", fmt(economy.deposits_locked)],
    ["Депозитов", fmt(economy.deposits_count)],
    ["Дуэлей", fmt(economy.duels)],
    ["Достижений", fmt(economy.achievements)],
    ["Забанено", fmt(economy.banned)],
    ["Дуэлей сыграно", fmt(economy.duels_finished)],
  ];
  $("adminEconomy").innerHTML = cards
    .map(([label, value]) =>
      `<div class="stat"><span class="stat-value">${value}</span><span class="stat-label">${label}</span></div>`)
    .join("");
}

function renderAdminDuels() {
  const box = $("adminDuels");
  const items = (state.admin && state.admin.duels) || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Дуэлей пока нет</div>';
    return;
  }
  const labels = {
    pending: "ждёт ответа",
    finished: "завершена",
    declined: "отклонена",
    cancelled: "отменена",
    expired: "истекла",
  };
  box.innerHTML = items
    .map((d) => {
      const winner = d.winner_id
        ? (Number(d.winner_id) === Number(d.challenger_id) ? d.challenger : d.opponent)
        : "—";
      const rolls = d.challenger_roll != null
        ? ` · ${d.challenger_roll}:${d.opponent_roll}`
        : "";
      return `<div class="row">
        <div class="row-main">
          <div class="row-title">${escapeHtml(d.challenger)} vs ${escapeHtml(d.opponent)}</div>
          <div class="row-sub">${fmt(d.bet)} mCoin · ${labels[d.status] || d.status}${rolls}</div>
        </div>
        <div class="row-value">${escapeHtml(winner)}</div>
      </div>`;
    })
    .join("");
}

function renderAdminGames() {
  const box = $("adminGames");
  const items = (state.admin && state.admin.games) || [];
  if (!items.length) {
    box.innerHTML = '<div class="empty">Статистики пока нет</div>';
    return;
  }
  box.innerHTML = items
    .map((g) => `<div class="row">
      <div class="row-main">
        <div class="row-title">${escapeHtml(g.title)}</div>
        <div class="row-sub">партий ${fmt(g.rounds)} · оборот ${fmt(g.wagered)} · выплаты ${fmt(g.paid)}</div>
      </div>
      <div class="row-value">${g.rtp || 0}%</div>
    </div>`)
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
          <div class="row-sub">${escapeHtml(r.label || ((r.mines || 0) + " мин"))} · ${fmtMult(r.multiplier)} · ${r.status}</div>
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
        <input class="mini-input" type="number" value="5" min="1" data-gmp>
        <button class="chip-btn" data-act="gmp">+G</button>
        <button class="chip-btn" data-act="gmp-minus">−G</button>
        <select class="mini-select" data-role="item">${ADMIN_ITEMS.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select>
        <button class="chip-btn" data-act="item">Выдать</button>
        <button class="chip-btn" data-act="${u.is_banned ? "unban" : "ban"}">${u.is_banned ? "Разбан" : "Бан"}</button>
        ${state.isSuper ? `<select class="mini-select" data-role="role">
          ${[["user", "Игрок"], ["tester", "Тестер"], ["moderator", "Модератор"],
             ["admin", "Админ"], ["owner", "Владелец"]]
            .map(([k, t]) => `<option value="${k}"${(u.role || "user") === k ? " selected" : ""}>${t}</option>`)
            .join("")}
        </select>
        <button class="chip-btn" data-act="role">Роль</button>` : ""}
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
  const games = settings.games || {};
  $("setGameMines").checked = games.mines !== false;
  $("setGameDice").checked = games.dice !== false;
  $("setGameWheel").checked = games.wheel !== false;
  $("setGameCrash").checked = games.crash !== false;
  $("setGameRoulette").checked = games.roulette !== false;
  $("setGameSlots").checked = games.slots !== false;
  $("setGameCoinflip").checked = games.coinflip !== false;
  $("setGameBlackjack").checked = games.blackjack !== false;
  $("setGameBasket").checked = games.basket !== false;
}

async function loadAdmin() {
  try {
    const data = await api("/api/admin/overview");
    state.admin = data;
    renderAdminStats();
    renderAdminEconomy();
    renderAdminDuels();
    renderAdminGames();
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

async function adminRole(userId, role) {
  try {
    await api("/api/admin/role", { user_id: userId, role });
    toast("Роль обновлена");
    await adminSearch($("adminSearch").value.trim());
  } catch (err) {
    toast(err.message);
  }
}

async function adminGmpoint(userId, value) {
  try {
    const data = await api("/api/admin/gmpoint", { user_id: userId, value });
    toast(`GMPOINT: ${fmt(data.gmpoint)}`);
    await adminSearch($("adminSearch").value.trim());
  } catch (err) {
    toast(err.message);
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

async function adminGrant(userId, item) {
  try {
    const data = await api("/api/admin/grant", { user_id: userId, item });
    toast(data.title + " × " + data.qty);
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
      game_mines: $("setGameMines").checked ? 1 : 0,
      game_dice: $("setGameDice").checked ? 1 : 0,
      game_wheel: $("setGameWheel").checked ? 1 : 0,
      game_crash: $("setGameCrash").checked ? 1 : 0,
      game_roulette: $("setGameRoulette").checked ? 1 : 0,
      game_slots: $("setGameSlots").checked ? 1 : 0,
      game_coinflip: $("setGameCoinflip").checked ? 1 : 0,
      game_blackjack: $("setGameBlackjack").checked ? 1 : 0,
    game_basket: $("setGameBasket").checked ? 1 : 0,
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

const GAMES = [
  { key: "mines", icon: "💣", title: "Сапёр", desc: "5×5 · до 24 мин" },
  { key: "dice", icon: "🎲", title: "Кости", desc: "Чёт или нечёт, ×1,96" },
  { key: "wheel", icon: "🎡", title: "Колесо", desc: "Секторы до ×3,2" },
  { key: "crash", icon: "📈", title: "Краш", desc: "Цель до ×10" },
  { key: "coinflip", icon: "🟡", title: "Орёл и решка", desc: "Монета 50/50, ×1,96" },
  { key: "blackjack", icon: "♠️", title: "21", desc: "Против дилера" },
  { key: "basket", icon: "🏀", title: "Баскет", desc: "Бросок в кольцо, ×2,4" },
];

function renderGameMenu() {
  const grid = $("gameMenuGrid");
  if (!grid) return;
  grid.innerHTML = GAMES.map((game) => {
    const active = state.game === game.key;
    return `<button class="game-menu-item${active ? " active" : ""}" data-game="${game.key}" type="button">
      <span class="gmi-icon">${game.icon}</span>
      <span class="gmi-text"><span class="gmi-title">${game.title}</span><span class="gmi-desc">${game.desc}</span></span>
      ${active ? '<span class="gmi-check">✓</span>' : ""}
    </button>`;
  }).join("");
}

function renderGameSwitch() {
  const game = GAMES.find((item) => item.key === state.game) || GAMES[0];
  if ($("gameEmoji")) $("gameEmoji").textContent = game.icon;
  if ($("gameName")) $("gameName").textContent = game.title;
  if ($("gameCount")) $("gameCount").textContent = `${GAMES.length} режимов`;
  renderGameMenu();
}

function openGameMenu() {
  const menu = $("gameMenu");
  if (!menu) return;
  renderGameMenu();
  menu.hidden = false;
  requestAnimationFrame(() => menu.classList.add("show"));
  if ($("gamePickerBtn")) $("gamePickerBtn").setAttribute("aria-expanded", "true");
  document.body.classList.add("game-menu-open");
}

function closeGameMenu() {
  const menu = $("gameMenu");
  if (!menu) return;
  menu.classList.remove("show");
  if ($("gamePickerBtn")) $("gamePickerBtn").setAttribute("aria-expanded", "false");
  document.body.classList.remove("game-menu-open");
  setTimeout(() => {
    if (!menu.classList.contains("show")) menu.hidden = true;
  }, 180);
}

function switchGame(name) {
  state.game = name;
  document.querySelectorAll(".game-pane").forEach((pane) =>
    pane.classList.toggle("active", pane.id === "game-pane-" + name));
  if (name === "wheel") renderWheel();
  if (name === "crash") renderCrashTarget();
  if (name === "blackjack") renderBlackjack();
  renderGameSwitch();
  closeGameMenu();
}

function clampBet(value) {
  const min = state.settings.min_bet || 10;
  const max = state.settings.max_bet || 100000;
  return Math.max(min, Math.min(max, Math.round(value || 0)));
}

const WHEEL_COLORS = ["#3a2230", "#1f3a34", "#26324a", "#342a4d", "#4a3a20", "#1f3b46"];
let wheelAngle = 0;

function wheelSegments() {
  return state.wheelSegments && state.wheelSegments.length
    ? state.wheelSegments
    : [{ multiplier: 0, weight: 35 }, { multiplier: 1.1, weight: 25 },
       { multiplier: 1.35, weight: 18 }, { multiplier: 1.7, weight: 12 },
       { multiplier: 2.3, weight: 7 }, { multiplier: 3.2, weight: 3 }];
}

function wheelMidAngle(index) {
  const segments = wheelSegments();
  const total = segments.reduce((sum, seg) => sum + (seg.weight || 1), 0);
  let acc = 0;
  for (let i = 0; i < index; i++) acc += segments[i].weight || 1;
  const share = (segments[index].weight || 1) / total;
  return ((acc + share / 2) / total) * 360;
}

function renderWheel() {
  const disc = $("wheelView");
  const legend = $("wheelLegend");
  if (!disc) return;
  const segments = wheelSegments();
  const total = segments.reduce((sum, seg) => sum + (seg.weight || 1), 0);
  let acc = 0;
  const stops = [];
  const chips = [];
  segments.forEach((seg, i) => {
    const from = (acc / total) * 360;
    acc += seg.weight || 1;
    const to = (acc / total) * 360;
    const color = seg.multiplier ? WHEEL_COLORS[i % WHEEL_COLORS.length] : "#3a2230";
    stops.push(`${color} ${from}deg ${to}deg`);
    const label = seg.multiplier ? fmtMult(seg.multiplier) : "×0";
    chips.push(`<span class="wheel-chip"><i style="background:${color}"></i>${label}</span>`);
  });
  disc.style.background = `conic-gradient(${stops.join(", ")})`;
  disc.innerHTML = "";
  if (legend) legend.innerHTML = chips.join("");
}

function renderQuests() {
  const boxes = [$("questsList"), $("tasksQuests")].filter(Boolean);
  if (!boxes.length) return;
  const items = state.quests || [];
  const html = !items.length
    ? '<div class="empty">Задания появятся после первой партии</div>'
    : items
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
  boxes.forEach((box) => {
    box.innerHTML = html;
  });
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
      toast(`+${fmt(data.payout)} mCoin`);
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

async function playCoinflip(pick) {
  const input = $("coinBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const face = $("coinFace");
  const hint = $("coinHint");
  try {
    const data = await api("/api/games/coinflip", { bet, pick });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    face.textContent = data.side === "heads" ? "О" : "Р";
    face.classList.remove("flip");
    void face.offsetWidth;
    face.classList.add("flip");
    if (data.win) {
      sfx.coin();
      haptic("success");
      toast(`+${fmt(data.payout)} mCoin`);
      hint.textContent = `Выпал ${data.side === "heads" ? "орёл" : "решка"} — угадали`;
    } else {
      sfx.boom();
      haptic("error");
      hint.textContent = `Выпала ${data.side === "heads" ? "орёл" : "решка"} — мимо`;
    }
    renderAll();
  } catch (e) {
    toast(e.message);
  }
}

/* ---------- баскет ---------- */

async function playBasket() {
  const input = $("basketBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const stage = $("basketStage");
  const result = $("basketResult");
  const btn = $("basketShoot");
  btn.disabled = true;
  stage.classList.remove("shoot-score", "shoot-miss", "scored");
  result.className = "basket-result";
  result.textContent = "Бросок…";
  try {
    const data = await api("/api/games/basket", { bet });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    void stage.offsetWidth;
    stage.classList.add(data.scored ? "shoot-score" : "shoot-miss");
    if (data.scored) stage.classList.add("scored");
    await new Promise((resolve) => setTimeout(resolve, 1150));
    if (data.scored) {
      result.textContent = `Попал! +${fmt(data.payout)} mCoin`;
      result.className = "basket-result win";
      sfx.cash();
      haptic("success");
      toast(`+${fmt(data.payout)} mCoin`);
      confetti();
    } else {
      result.textContent = "Мимо — ставка сгорела";
      result.className = "basket-result lose";
      sfx.boom();
      haptic("error");
    }
    renderAll();
  } catch (e) {
    result.textContent = e.message;
    result.className = "basket-result lose";
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- блэкджек ---------- */

function bjCardHtml(card) {
  const red = card.suit === "♥" || card.suit === "♦";
  return `<div class="bj-card${red ? " red" : ""}"><b>${card.rank}</b><i>${card.suit}</i></div>`;
}

function bjHint(round) {
  if (!round) return "Соберите 21 или ближе к 21, чем дилер. Блэкджек платит ×2,5.";
  if (round.status === "active") {
    const shown = round.dealer_hidden ? `${round.dealer_value}+` : round.dealer_value;
    return `Ваши очки: ${round.player_value}. У дилера: ${shown}.`;
  }
  if (round.status === "bust") return `Перебор — ${fmt(round.player_value)}. Ставка сгорела.`;
  if (round.multiplier >= 2.5) return `Блэкджек! Выплата ${fmt(round.payout)} mCoin`;
  if (round.multiplier >= 2) return `Победа ${round.player_value} : ${round.dealer_value} — ${fmt(round.payout)} mCoin`;
  if (round.multiplier >= 1) return `Ничья ${round.player_value} : ${round.dealer_value} — ставка возвращена`;
  return `Дилер сильнее: ${round.dealer_value} против ${round.player_value}`;
}

function renderBlackjack() {
  const box = $("bjPlayer");
  if (!box) return;
  const round = state.bj;
  const active = !!round && round.status === "active";
  const dealerBox = $("bjDealer");
  const playerBox = $("bjPlayer");
  box.innerHTML = "";
  dealerBox.innerHTML = "";
  playerBox.innerHTML = "";
  $("bjDeal").hidden = active;
  $("bjHit").hidden = !active;
  $("bjStand").hidden = !active;
  $("bjDouble").hidden = !active || (round.player && round.player.length !== 2);
  if (!round) {
    $("bjDealerValue").textContent = "0";
    $("bjPlayerValue").textContent = "0";
    $("bjHint").textContent = bjHint(null);
    return;
  }
  dealerBox.innerHTML = round.dealer.map(bjCardHtml).join("") +
    (round.dealer_hidden ? '<div class="bj-card back">?</div>' : "");
  playerBox.innerHTML = round.player.map(bjCardHtml).join("");
  $("bjDealerValue").textContent = round.dealer_hidden
    ? `${round.dealer_value}+` : round.dealer_value;
  $("bjPlayerValue").textContent = round.player_value;
  $("bjHint").textContent = bjHint(round);
}

function bjApply(data) {
  state.bj = data.round || null;
  state.user.balance = data.balance;
  state.quests = data.quests || state.quests;
  renderBlackjack();
  renderBalance();
  renderQuests();
  const round = state.bj;
  if (!round || round.status === "active") return;
  if (round.payout > 0) {
    sfx.cash();
    haptic("success");
    toast(`+${fmt(round.payout)} mCoin`);
    if (round.multiplier >= 2.5) confetti();
  } else {
    sfx.boom();
    haptic("error");
  }
}

async function bjDeal() {
  const input = $("bjBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  try {
    const data = await api("/api/games/bj/start", { bet });
    haptic();
    bjApply(data);
  } catch (e) {
    toast(e.message);
  }
}

async function bjAction(action) {
  if (!state.bj || state.bj.status !== "active") return;
  try {
    const data = await api(`/api/games/bj/${action}`, { id: state.bj.id });
    bjApply(data);
  } catch (e) {
    toast(e.message);
  }
}

async function spinWheel() {  const input = $("wheelBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const btn = $("wheelSpin");
  const disc = $("wheelView");
  const hint = $("wheelHint");
  btn.disabled = true;
  hint.textContent = "Крутим…";
  hint.className = "wheel-result";
  try {
    const data = await api("/api/games/wheel", { bet });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    state.wheelSegments = data.segments || state.wheelSegments;
    renderWheel();

    const mid = wheelMidAngle(data.segment);
    const delta = ((-mid - (wheelAngle % 360)) % 360 + 360) % 360;
    wheelAngle += 360 * 4 + delta;
    disc.style.transform = `rotate(${wheelAngle}deg)`;

    await new Promise((resolve) => setTimeout(resolve, 3400));

    if (data.multiplier > 0) {
      hint.textContent = `Сектор ${fmtMult(data.multiplier)} — выигрыш ${fmt(data.payout)}`;
      hint.className = "wheel-result win";
      sfx.cash();
      haptic("success");
      toast(`+${fmt(data.payout)} mCoin`);
    } else {
      hint.textContent = "Пустой сектор — ставка сгорела";
      hint.className = "wheel-result lose";
      sfx.boom();
      haptic("error");
    }
    renderAll();
  } catch (e) {
    hint.textContent = e.message;
    hint.className = "wheel-result lose";
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- магазин ---------- */

const INV_LABELS = {
  insurance: "🛡 Страховка",
  double_daily: "×2 Бонус",
  charm: "🍀 Талисман",
  relic_mines: "💣 Реликвия сапёра",
  relic_dice: "🎲 Кости судьбы",
  relic_wheel: "🎡 Колесо фортуны",
  relic_crash: "📈 Краш-модуль",
  theme_neon: "🎨 Неон",
  theme_gold: "🏅 Золото",
  gold_pick: "⛏ Золотая кирка",
  lootbox: "🎁 Кейс удачи",
};

function renderShopInventory() {
  const box = $("shopInventory");
  if (!box) return;
  const inv = (state.shop && state.shop.inventory) || {};
  const chips = Object.keys(INV_LABELS)
    .filter((key) => (inv[key] || 0) > 0)
    .map((key) => `<span class="inv-chip">${INV_LABELS[key]} ×${inv[key]}</span>`);
  box.innerHTML = chips.length
    ? chips.join("")
    : '<span class="muted">Инвентарь пуст — купи предмет ниже.</span>';
}

const SHOP_SECTIONS = [
  { key: "items", title: "Расходники" },
  { key: "relics", title: "Реликвии" },
  { key: "exclusive", title: "Эксклюзив" },
  { key: "cosmetics", title: "Косметика" },
];

function shopCard(entry, opts) {
  const options = opts || {};
  const owned = !!entry.owned && entry.key !== "lootbox";
  const currency = entry.currency === "gmpoint" ? "G" : (entry.currency === "level" ? "LVL" : "◈");
  let priceText;
  if (options.levelOnly) priceText = `с ${entry.level} ур.`;
  else if (entry.currency === "level") priceText = `за ${entry.level} ур.`;
  else priceText = `${currency} ${fmt(entry.price)}`;
  const label = owned ? (entry.active ? "Надет" : "Куплено") : (options.buyLabel || "Купить");
  return `<div class="shop-card${owned ? " owned" : ""}${entry.active ? " active" : ""}">
    <div class="shop-meta">
      <div class="shop-title">${escapeHtml(entry.title)}${owned ? ' <span class="owned-mark">✓</span>' : ""}${entry.active ? ' <span class="owned-mark">•</span>' : ""}</div>
      <div class="shop-desc">${escapeHtml(entry.desc || (entry.currency === "level" ? "Награда за уровень" : ""))}</div>
    </div>
    <button class="shop-buy" data-key="${entry.key}" ${owned || options.levelOnly ? "disabled" : ""}>
      <span class="shop-price">${owned ? label : priceText}</span>
      ${owned ? "Есть" : (entry.currency === "gmpoint" ? "За GMPOINT" : label)}
    </button>
  </div>`;
}

function renderShop() {
  const shop = state.shop || {};
  const items = $("shopItems");
  if (items) {
    const groups = [];
    SHOP_SECTIONS.forEach((section) => {
      const list = (shop.items || []).filter((item) => item.category === section.key);
      if (!list.length) return;
      groups.push(`<div class="shop-section">${section.title}</div>`);
      groups.push(list.map((item) => shopCard(item)).join(""));
    });
    items.innerHTML = groups.join("") || '<div class="empty">Магазин пуст</div>';
  }
  const bundles = $("shopBundles");
  if (bundles) bundles.innerHTML = (shop.bundles || []).map((item) => shopCard(item)).join("");
  const donate = $("shopDonate");
  if (donate) {
    donate.innerHTML = (shop.donate || []).map((item) => {
      const qty = (shop.inventory && shop.inventory[item.key]) || 0;
      const desc = `${item.desc}${qty ? ` · в инвентаре: ${qty}` : ""}`;
      return shopCard({ ...item, desc }, { buyLabel: "Купить" });
    }).join("") || '<div class="empty">Пока пусто</div>';
  }
  const prefixes = $("shopPrefixes");
  if (prefixes) {
    prefixes.innerHTML = (shop.prefixes || []).map((item) => {
      const levelOnly = item.currency === "level";
      const desc = `Цвет ${item.color}${levelOnly ? ` · открывается на ${item.level} уровне` : ""}`;
      return shopCard({ ...item, desc }, { levelOnly, buyLabel: "Надеть" });
    }).join("") || '<div class="empty">Пока пусто</div>';
  }
  const gmp = $("shopGmpoint");
  if (gmp) gmp.textContent = fmt(shop.gmpoint || 0);
  const lootbox = (shop.inventory && shop.inventory.lootbox) || 0;
  const box = $("lootboxCard");
  if (box) box.hidden = lootbox <= 0;
  renderShopInventory();
}

function applyCosmetics() {
  const inv = (state.shop && state.shop.inventory) || {};
  document.body.classList.toggle("theme-neon", !!inv.theme_neon);
  document.body.classList.toggle("theme-gold", !!inv.theme_gold);
}

async function loadShop() {
  try {
    const data = await api("/api/shop");
    state.shop = data;
    renderShop();
  } catch (e) {
    toast(e.message);
  }
}

async function openLootbox() {
  try {
    const data = await api("/api/shop/use", { key: "lootbox" });
    state.user.balance = data.balance;
    state.shop.inventory = data.inventory || {};
    sfx.cash();
    haptic("success");
    toast("Кейс: " + data.title);
    if (data.reward && data.reward.kind === "coins") confetti();
    renderAll();
    renderShop();
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

async function buyItem(key) {
  try {
    const data = await api("/api/shop/buy", { key });
    state.user.balance = data.balance;
    if (data.gmpoint !== undefined) state.shop.gmpoint = data.gmpoint;
    state.shop.inventory = data.inventory || {};
    if (data.prefix) state.user.prefix = data.prefix;
    sfx.cash();
    haptic("success");
    toast(`Куплено: ${data.bought}`);
    renderAll();
    renderShop();
    loadShop().catch(() => {});
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

/* ---------- краш ---------- */

function crashTarget() {
  const slider = $("crashSlider");
  return slider ? Math.round(Number(slider.value)) / 100 : 2;
}

function renderCrashTarget() {
  const target = crashTarget();
  const value = $("crashTargetValue");
  const chance = $("crashChance");
  if (value) value.textContent = fmtMult(target);
  if (chance) chance.textContent = `шанс ${Math.round((0.99 / target) * 100)}%`;
}

async function playCrash() {
  const input = $("crashBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const target = crashTarget();
  const btn = $("crashSpin");
  const hint = $("crashResult");
  btn.disabled = true;
  hint.className = "crash-result";
  hint.textContent = "Взлёт…";
  try {
    const data = await api("/api/games/crash", { bet, target });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    if (data.win) {
      hint.textContent = `Краш на ${fmtMult(data.point)} — забрал ${fmt(data.payout)}`;
      hint.className = "crash-result win";
      sfx.cash();
      haptic("success");
      toast(`+${fmt(data.payout)} mCoin`);
    } else {
      hint.textContent = `Краш на ${fmtMult(data.point)} — до ${fmtMult(data.target)} не дожило`;
      hint.className = "crash-result lose";
      sfx.boom();
      haptic("error");
    }
    renderAll();
  } catch (e) {
    hint.textContent = e.message;
    hint.className = "crash-result lose";
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
}

function renderUpdates(force) {
  const info = state.updates;
  const modal = $("updateModal");
  if (!info || !modal) return;
  if ($("updateVersion")) $("updateVersion").textContent = info.version || "";
  if ($("updateList")) {
    $("updateList").innerHTML = (info.notes || [])
      .map((note) => `<li>${escapeHtml(note)}</li>`).join("");
  }
  let dismissed = "";
  try {
    dismissed = sessionStorage.getItem("saper_updates_dismissed") || "";
  } catch (e) {}
  if (force || dismissed !== info.version) {
    modal.hidden = false;
    requestAnimationFrame(() => modal.classList.add("show"));
  }
}

function closeUpdates() {
  const modal = $("updateModal");
  if (!modal) return;
  modal.classList.remove("show");
  setTimeout(() => { modal.hidden = true; }, 200);
  try {
    if (state.updates && state.updates.version) {
      localStorage.setItem("saper_seen_version", state.updates.version);
      sessionStorage.setItem("saper_updates_dismissed", state.updates.version);
    }
  } catch (e) {}
}

async function sendTransfer() {
  const to = ($("transferTo").value || "").trim();
  const amount = parseInt($("transferAmount").value || "0", 10) || 0;
  const hint = $("transferHint");
  if (!to) {
    hint.textContent = "Введите ID или @username получателя";
    return;
  }
  if (amount < 1) {
    hint.textContent = "Сумма должна быть больше нуля";
    return;
  }
  try {
    const data = await api("/api/transfer", { to, amount });
    state.user.balance = data.balance;
    const name = data.to.username ? "@" + data.to.username : "ID " + data.to.id;
    hint.textContent = `Отправлено ${fmt(data.amount)} mCoin игроку ${name}`;
    $("transferTo").value = "";
    sfx.coin();
    haptic("success");
    renderAll();
  } catch (e) {
    hint.textContent = e.message;
    haptic("error");
  }
}

async function applyPromo() {
  const input = $("promoInput");
  const code = (input.value || "").trim();
  const hint = $("promoHint");
  if (!code) {
    hint.textContent = "Введите промокод";
    return;
  }
  try {
    const data = await api("/api/promo", { code });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    hint.textContent = `Промокод принят: +${fmt(data.amount)} mCoin`;
    input.value = "";
    sfx.cash();
    haptic("success");
    confetti();
    renderAll();
  } catch (e) {
    hint.textContent = e.message;
    haptic("error");
  }
}

function renderAll() {
  renderBalance();
  renderDaily();
  renderBonus();
  renderMines();
  renderGameSwitch();
  renderControls();
  renderGrid();
  renderLadder();
  renderProfile();
  renderQuests();
  renderTasks();
  renderBank();
  renderGamesHub();
  renderDailySpin();
  renderHistory();
  renderBlackjack();
  applyCosmetics();
    const topTab = document.querySelector("#view-top .tab.active");
    renderTop(topTab ? topTab.dataset.tab : "balance");
  renderFair();
}

/* ---------- actions ---------- */

async function loadState() {
  const data = await api("/api/state");
  const prevUser = state.user;
  const prevClaimed = new Set(
    (state.achievements || []).filter((a) => a.claimed).map((a) => a.key)
  );
  state.user = data.user;
  if (prevUser && data.user.level > (prevUser.level || 1)) {
    toast(`⭐ Уровень ${data.user.level} — ${data.user.level_title}`);
    confetti();
  }
  state.botUsername = data.bot_username || "";
  state.chatUrl = data.chat_url || "";
  state.settings = data.settings || state.settings;
  state.isAdmin = !!data.is_admin;
  state.isSuper = !!data.is_superadmin;
  state.account = data.account || null;
  state.quests = data.quests || state.quests;
  state.shop.inventory = data.inventory || state.shop.inventory;
  const adminNav = $("adminNav");
  if (adminNav) adminNav.hidden = !state.isAdmin;
  state.referrals = data.referrals;
  state.leaderboard = {
    by_balance: data.leaderboard || [],
    by_multiplier: state.leaderboard.by_multiplier || [],
    by_level: data.leaderboard_level || state.leaderboard.by_level || [],
    me: data.user.id,
  };
  state.history = data.history || [];
  state.invites = data.invites || state.invites;
  state.sponsors = data.sponsors || state.sponsors;
  state.deposits = data.deposits || state.deposits;
  state.spin = data.spin || state.spin;
  state.levels = data.levels || state.levels;
  state.gamesHub = data.games_hub || state.gamesHub;
  if (!state.depositPlan && state.deposits.plans && state.deposits.plans.length) {
    state.depositPlan = state.deposits.plans[0].days;
  }
  state.fair = data.fair;
  state.round = data.active_round;
  state.bj = data.active_bj || null;
  state.updates = data.updates || state.updates;
  if (state.round) {
    state.bet = state.round.bet;
    state.mines = state.round.mines;
    state.autoTarget = state.round.auto_target || 0;
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
      modal("💥", "Мина!", `Ставка ${fmt(state.round.bet)} mCoin сгорела. Попробуешь ещё?`, "Ещё раз");
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
      confetti();
      if (data.auto) {
        modal("🤖", "Авто-кэшаут!", `${fmt(data.payout)} mCoin на множителе ${fmtMult(data.multiplier)}.`, "Ещё раз");
      } else {
        modal("💎", "Поле очищено!", `Ты забрал ${fmt(data.payout)} mCoin с множителем ${fmtMult(data.multiplier)}.`, "Ещё раз");
      }
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
  const autoTarget = Number(($("autoTarget") && $("autoTarget").value) || 0);
  state.autoTarget = autoTarget;
  try {
    const data = await api("/api/game/start", { bet, mines: state.mines, auto_target: autoTarget });
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
    confetti();
    renderAll();
    modal("💰", "Забрано!", `${fmt(data.payout)} mCoin на множителе ${fmtMult(data.multiplier)}.`, "Продолжить");
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
    toast(`Бонус +${fmt(data.amount)} mCoin${awardsNote(data.awards)}`);
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
  if (name === "shop") loadShop();
  if (name === "tasks") renderTasks();
  if (name === "bank") renderBank();
  if (name === "games") renderGamesHub();
}

async function loadTop() {
  try {
    const data = await api("/api/leaderboard");
    state.leaderboard.by_balance = data.by_balance;
    state.leaderboard.by_multiplier = data.by_multiplier;
    state.leaderboard.by_level = data.by_level || state.leaderboard.by_level;
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

  if ($("autoTarget")) {
    $("autoTarget").addEventListener("change", (e) => {
      state.autoTarget = Number(e.target.value) || 0;
    });
  }

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

  if ($("updateClose")) $("updateClose").addEventListener("click", closeUpdates);
  if ($("updatesOpen")) $("updatesOpen").addEventListener("click", () => renderUpdates(true));
  if ($("transferSend")) $("transferSend").addEventListener("click", sendTransfer);
  if ($("promoApply")) $("promoApply").addEventListener("click", applyPromo);
  if ($("copyId")) $("copyId").addEventListener("click", async () => {
    const id = state.user ? String(state.user.id) : "";
    try {
      await navigator.clipboard.writeText(id);
      toast("ID скопирован");
    } catch (e) {
      toast(id);
    }
  });
  if ($("updateModal")) $("updateModal").addEventListener("click", (e) => {
    if (e.target === $("updateModal")) closeUpdates();
  });

  if ($("modalBtn")) {
    $("modalBtn").addEventListener("click", () => {
      $("modal").classList.remove("show");
      state.round = null;
      renderAll();
    });
  }

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
      if (tab.dataset.atab === "promo") loadPromos();
    })
  );

  $("adminSearch").addEventListener("input", (e) => {
    clearTimeout(e.target._t);
    e.target._t = setTimeout(() => adminSearch(e.target.value.trim()), 350);
  });

  if ($("promoCreate")) $("promoCreate").addEventListener("click", createPromo);
  if ($("promoList")) $("promoList").addEventListener("click", (e) => {
    const btn = e.target.closest('button[data-act="del-promo"]');
    if (!btn) return;
    const row = btn.closest(".row");
    if (row) deletePromo(row.dataset.code);
  });
  if ($("promoRedeemBtn")) $("promoRedeemBtn").addEventListener("click", redeemPromo);

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
    else if (act === "item") {
      const select = row.querySelector('select[data-role="item"]');
      if (select) adminGrant(userId, select.value);
    }
    else if (act === "ban") adminBan(userId, true);
    else if (act === "unban") adminBan(userId, false);
    else if (act === "role") {
      const select = row.querySelector('select[data-role="role"]');
      if (select) adminRole(userId, select.value);
    }
    else if (act === "gmp" || act === "gmp-minus") {
      const gmp = row.querySelector("[data-gmp]");
      const value = Number((gmp && gmp.value) || 0);
      if (value > 0) adminGmpoint(userId, act === "gmp" ? value : -value);
    }
  });

  $("saveSettings").addEventListener("click", saveAdminSettings);

  if ($("hourlyCard")) $("hourlyCard").addEventListener("click", claimHourly);
  if ($("spinCard")) $("spinCard").addEventListener("click", () => switchView("tasks"));
  if ($("dailySpinBtn")) $("dailySpinBtn").addEventListener("click", spinDaily);
  if ($("inviteList")) $("inviteList").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-step]");
    if (btn) claimInvite(Number(btn.dataset.step));
  });
  if ($("sponsorList")) $("sponsorList").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-channel]");
    if (btn) claimSponsor(btn.dataset.channel);
  });
  if ($("depositPlans")) $("depositPlans").addEventListener("click", (e) => {
    const btn = e.target.closest(".plan");
    if (!btn) return;
    state.depositPlan = Number(btn.dataset.days);
    renderBank();
  });
  if ($("depositAmount")) $("depositAmount").addEventListener("input", updateDepositHint);
  if ($("depositCreate")) $("depositCreate").addEventListener("click", depositCreate);
  if ($("savingsPut")) $("savingsPut").addEventListener("click", savingsPut);
  if ($("savingsClose")) $("savingsClose").addEventListener("click", savingsClose);
  if ($("depositList")) $("depositList").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-dep]");
    if (btn) depositClose(btn.dataset.dep);
  });
  if ($("hubGrid")) $("hubGrid").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-hub-game]");
    if (!btn) return;
    switchView("game");
    switchGame(btn.dataset.hubGame);
  });

  setInterval(() => {
    if (state.user) renderBonus();
  }, 1000);

  if ($("gamePickerBtn")) $("gamePickerBtn").addEventListener("click", openGameMenu);
  if ($("gameMenuClose")) $("gameMenuClose").addEventListener("click", closeGameMenu);
  if ($("gameMenuBackdrop")) $("gameMenuBackdrop").addEventListener("click", closeGameMenu);
  if ($("gameMenuGrid")) {
    $("gameMenuGrid").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-game]");
      if (btn) switchGame(btn.dataset.game);
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeGameMenu();
  });

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

  document.querySelectorAll("[data-cbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("crashBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.cbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  $("crashSlider").addEventListener("input", renderCrashTarget);
  $("crashSpin").addEventListener("click", playCrash);

  document.querySelectorAll("[data-flip]").forEach((btn) =>
    btn.addEventListener("click", () => playCoinflip(btn.dataset.flip)));

  document.querySelectorAll("[data-fbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("coinBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.fbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  document.querySelectorAll("[data-jbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("bjBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.jbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  if ($("bjDeal")) $("bjDeal").addEventListener("click", bjDeal);
  if ($("bjHit")) $("bjHit").addEventListener("click", () => bjAction("hit"));
  if ($("bjStand")) $("bjStand").addEventListener("click", () => bjAction("stand"));
  if ($("bjDouble")) $("bjDouble").addEventListener("click", () => bjAction("double"));

  document.querySelectorAll("[data-kbet]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const input = $("basketBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.kbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  if ($("basketShoot")) $("basketShoot").addEventListener("click", playBasket);

  $("view-shop").addEventListener("click", (e) => {
    const btn = e.target.closest(".shop-buy");
    if (!btn || btn.disabled) return;
    buyItem(btn.dataset.key);
  });

  if ($("openLootbox")) $("openLootbox").addEventListener("click", openLootbox);

  if ($("accountRegister")) $("accountRegister").addEventListener("click", accountRegister);
  if ($("accountLoginBtn")) $("accountLoginBtn").addEventListener("click", accountLogin);
  if ($("accountLogout")) $("accountLogout").addEventListener("click", accountLogout);
  if ($("gateSubmit")) $("gateSubmit").addEventListener("click", accountLogin);

  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchView(btn.dataset.goto);
      toggleDrawer(false);
    });
  });
  if ($("menuToggle")) $("menuToggle").addEventListener("click", () => toggleDrawer(true));
  if ($("drawerClose")) $("drawerClose").addEventListener("click", () => toggleDrawer(false));
  if ($("drawerBackdrop")) $("drawerBackdrop").addEventListener("click", () => toggleDrawer(false));
  document.querySelectorAll("[data-theme]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const theme = btn.dataset.theme;
      if (theme !== "default") {
        const inv = (state.shop && state.shop.inventory) || {};
        const need = theme === "neon" ? "theme_neon" : "theme_gold";
        if (!inv[need]) {
          toggleDrawer(false);
          switchView("shop");
          toast("Сначала купи тему в магазине");
          return;
        }
      }
      applyTheme(theme);
      toggleDrawer(false);
      toast("Тема применена");
    });
  });
  if ($("chatLink")) $("chatLink").addEventListener("click", () => {
    if (state.chatUrl) window.open(state.chatUrl, "_blank");
    else toast("Чат пока не настроен");
  });

  if ($("claimLevels")) $("claimLevels").addEventListener("click", async () => {
    try {
      const data = await api("/api/levels/claim");
      state.user.balance = data.balance;
      state.levels = data.levels || state.levels;
      const bits = [];
      if (data.coins) bits.push(`+${fmt(data.coins)} mCoin`);
      if (data.gmpoint) bits.push(`+${data.gmpoint} GMPOINT`);
      if (data.lootbox) bits.push(`+${data.lootbox} лутбокс`);
      toast(bits.length ? `Награды за уровни: ${bits.join(" · ")}` : "Наград пока нет");
      if (bits.length) sfx.cash();
      renderAll();
      await loadState();
    } catch (err) {
      toast(err.message);
    }
  });

  $("questsList").addEventListener("click", async (e) => {
    const btn = e.target.closest(".quest-claim");
    if (!btn || btn.disabled) return;
    try {
      const data = await api("/api/quests/claim", { key: btn.dataset.quest });
  state.quests = data.quests || state.quests;
  state.achievements = data.achievements || [];
  if (prevClaimed.size) {
    const fresh = state.achievements.filter(
      (a) => a.claimed && !prevClaimed.has(a.key)
    );
    if (fresh.length) toast(`🏅 ${fresh.map((a) => a.title).join(", ")}`);
  }
      state.user.balance = data.balance;
      sfx.cash();
    toast(`Награда +${fmt(data.reward)} mCoin${awardsNote(data.awards)}`);
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
    const savedTheme = localStorage.getItem("saper_theme");
    if (savedTheme) applyTheme(savedTheme);
  } catch (e) {}
  const soundBtn = $("soundBtn");
  if (soundBtn) soundBtn.textContent = state.sound ? "🔊" : "🔇";

  bind();
  renderCrashTarget();
  renderControls();
  try {
    await loadState();
    renderUpdates(false);
  } catch (e) {
    if (String(e.message).toLowerCase().includes("unauthorized")) {
      if (!(tg && tg.initData) ) showAuthGate();
    } else {
      toast(e.message === "unauthorized" ? "Откройте игру через Telegram" : e.message);
    }
  }
}

init();
