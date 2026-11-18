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
  settings: { min_bet: 10, max_bet: 100000000, min_mines: 1, max_mines: 24, daily_bonus: 500, maintenance: 0 },
  isAdmin: false,
  isSuper: false,
  sound: true,
  vibrate: true,
  soundVol: 1,
  anim: true,
  game: "mines",
  quests: [],
  hourQuests: [],
  shop: { items: [], bundles: [], donate: [], prefixes: [], inventory: {}, gmpoint: 0 },
  cosmetics: { avatars: [], backgrounds: [], avatar_key: "letter", bg_key: "default" },
  leaderboard: { by_balance: [], by_multiplier: [], by_level: [], me: 0 },
  levels: { level: 1, pending: 0, pending_levels: [], next: 2, to_next: 0 },
  history: [],
  achievements: [],
  referrals: { total: 0, active: 0 },
  invites: { total: 0, ladder: [] },
  sponsors: [],
  deposits: { plans: [], items: [], savings: null, min: 100, max: 100000000 },
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
  if (state.vibrate === false) return;
  try {
    if (type === "error") tg.HapticFeedback.notificationOccurred("error");
    else if (type === "success") tg.HapticFeedback.notificationOccurred("success");
    else tg.HapticFeedback.impactOccurred("light");
  } catch (e) {}
}

let audioCtx = null;

function tone(freq, duration, type, gain, when) {
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
    const volume = (state.soundVol || 1) * (gain == null ? 0.05 : gain);
    vol.gain.value = volume;
    osc.connect(vol);
    vol.connect(audioCtx.destination);
    const t0 = audioCtx.currentTime + (when || 0);
    vol.gain.setValueAtTime(volume, t0);
    vol.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
    osc.start(t0);
    osc.stop(t0 + duration);
  } catch (e) {}
}

function melody(steps, type, gain, speed) {
  steps.forEach((f, i) => tone(f, 0.14, type || "sine", gain || 0.05, i * (speed || 0.09)));
}

const sfx = {
  click() { tone(320, 0.05, "square", 0.03); },
  open() { tone(520, 0.09, "triangle", 0.05); },
  coin() { tone(700, 0.09, "sine", 0.05); setTimeout(() => tone(980, 0.1, "sine", 0.04), 70); },
  boom() { tone(110, 0.42, "sawtooth", 0.09); setTimeout(() => tone(70, 0.5, "sawtooth", 0.07), 90); },
  cash() { [660, 880, 1180].forEach((f, i) => setTimeout(() => tone(f, 0.12, "sine", 0.05), i * 80)); },
  win() { melody([523, 659, 784, 1046], "triangle", 0.055, 0.1); },
  lose() { melody([300, 250, 200, 150], "sawtooth", 0.05, 0.12); },
  levelup() { melody([440, 554, 659, 880, 1108], "square", 0.04, 0.09); },
  quest() { melody([392, 523, 659], "sine", 0.05, 0.1); },
  tick() { tone(920, 0.04, "sine", 0.03); },
  ticket() { melody([660, 880], "triangle", 0.05, 0.08); },
  error() { tone(180, 0.18, "sawtooth", 0.06); },
  purchase() { melody([523, 659, 784], "triangle", 0.05, 0.09); },
};

function confetti() {
  const green = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const weak = !state.anim && !green;
  burst("confetti", window.innerWidth / 2, window.innerHeight * 0.4,
    weak ? 40 : 90, {
    vx: 9, vy: 11, size: 7, colors: ["#7c5cff", "#2ee6a8", "#ffb02e", "#ff5d7a", "#f4f6ff"],
    shape: "rect", gravity: 0.3, life: 90,
  });
}

function coinRain() {
  burst("confetti", window.innerWidth / 2, window.innerHeight * 0.2, 70, {
    vx: 10, vy: 5, size: 9, colors: ["#ffd166", "#ffb02e", "#ffe9a8"],
    shape: "coin", gravity: 0.5, life: 120, spin: true,
  });
  const chip = $("balanceChip");
  if (chip) {
    chip.classList.remove("bump");
    chip.classList.add("bump");
    setTimeout(() => chip.classList.remove("bump"), 500);
  }
}

function floatWin(text, x, y) {
  const span = document.createElement("div");
  span.className = "float-win";
  span.textContent = text;
  span.style.left = `${Math.max(8, Math.min(window.innerWidth - 120, ((x == null ? window.innerWidth / 2 : x))))}px`;
  span.style.top = `${y == null ? window.innerHeight * 0.4 : y}px`;
  document.body.appendChild(span);
  setTimeout(() => span.remove(), 1400);
}

function burst(canvasId, cx, cy, count, opts) {
  const canvas = $(canvasId);
  if (!canvas) return;
  if (state.anim === false) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.floor(window.innerWidth * dpr);
  canvas.height = Math.floor(window.innerHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const o = opts || {};
  const colors = o.colors || ["#7c5cff", "#2ee6a8", "#ffb02e", "#ff5d7a", "#f4f6ff"];
  const parts = [];
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = (o.vx || 8) * (0.4 + Math.random() * 0.8);
    parts.push({
      x: cx + (Math.random() - 0.5) * 60,
      y: cy + (Math.random() - 0.5) * 40,
      vx: Math.cos(angle) * speed,
      vy: -Math.abs(Math.sin(angle)) * (o.vy || 10) - Math.random() * 3,
      size: (o.size || 6) * (0.6 + Math.random() * 0.8),
      color: colors[Math.floor(Math.random() * colors.length)],
      shape: o.shape || "rect",
      rot: Math.random() * Math.PI,
      vr: (Math.random() - 0.5) * 0.4,
      life: (o.life || 90) + Math.floor(Math.random() * 40),
      spin: !!(o.spin),
    });
  }
  const gravity = o.gravity == null ? 0.3 : o.gravity;
  let frame = 0;
  const tick = () => {
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    let alive = false;
    for (const p of parts) {
      if (p.life <= 0) continue;
      alive = true;
      p.life -= 1;
      p.vy += gravity;
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.globalAlpha = Math.max(0, Math.min(1, p.life / 35));
      ctx.fillStyle = p.color;
      if (p.shape === "coin") {
        ctx.beginPath();
        ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.35)";
        ctx.beginPath();
        ctx.arc(-p.size * 0.12, -p.size * 0.12, p.size * 0.18, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.62);
      }
      ctx.restore();
    }
    frame += 1;
    if (alive && frame < 190) requestAnimationFrame(tick);
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
    if (typeof sfx !== "undefined") sfx.error();
    throw new Error("Сервер не ответил");
  }
  if (!res.ok || !data.ok) {
    if (typeof sfx !== "undefined") sfx.error();
    throw new Error(data.error || "Ошибка запроса");
  }
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
  const chip = $("balanceChip");
  if (chip) {
    chip.classList.remove("flash");
    chip.classList.add("flash");
    setTimeout(() => chip.classList.remove("flash"), 400);
  }
}

function renderDaily() {
  const btn = $("dailyBtn");
  const ready = state.user && state.user.daily_ready;
  btn.classList.toggle("ready", !!ready);
  const streak = (state.user && state.user.daily_streak) || 0;
  const amount = (state.user && state.user.daily_amount) || 1000;
  btn.title = ready
    ? `Бонус: день ${streak + 1} · +${fmt(amount)} mCoin`
    : `Бонус получен · серия ${streak} дн.`;
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
  ["darts", "🎯", "Дартс", "Яблочко ×5,9 · сектор ×1,98 · мимо ×2,97"],
  ["fishing", "🎣", "Рыбалка", "Забрось удочку и продай улов"],
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
    confetti();
    floatWin(data.currency === "gmpoint" ? `+${fmt(data.amount)} G` : `+${fmt(data.amount)}`);
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
  const round = state.round;
  const opened = round ? round.opened : [];
  const mineSet = round && round.mine_positions ? new Set(round.mine_positions) : null;
  const cheat = state.cheat && state.cheat.enabled && state.isAdmin
    ? state.cheat : null;
  const cheatMines = cheat && cheat.mine_positions ? new Set(cheat.mine_positions) : null;
  const active = !!(round && round.status === "active");

  let cells = grid.querySelectorAll("button.cell");
  if (cells.length !== 25) {
    grid.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (let i = 0; i < 25; i++) {
      const cell = document.createElement("button");
      cell.className = "cell";
      cell.dataset.index = i;
      cell.type = "button";
      cell.addEventListener("click", () => {
        if (state.round && state.round.status === "active") openCell(Number(cell.dataset.index));
      });
      frag.appendChild(cell);
    }
    grid.appendChild(frag);
    cells = grid.querySelectorAll("button.cell");
  }

  cells.forEach((cell, i) => {
    cell.className = "cell";
    cell.title = "";
    cell.style.animationDelay = "";

    if (cheat && cheatMines && active && !opened.includes(i)) {
      if (cheatMines.has(i)) {
        cell.classList.add("cheat-mine");
        cell.title = "Мина (чит)";
      }
    }

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
  });
}

function previewLadder(mines, steps) {
  const safe = 25 - mines;
  const out = [];
  for (let k = 1; k <= Math.min(steps, safe); k++) {
    let p = 1;
    for (let i = 0; i < k; i++) p *= (safe - i) / (25 - i);
    const mult = Math.max(1, Math.min(100, Math.floor((0.92 / p) * 100) / 100));
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
  return Math.max(1, Math.min(100, Math.floor((0.92 / p) * 100) / 100));
}

function avatarFace(u) {
  if (u.avatar_url) return `<img class="profile-avatar-img" src="${u.avatar_url}" alt="">`;
  if (u.avatar_icon) return u.avatar_icon;
  return (u.first_name || u.username || "И").trim().charAt(0).toUpperCase();
}

function avatarFaceHtml(u, cls) {
  if (u.avatar_url) return `<img class="${cls || "avatar-img"}" src="${u.avatar_url}" alt="">`;
  return null;
}

function prefixStyleCss(entry) {
  const color = entry.prefix_color || entry.color || "#e5e7eb";
  const color2 = entry.prefix_color2 || entry.color2 || color;
  return `--prefix-color:${color};--prefix-color2:${color2};`;
}

function prefixClass(entry) {
  const style = entry.prefix_style || entry.style || "solid";
  return `prefix-badge prefix-style-${style}`;
}

function pluralText(value, one, few, many) {
  const n = Math.abs(Math.trunc(value)) % 100;
  if (n >= 11 && n <= 14) return many;
  const last = n % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

function seenLabel(ts) {
  if (!ts) return "давно не заходил";
  const delta = Math.max(0, Math.floor(Date.now() / 1000) - Number(ts));
  if (delta < 60) return "был(а) только что";
  if (delta < 3600) {
    const minutes = Math.floor(delta / 60);
    return `был(а) ${minutes} ${pluralText(minutes, "минуту", "минуты", "минут")} назад`;
  }
  if (delta < 86400) {
    const hours = Math.floor(delta / 3600);
    return `был(а) ${hours} ${pluralText(hours, "час", "часа", "часов")} назад`;
  }
  if (delta < 30 * 86400) {
    const days = Math.max(1, Math.floor(delta / 86400));
    return `был(а) ${days} ${pluralText(days, "день", "дня", "дней")} назад`;
  }
  const date = new Date(Number(ts) * 1000);
  return "заходил(а) " + date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

function renderProfile() {
  if (!state.user) return;
  const u = state.user;
  $("profileName").textContent = u.first_name || u.username || "Игрок";
  $("profileId").textContent = "id " + u.id;
  if ($("myId")) $("myId").textContent = u.id;
  $("avatar").innerHTML = avatarFace(u);
  const card = document.querySelector("#view-profile .profile-card");
  if (card) {
    if (u.bg_css) {
      card.style.background = u.bg_css;
      card.classList.add("has-bg");
    } else {
      card.style.background = "";
      card.classList.remove("has-bg");
    }
  }
  const prefBox = $("profilePrefix");
  if (prefBox) {
    if (u.prefix_title) {
      const bonus = u.prefix_bonus ? ` · +${Math.round(u.prefix_bonus * 100)}% к выигрышу` : "";
      prefBox.hidden = false;
      prefBox.textContent = `${u.prefix_title}${bonus}`;
      prefBox.className = "profile-prefix " + prefixClass(u);
      prefBox.style.cssText = prefixStyleCss(u);
    } else {
      prefBox.hidden = true;
    }
  }
  const seen = $("profileSeen");
  if (seen) seen.textContent = seenLabel(u.last_seen);
  const boosts = $("profileBoosts");
  if (boosts) {
    const bits = [];
    if (u.boost_win) bits.push(`🚀 +5% к выигрышу ×${u.boost_win}`);
    if (u.boost_loss) bits.push(`🛟 кэшбэк 5% ×${u.boost_loss}`);
    const inv = (state.shop && state.shop.inventory) || {};
    const titleKeys = ["title_baron", "title_magnate", "title_emperor",
                       "title_legend", "title_deity"];
    const titles = titleKeys.filter((k) => Number(inv[k] || 0) > 0);
    if (titles.length) bits.push(`👑 Титулов: ${titles.length}`);
    boosts.hidden = !bits.length;
    boosts.textContent = bits.join(" · ");
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

  if ($("profileRank")) {
    const rankPos = Number(state.rank) || 0;
    $("profileRank").textContent = rankPos > 0 ? "#" + rankPos : "#—";
  }

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
  const filter = state.achFilter || "all";
  const inFilter = (a) => {
    if (filter === "done") return a.claimed;
    if (filter === "ready") return !a.claimed && a.done;
    return true;
  };
  const items = ach.filter(inFilter);
  const total = ach.length;
  const done = ach.filter((a) => a.claimed).length;
  const box = $("achievements");
  if (!box) return;
  box.innerHTML = `
    <div class="ach-head">
      <span class="ach-count">${done} / ${total} получено</span>
      <div class="ach-pills">
        <button class="ach-pill${filter === "all" ? " active" : ""}" data-achfilter="all">Все (${total})</button>
        <button class="ach-pill${filter === "done" ? " active" : ""}" data-achfilter="done">Есть (${done})</button>
        <button class="ach-pill${filter === "ready" ? " active" : ""}" data-achfilter="ready">Доступно</button>
      </div>
    </div>`;
  const list = document.createElement("div");
  list.className = "ach-list";
  list.innerHTML = items.length
    ? items
        .map((a) => {
          const cls = a.claimed ? "done" : a.done ? "ready" : "locked";
          const pct = a.target ? Math.min(100, Math.round((a.progress / a.target) * 100)) : 0;
          return `<div class="ach ${cls}">
            <div class="ach-icon">${a.icon}</div>
            <div class="ach-main">
              <div class="ach-name">${escapeHtml(a.title)}</div>
              <div class="ach-desc">${escapeHtml(a.desc)}</div>
              <div class="ach-bar"><span class="ach-bar-fill" style="width:${pct}%"></span></div>
              <div class="ach-hint">${a.progress} / ${a.target} · ${a.claimed ? "получено ✓" : pct + "%"}</div>
            </div>
            <div class="ach-reward">${a.claimed ? "✓" : "+" + fmt(a.reward)}</div>
          </div>`;
        })
        .join("")
    : '<div class="empty">Здесь пока пусто</div>';
  box.appendChild(list);
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
    $("admPromoHint").textContent = `Создан ${data.code} на +${fmt(data.amount)} GMPOINT`;
    $("promoCode").value = "";
    await loadPromos();
  } catch (e) {
    $("admPromoHint").textContent = e.message;
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

async function toggleDrawer(show) {
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
  const sum = $("historySummary");
  if (!state.history.length) {
    if (list) list.innerHTML = '<div class="empty">Пока ни одной игры</div>';
    if (sum) sum.innerHTML = "";
    return;
  }
  const filter = state.historyFilter || "all";
  let items = state.history;
  if (filter === "win") items = items.filter((r) => r.payout > 0);
  if (filter === "lose") items = items.filter((r) => r.payout <= 0);
  if (items.length > 250) items = items.slice(0, 250);
  const totalBet = items.reduce((a, r) => a + (r.bet || 0), 0);
  const totalPaid = items.reduce((a, r) => a + (r.payout || 0), 0);
  const wins = items.filter((r) => r.payout > 0).length;
  if (sum) {
    sum.innerHTML = `
      <div class="stat"><span class="stat-value">${fmt(items.length)}</span><span class="stat-label">записей</span></div>
      <div class="stat"><span class="stat-value">${fmt(wins)}</span><span class="stat-label">побед</span></div>
      <div class="stat"><span class="stat-value">${fmt(totalBet)}</span><span class="stat-label">ставок</span></div>
      <div class="stat ${totalPaid - totalBet >= 0 ? "hist-plus" : "hist-minus"}"><span class="stat-value">${totalPaid - totalBet >= 0 ? "+" : "−"}${fmt(Math.abs(totalPaid - totalBet))}</span><span class="stat-label">результат</span></div>`;
  }
  const html = items
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
  list.innerHTML = html;
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

function prefixBadge(entry) {
  if (!entry) return "";
  if (entry.prefix_title) {
    return ` <span class="${prefixClass(entry)}" style="${prefixStyleCss(entry)}">${escapeHtml(entry.prefix_title)}</span>`;
  }
  const meta = PREFIX_META[entry];
  if (!meta) return "";
  return ` <span class="prefix-badge" style="color:${meta.color};border-color:${meta.color}55">${escapeHtml(meta.title)}</span>`;
}

let topSignature = "";

function nextMonday() {
  const now = new Date();
  const day = (now.getDay() + 6) % 7;
  const next = new Date(now);
  next.setHours(0, 0, 0, 0);
  next.setDate(now.getDate() + ((7 - day) % 7 || 7));
  return next.getTime();
}

function renderTop(tab) {
  const list = $("topList");
  if (!list) return;
  const rewards = $("topRewards");
  if (rewards) {
    const w = state.leaderboard.weekly || [];
    if (w.length) {
      const next = nextMonday();
      const diff = Math.max(0, next - Date.now());
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff % 86400000) / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const timer = d > 0 ? `${d} д ${h} ч` : `${h} ч ${m} мин`;
      rewards.innerHTML = `<div class="top-reward top-timer">🏁 До награды: <b>${timer}</b></div>` +
        w.map((x) =>
          `<div class="top-reward"><span>${["🥇", "🥈", "🥉"][x.place - 1] || x.place} место</span>` +
          `<b>${fmt(x.coins)} mCoin</b> + ${x.gmpoint} GMPOINT</div>`).join("");
    } else {
      rewards.innerHTML = `<div class="top-reward">Еженедельные призы: топ-3 получает mCoin и GMPOINT (каждый понедельник)</div>`;
    }
  }
  let rows = [];
  if (tab === "mult") {
    rows = (state.leaderboard.by_multiplier || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: fmtMult(u.best_multiplier),
      id: u.user_id,
      photo: u.photo_url,
      row: u,
    }));
  } else if (tab === "lvl") {
    rows = (state.leaderboard.by_level || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: `⭐ ${u.level || 1} ур. · ${fmt(u.xp || 0)} XP`,
      id: u.user_id,
      photo: u.photo_url,
      row: u,
    }));
  } else {
    rows = (state.leaderboard.by_balance || []).map((u, i) => ({
      place: i + 1,
      name: u.username || u.first_name || "id" + u.user_id,
      value: fmt(u.balance) + " mCoin",
      id: u.user_id,
      photo: u.photo_url,
      row: u,
    }));
  }
  if (!rows.length) {
    list.innerHTML = '<div class="empty">Рейтинг пока пуст</div>';
    return;
  }
  const medals = ["🥇", "🥈", "🥉"];
  const signature = tab + "|" + rows
    .map((r) => [r.id, r.value, r.name, r.photo || "", (r.row && r.row.last_seen) || ""].join(":"))
    .join("|");
  if (signature === topSignature) return;
  topSignature = signature;

  list.innerHTML = rows
    .map(
      (r) => {
        const seen = seenLabel(r.row && r.row.last_seen);
        return `<div class="row" style="${r.id === state.leaderboard.me ? "border-color:rgba(46,230,168,.45)" : ""}">
        ${r.photo
          ? `<img class="row-avatar" src="${escapeHtml(r.photo)}" alt="">`
          : `<span class="row-avatar${r.row && r.row.avatar_icon ? " emoji" : " letter"}">${escapeHtml(r.row && r.row.avatar_icon ? r.row.avatar_icon : (String(r.name).replace("@", "").charAt(0).toUpperCase() || "?"))}</span>`}
        <div class="row-main"><div class="row-title"><span class="top-place">${medals[r.place - 1] || r.place}</span> ${escapeHtml(r.name)}${prefixBadge(r.row)}</div>
        <div class="row-sub top-seen">${escapeHtml(seen)}</div></div>
        <div class="row-value">${r.value}</div>
      </div>`;
      }
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
  ["boost_win", "Буст выигрыша"],
  ["boost_loss", "Кэшбэк"],
  ["relic_mines", "Реликвия сапёра"],
  ["relic_dice", "Кости судьбы"],
  ["relic_wheel", "Колесо фортуны"],
  ["relic_crash", "Краш-модуль"],
  ["theme_neon", "Неоновая тема"],
  ["theme_gold", "Золотые клетки"],
  ["gold_pick", "Золотая кирка"],
  ["lootbox", "Кейс удачи"],
  ["title_baron", "Титул «Барон»"],
  ["title_magnate", "Титул «Магнат»"],
  ["title_emperor", "Титул «Император»"],
  ["title_legend", "Титул «Легенда»"],
  ["title_deity", "Титул «Божество»"],
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
  $("setHourly").value = settings.hourly_bonus || 0;
  $("setChatUrl").value = settings.chat_url || "";
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
  if ($("setGameDarts")) $("setGameDarts").checked = games.darts !== false;
  if ($("setGameFishing")) $("setGameFishing").checked = games.fishing !== false;
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

function bindAdminEconomy() {
  const $e = (id) => document.getElementById(id);
  const val = (id) => ($e(id) ? $e(id).value : "");
  const num = (id) => parseInt(val(id), 10) || 0;

  if ($e("adminEmitBtn")) $e("adminEmitBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/emit", {
        user_id: num("adminEmitUser"), amount: num("adminEmitAmount"),
        currency: val("adminEmitCur") || "gold", reason: "panel",
      });
      toast(`Эмиссия: баланс игрока ${r.user_id} = ${fmt(r.balance)}`);
    } catch (e) { toast(e.message); }
  });
  if ($e("adminRateBtn")) $e("adminRateBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/rate", {
        currency: val("adminRateCur"), rate: num("adminRateVal"),
      });
      toast(`Курс установлен: ${Object.keys(r.rates).length} валют`);
    } catch (e) { toast(e.message); }
  });
  if ($e("adminTaxBtn")) $e("adminTaxBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/commission", {
        tax_key: val("adminTaxKey"), rate: num("adminTaxVal"),
      });
      toast(`Комиссия обновлена`);
    } catch (e) { toast(e.message); }
  });
  if ($e("adminInflBtn")) $e("adminInflBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/inflation", { pct: num("adminInflVal") });
      toast(`Инфляция ${r.pct || ""}% применена`);
    } catch (e) { toast(e.message); }
  });
  if ($e("adminTokensBtn")) $e("adminTokensBtn").addEventListener("click", async () => {
    try {
      const r = await api("/api/admin/grant-tokens", {
        user_id: num("adminTokensUser"), amount: num("adminTokensAmt"), reason: "panel",
      });
      toast(`Игроку ${r.user_id} выдано жетонов: ${fmt(r.tokens)}`);
    } catch (e) { toast(e.message); }
  });
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
      hourly_bonus: Number($("setHourly").value || 0),
      chat_url: String($("setChatUrl").value || "").trim(),
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
      game_darts: $("setGameDarts") && $("setGameDarts").checked ? 1 : 0,
      game_fishing: $("setGameFishing") && $("setGameFishing").checked ? 1 : 0,
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
  { key: "darts", icon: "🎯", title: "Дартс", desc: "Яблочко, сектор или мимо" },
  { key: "fishing", icon: "🎣", title: "Рыбалка", desc: "Ждать поклёвку и продать" },
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
  if (name === "fishing") loadFish();
  renderGameSwitch();
  closeGameMenu();
}

function clampBet(value) {
  const min = state.settings.min_bet || 10;
  const max = state.settings.max_bet || 100000000;
  const num = Number(value);
  if (!Number.isFinite(num)) return min;
  return Math.max(min, Math.min(max, Math.round(num)));
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
  const boxes = [$("tasksQuests")].filter(Boolean);
  if (!boxes.length) return;
  const items = state.quests || [];
  const hourItems = state.hourQuests || [];
  const card = (q) => {
    const pct = Math.min(100, Math.round((q.progress / q.target) * 100));
    const label = q.claimed
      ? "Получено"
      : q.ready
        ? `Забрать +${fmt(q.reward)} ${q.currency === "gmpoint" ? "GMPOINT" : ""}`
        : `${fmt(q.progress)} / ${fmt(q.target)}`;
    return `<div class="quest${q.ready ? " ready" : ""}${q.claimed ? " done" : ""}">
      <div class="quest-main">
        <div class="quest-title">${escapeHtml(q.title)}</div>
        <div class="quest-bar"><span style="width:${pct}%"></span></div>
      </div>
      <button class="chip-btn quest-claim" data-quest="${q.key}"
        ${q.ready ? "" : "disabled"}>${label}</button>
    </div>`;
  };
  const html = (!items.length ? '<div class="empty">Задания появятся после первой партии</div>' : items.map(card).join(""));
  const hourHtml = hourItems.length ? `<div class="inv-section-title">Задания за час</div>${hourItems.map(card).join("")}` : "";
  boxes.forEach((box) => {
    if (box.id === "tasksQuests") {
      box.innerHTML = (hourItems.length ? `<div class="inv-section-title">Задания за час</div>${hourItems.map(card).join("")}` : "") + (html || '<div class="empty">—</div>');
    } else {
      box.innerHTML = html || '<div class="empty">—</div>';
    }
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
    showCheatHint(data);
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
    showCheatHint(data);
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

/* ---------- дартс ---------- */

function dartsPick() {
  const active = document.querySelector("#dartsPicks .darts-pick.active");
  return active ? active.dataset.dartsPick : "bull";
}

async function playDarts() {
  const input = $("dartsBet");
  const bet = clampBet(parseInt(input.value || "0", 10));
  input.value = bet;
  const stage = $("dartsStage");
  const result = $("dartsResult");
  const btn = $("dartsThrow");
  const score = $("dartsScore");
  const pick = dartsPick();
  btn.disabled = true;
  stage.classList.remove("throw-bull", "throw-sector", "throw-miss");
  result.className = "basket-result";
  result.textContent = "Бросок…";
  if (score) score.textContent = "";
  try {
    const data = await api("/api/games/darts", { bet, pick });
    state.user.balance = data.balance;
    state.quests = data.quests || state.quests;
    showCheatHint(data);
    void stage.offsetWidth;
    stage.classList.add("throw-" + (data.sector || "miss"));
    if (score) score.textContent = String(data.value);
    await new Promise((resolve) => setTimeout(resolve, 900));
    if (data.win) {
      result.textContent = `В цель! ${fmtMult(data.multiplier)} · +${fmt(data.payout)} mCoin`;
      result.className = "basket-result win";
      sfx.cash();
      haptic("success");
      toast(`+${fmt(data.payout)} mCoin`);
      confetti();
      floatWin(`+${fmt(data.payout)}`);
    } else {
      result.textContent = `Сектор ${data.value} — мимо, ставка сгорела`;
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
    sfx.win();
    haptic("success");
    toast(`+${fmt(round.payout)} mCoin`);
    if (round.multiplier >= 2.5) {
      confetti();
      floatWin(`+${fmt(round.payout)}`);
    } else {
      floatWin(`+${fmt(round.payout)}`);
    }
  } else {
    sfx.lose();
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
    showCheatHint(data);
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

let shopCat = "";

const SHOP_SECTIONS = [
  { key: "boosts", title: "Бусты" },
  { key: "items", title: "Расходники" },
  { key: "relics", title: "Реликвии" },
  { key: "prestige", title: "Престиж" },
  { key: "exclusive", title: "Эксклюзив" },
  { key: "cosmetics", title: "Косметика" },
];

const CONSUMABLE_KEYS = new Set([
  "insurance", "double_daily", "charm", "lootbox", "boost_win", "boost_loss",
]);

function shopCard(entry, opts) {
  const options = opts || {};
  const consumable = CONSUMABLE_KEYS.has(entry.key);
  const owned = !!entry.owned && !consumable;
  const canEquip = !!options.equip && owned && !entry.active;
  const currency = entry.currency === "gmpoint" ? "G" : (entry.currency === "level" ? "LVL" : "◈");
  let priceText;
  if (options.levelOnly) priceText = `с ${entry.level} ур.`;
  else if (entry.currency === "level") priceText = `за ${entry.level} ур.`;
  else priceText = `${currency} ${fmt(entry.price)}`;
  const label = owned ? (entry.active ? "Надет" : "Куплено") : (options.buyLabel || "Купить");
  const action = canEquip ? "equip" : "buy";
  const disabled = (owned && !canEquip) || options.levelOnly;
  const title = entry.color
    ? `<span class="${prefixClass(entry)}" style="${prefixStyleCss(entry)}">${escapeHtml(entry.title)}</span>`
    : escapeHtml(entry.title);
  const qty = consumable && entry.qty ? ` <span class="shop-qty">×${entry.qty}</span>` : "";
  const icon = entry.icon
    ? `<img class="shop-icon" src="/static/${entry.icon}" alt="">`
    : "";
  return `<div class="shop-card${owned ? " owned" : ""}${entry.active ? " active" : ""}">
    <div class="shop-meta">
      ${icon}
      <div class="shop-title">${title}${owned ? ' <span class="owned-mark">✓</span>' : ""}${entry.active ? ' <span class="owned-mark">•</span>' : ""}${qty}</div>
      <div class="shop-desc">${escapeHtml(entry.desc || (entry.currency === "level" ? "Награда за уровень" : ""))}</div>
    </div>
    <button class="shop-buy" data-key="${entry.key}" data-act="${action}" ${disabled ? "disabled" : ""}>
      <span class="shop-price">${owned && !canEquip ? label : priceText}</span>
      ${owned && !canEquip ? "Есть" : (canEquip ? "Надеть" : (entry.currency === "gmpoint" ? "За GMPOINT" : label))}
    </button>
  </div>`;
}

function renderShopTabs() {
  const box = $("shopTabs");
  if (!box) return;
  if (!shopCat) shopCat = (SHOP_SECTIONS[0] || {}).key || "";
  box.innerHTML = SHOP_SECTIONS.map((section) =>
    `<button class="shop-tab${section.key === shopCat ? " active" : ""}" data-shop-cat="${section.key}">${section.title}</button>`
  ).join("");
}

function renderShop() {
  const shop = state.shop || {};
  const items = $("shopItems");
  if (items) {
    const active = SHOP_SECTIONS.find((section) => section.key === shopCat)
      || SHOP_SECTIONS[0] || { key: "", title: "" };
    const list = (shop.items || [])
      .filter((item) => item.category === active.key)
      .sort((a, b) => (a.price || 0) - (b.price || 0));
    items.innerHTML = list.length
      ? list.map((item) => shopCard(item)).join("")
      : '<div class="empty">В этой категории пока пусто</div>';
  }
  renderShopTabs();
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
    prefixes.innerHTML = (shop.prefixes || []).slice()
      .sort((a, b) => (a.price || 0) - (b.price || 0))
      .map((item) => {
      const levelOnly = item.currency === "level" || item.currency === "role";
      const style = item.style && item.style !== "solid" ? " · цветная обводка" : "";
      const bonus = Number(item.bonus || 0);
      const bonusPct = Math.round(bonus * 1000) / 10;
      const bonusText = bonus > 0
        ? ` · +${bonusPct % 1 === 0 ? bonusPct.toFixed(0) : bonusPct}% к выплате`
        : "";
      const base = item.desc ? `${item.desc} · ` : "";
      const desc = `${base}Цвет ${item.color}${style}${bonusText}${levelOnly ? ` · открывается на ${item.level} уровне` : ""}`;
      return shopCard({ ...item, desc }, { levelOnly, equip: true });
    }).join("") || '<div class="empty">Пока пусто</div>';
  }
  renderProfilePrefixList();
  const gmp = $("shopGmpoint");
  if (gmp) gmp.textContent = fmt(shop.gmpoint || 0);
  const lootbox = (shop.inventory && shop.inventory.lootbox) || 0;
  const box = $("lootboxCard");
  if (box) box.hidden = lootbox <= 0;
  renderShopInventory();
}

function renderProfilePrefixList() {
  const box = $("profilePrefixList");
  if (!box) return;
  const prefixes = (state.shop && state.shop.prefixes) || [];
  const owned = prefixes.filter((p) => p.owned);
  if (!owned.length) {
    box.innerHTML = '<span class="muted">Купленных префиксов нет — загляни в магазин.</span>';
    return;
  }
  box.innerHTML = owned.map((item) => {
    const active = item.active;
    return `<button class="prefix-pick${active ? " active" : ""}" data-key="${item.key}"
      data-act="${active ? "off" : "equip"}"
      style="${prefixStyleCss(item)}">
      <span class="${prefixClass(item)}">${escapeHtml(item.title)}</span>
      <span class="prefix-pick-state">${active ? "надет · снять" : "надеть"}</span>
    </button>`;
  }).join("");
}

function inventoryIcon(icon) {
  if (!icon) return "";
  if (/\.(jpg|png|webp)$/i.test(icon)) {
    return `<img class="inv-icon" src="/static/${icon}" alt="">`;
  }
  return `<span class="inv-icon">${icon}</span>`;
}

function renderInventory() {
  const box = $("inventorySections");
  if (!box) return;
  const sections = state.inventorySections || [];
  box.innerHTML = sections.map((section) => {
    const items = (section.items || []).map((item) => {
      const qty = item.key === "fish_value" ? `◈ ${fmt(item.qty)}` : `×${item.qty}`;
      const actions = [];
      if (item.use === "open") {
        actions.push(`<button class="inv-act" data-inv="use" data-key="${item.key}" data-qty="1">Открыть</button>`);
        if (item.qty >= 5) {
          actions.push(`<button class="inv-act" data-inv="use" data-key="${item.key}" data-qty="5">×5</button>`);
        }
        if (item.qty >= 2) {
          actions.push(`<button class="inv-act" data-inv="use" data-key="${item.key}" data-qty="${item.qty}" title="Открыть все">Все</button>`);
        }
      }
      if (item.sell && item.sell > 0) {
        actions.push(`<button class="inv-act inv-sell" data-inv="sell" data-key="${item.key}" data-qty="1" title="Продать за ◈ ${fmt(item.sell)}">Продать</button>`);
      }
      const acts = actions.length ? `<span class="inv-actions">${actions.join("")}</span>` : "";
      return `<span class="inv-item">${inventoryIcon(item.icon)}<span>${escapeHtml(item.title)}</span><b>${qty}</b>${acts}</span>`;
    }).join("");
    return `<div class="inv-section"><div class="inv-section-title">${escapeHtml(section.title)}</div><div class="inv-items">${items || '<span class="muted">Пусто</span>'}</div></div>`;
  }).join("") || '<div class="muted">Загрузка…</div>';
}

async function inventoryAction(act, key, qtyOverride) {
  try {
    const data = await api(`/api/inventory/${act}`, { key, qty: qtyOverride || 1 });
    if (act === "sell") {
      toast(`Продано: +${fmt(data.total)} mCoin`);
      state.balance = data.balance;
      state.shop.balance = data.balance;
    } else if (act === "use") {
      toast(`${data.title || "Открыто"}`);
      state.balance = data.balance;
      state.shop.balance = data.balance;
    }
    state.inventorySections = data.sections || [];
    state.shop.inventory = data.inventory || state.shop.inventory;
    renderInventory();
    renderBalance();
  } catch (e) {
    toast(e.message);
  }
}

async function loadInventory() {
  try {
    const data = await api("/api/inventory", {});
    state.inventorySections = data.sections || [];
    renderInventory();
  } catch (e) {}
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
    renderCosmetics();
  } catch (e) {
    toast(e.message);
  }
}

function applyGameBackground() {
  const layer = $("gameBg");
  if (!layer) return;
  const url = state.user && state.user.game_bg_url;
  if (url) {
    layer.style.backgroundImage = `url("${url}")`;
    layer.classList.add("active");
  } else {
    layer.style.backgroundImage = "";
    layer.classList.remove("active");
  }
}

function renderGameBgGallery() {
  const box = $("gameBgGallery");
  if (!box) return;
  const list = (state.cosmetics && state.cosmetics.game_backgrounds) || [];
  box.innerHTML = list.map((item) => {
    const thumb = item.url
      ? `<span class="bg-scene" style="background-image:url('${item.url}')"></span>`
      : '<span class="bg-scene bg-scene-default"></span>';
    const price = item.owned ? "" : `<span class="cos-price">◈ ${fmt(item.price)}</span>`;
    const label = item.key === "custom" ? "Своё фото" : item.title;
    const act = item.owned ? "equip" : (item.key === "custom" ? "upload" : "buy");
    return `<button class="bg-item${item.active ? " active" : ""}${item.owned ? "" : " locked"}"
      data-kind="gamebg" data-key="${item.key}" data-act="${act}" title="${escapeHtml(item.title)}">
      ${thumb}<span class="cos-name">${escapeHtml(label)}</span>${price}
    </button>`;
  }).join("") || '<span class="muted">Загрузка…</span>';
}

function renderCosmetics() {
  const av = $("avatarGallery");
  const bg = $("bgGallery");
  const data = state.cosmetics || {};
  if (av) {
    av.innerHTML = (data.avatars || []).map((item) => {
      const cls = `cos-item${item.active ? " active" : ""}${item.owned ? "" : " locked"}`;
      const act = item.key === "custom" && !item.owned ? "upload" : (item.owned ? "equip" : "buy");
      const inner = item.url
        ? `<img class="cos-avatar-img" src="${item.url}" alt="">`
        : `<span class="cos-emoji">${item.icon || "А"}</span>`;
      const price = item.key === "custom" && !item.owned ? "" : (item.owned ? "" : `<span class="cos-price">◈ ${fmt(item.price)}</span>`);
      return `<button class="${cls}" data-kind="avatar" data-key="${item.key}" data-act="${act}" title="${escapeHtml(item.title)}">
        ${inner}<span class="cos-name">${escapeHtml(item.title)}</span>${price}
      </button>`;
    }).join("") || '<span class="muted">Загрузка…</span>';
  }
  if (bg) {
    bg.innerHTML = (data.backgrounds || []).map((item) => {
      const cls = `cos-item cos-item-bg${item.active ? " active" : ""}${item.owned ? "" : " locked"}`;
      const price = item.owned ? "" : `<span class="cos-price">◈ ${fmt(item.price)}</span>`;
      return `<button class="${cls}" data-kind="background" data-key="${item.key}" data-act="${item.owned ? "equip" : "buy"}" title="${escapeHtml(item.title)}">
        <span class="cos-bg" style="background:${item.css}"></span>
        <span class="cos-name">${escapeHtml(item.title)}</span>${price}
      </button>`;
    }).join("") || '<span class="muted">Загрузка…</span>';
  }
  renderGameBgGallery();
  applyGameBackground();
}

function showCheatHint(data) {
  if (!data || !data.cheat || !data.cheat.enabled || !state.isAdmin) return;
  const c = data.cheat;
  const text = c.hint || (c.correct ? `Правильно: ${c.correct}` : "");
  if (text) toast(`👁 ${text}`);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function loadImageElement(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

async function compressBackground(file) {
  const dataUrl = await readFileAsDataUrl(file);
  const img = await loadImageElement(dataUrl);
  const maxW = 1600;
  const maxH = 1000;
  const scale = Math.min(1, maxW / img.width, maxH / img.height);
  const w = Math.max(1, Math.round(img.width * scale));
  const h = Math.max(1, Math.round(img.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d").drawImage(img, 0, 0, w, h);
  let quality = 0.85;
  let out = canvas.toDataURL("image/jpeg", quality);
  while (out.length * 0.75 > 380000 && quality > 0.45) {
    quality -= 0.08;
    out = canvas.toDataURL("image/jpeg", quality);
  }
  return out;
}

async function uploadAvatar(file) {
  try {
    if (!file) return;
    if (!file.type || file.type.indexOf("image/") !== 0) {
      toast("Нужно изображение");
      return;
    }
    toast("Готовим фото…");
    const image = await compressBackground(file);
    const data = await api("/api/profile/avatar/upload", { image });
    state.cosmetics = data;
    if (data.user) state.user = { ...state.user, ...data.user };
    haptic("success");
    toast("Аватар обновлён");
    renderCosmetics();
    renderProfile();
    if (typeof loadLeaderboard === "function") loadLeaderboard();
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

async function uploadBackground(file) {
  const hint = $("bgUploadHint");
  try {
    if (!file) return;
    if (!file.type || file.type.indexOf("image/") !== 0) {
      toast("Нужно изображение");
      return;
    }
    if (hint) hint.textContent = "Готовим фото…";
    const image = await compressBackground(file);
    const data = await api("/api/profile/background/upload", { image });
    state.cosmetics = data;
    if (data.user) state.user = { ...state.user, ...data.user };
    haptic("success");
    toast("Фон игры обновлён");
    renderCosmetics();
    renderProfile();
  } catch (e) {
    haptic("error");
    toast(e.message);
  } finally {
    if (hint) hint.textContent = "JPEG, PNG или WEBP. Фото сожмётся автоматически.";
  }
}

async function loadCosmetics() {
  try {
    const data = await api("/api/profile/cosmetics", { action: "list" });
    state.cosmetics = data;
    renderCosmetics();
  } catch (e) {
    // тихо: галерея не критична
  }
}

async function cosmeticAction(kind, key, act) {
  try {
    const data = await api("/api/profile/cosmetics", { action: act, kind, key });
    state.cosmetics = data;
    if (data.user) state.user = { ...state.user, ...data.user };
    if (data.balance !== undefined) state.user.balance = data.balance;
    haptic("success");
    toast(act === "buy" ? "Куплено и надето" : "Оформление применено");
    renderCosmetics();
    renderProfile();
    renderBalance();
    if (act === "buy") loadShop().catch(() => {});
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

async function equipPrefix(key) {
  try {
    const data = await api("/api/prefix/equip", { key });
    if (data.user) state.user = { ...state.user, ...data.user };
    const shopPrefixes = (state.shop && state.shop.prefixes) || [];
    shopPrefixes.forEach((p) => { p.active = p.key === key; });
    haptic("success");
    toast(key ? "Префикс надет" : "Префикс снят");
    renderProfile();
    renderProfilePrefixList();
    renderShop();
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

async function openLootbox() {
  try {
    const data = await api("/api/shop/use", { key: "lootbox" });
    state.user.balance = data.balance;
    state.shop.inventory = data.inventory || {};
    sfx.ticket();
    haptic("success");
    toast("Кейс: " + data.title);
    if (data.reward && data.reward.kind === "coins") {
      confetti();
      floatWin(`+${fmt(data.reward.value || data.reward.amount || 0)}`);
    }
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
    sfx.purchase();
    haptic("success");
    toast(`Куплено: ${data.bought}`);
    renderAll();
    renderShop();
    loadShop().catch(() => {});
    if (data.prefix) loadState().catch(() => {});
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
    showCheatHint(data);
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
    dismissed = localStorage.getItem("saper_seen_version") || "";
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
    if (data.gmpoint != null) state.user.gmpoint = data.gmpoint;
    state.quests = data.quests || state.quests;
    hint.textContent = data.currency === "gmpoint"
      ? `Промокод принят: +${fmt(data.amount)} GMPOINT`
      : `Промокод принят: +${fmt(data.amount)} mCoin`;
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

/* ---------- рыбалка ---------- */
let fishCurrent = null;

function renderFishSell() {
  const total = (state.fishItems || []).reduce((sum, f) => sum + (f.price || 0), 0);
  if ($("fishTotal")) $("fishTotal").textContent = fmt(total);
}

function fishCard(fish) {
  const grams = fish.weight_g >= 1000
    ? `${(fish.weight_g / 1000).toFixed(2)} кг` : `${fish.weight_g} г`;
  $("fishResult").innerHTML =
    `<div><b>${fish.name}</b> · <span class="rarity">${fish.rarity_title}</span></div>
     <div>Вес: ${grams} · скупщик даёт <b>${fmt(fish.price)}</b> mCoin</div>
     <div class="fish-actions"><button class="secondary" id="fishSellOne">
       Продать за ${fmt(fish.price)}</button></div>`;
  $("fishSellOne").addEventListener("click", () => sellFish(fish.id));
}

function fishLock(seconds) {
  const castBtn = $("fishCast");
  if (!castBtn) return;
  let left = Math.max(0, Math.round(seconds));
  castBtn.disabled = true;
  const label = castBtn.textContent;
  const tick = () => {
    if (left <= 0) {
      castBtn.disabled = false;
      castBtn.textContent = label;
      return;
    }
    castBtn.textContent = `Ждать ${left} с`;
    left -= 1;
    setTimeout(tick, 1000);
  };
  tick();
}

function fishMiss(data, message) {
  $("fishStage").innerHTML = `<div class="fish-hint">${data.icon || "🐟"} ${message}</div>`;
  $("fishResult").textContent = "";
  toast(message);
  haptic("error");
  fishLock(data.lock_seconds || 15);
}

async function castFish() {
  const castBtn = $("fishCast");
  if (!castBtn || castBtn.disabled) return;
  castBtn.disabled = true;
  $("fishResult").textContent = "";
  try {
    const data = await api("/api/fish/catch", {});
    const total = data.cells || 25;
    const parts = [];
    for (let i = 0; i < total; i += 1) {
      const hit = i === data.cell;
      parts.push(`<button class="fish-cell${hit ? " has-fish" : ""}" data-cell="${i}">${hit ? data.icon : ""}</button>`);
    }
    $("fishStage").innerHTML =
      `<div class="fish-grid">${parts.join("")}</div>
       <div class="fish-hint">Успей схватить: <b id="fishLeft">${(data.seconds || 3).toFixed(1)}</b> с</div>`;
    const stage = $("fishStage");
    const left = $("fishLeft");
    const budget = data.seconds || 3;
    const started = Date.now();
    let done = false;
    const timer = setInterval(() => {
      const rest = budget - (Date.now() - started) / 1000;
      if (left) left.textContent = Math.max(0, rest).toFixed(1);
      if (rest <= 0 && !done) {
        done = true;
        clearInterval(timer);
        fishMiss(data, "Не успели — рыба ушла");
      }
    }, 100);
    stage.querySelectorAll(".fish-cell").forEach((cell) => {
      cell.addEventListener("click", async () => {
        if (done) return;
        done = true;
        clearInterval(timer);
        const picked = Number(cell.dataset.cell);
        if (picked !== data.cell) {
          fishMiss(data, "Мимо — рыба ушла");
          return;
        }
        try {
          const caught = await api("/api/fish/grab", { cell: picked });
          fishCurrent = caught;
          stage.innerHTML = `<div class="fish-hint">${caught.icon} Поймали: <b>${caught.name}</b></div>`;
          fishCard(caught);
          state.fishItems = (state.fishItems || []).concat([caught]);
          renderFishSell();
          sfx.coin();
          haptic("success");
        } catch (e) {
          fishMiss(data, e.message);
        }
      });
    });
  } catch (e) {
    $("fishStage").innerHTML = `<div class="fish-hint">${e.message}</div>`;
    toast(e.message);
  } finally {
    castBtn.disabled = false;
  }
}

async function sellFish(id) {
  try {
    const data = await api("/api/fish/sell", { id });
    state.user.balance = data.balance;
    state.fishItems = (state.fishItems || []).filter((f) => f.id !== id);
    $("fishResult").innerHTML = `Продано за <b>${fmt(data.amount)}</b> mCoin`;
    renderFishSell();
    renderBalance();
    sfx.cash();
  } catch (e) {
    toast(e.message);
  }
}

async function sellAllFish() {
  try {
    const data = await api("/api/fish/sell", { all: true });
    state.user.balance = data.balance;
    state.fishItems = [];
    $("fishResult").innerHTML =
      `Скупщик забрал ${data.sold} шт. за <b>${fmt(data.amount)}</b> mCoin`;
    renderFishSell();
    renderBalance();
    sfx.cash();
  } catch (e) {
    toast(e.message);
  }
}

async function loadFish() {
  try {
    const data = await api("/api/fish/list", {});
    state.fishItems = data.items || [];
    renderFishSell();
  } catch (e) {}
  loadRods();
}

function renderRods() {
  const grid = $("rodGrid");
  if (!grid) return;
  const data = state.rods || { rods: [], rod_key: "bamboo" };
  const list = data.rods || [];
  grid.innerHTML = list.map((rod) => {
    const active = rod.key === data.rod_key;
    const price = rod.owned ? "" : `<span class="rod-price">◈ ${fmt(rod.price)}</span>`;
    const act = rod.owned ? (active ? "" : "equip") : "buy";
    return `<div class="rod-card${active ? " active" : ""}${rod.owned ? "" : " locked"}">
      <div class="rod-icon">${rod.icon_file
        ? `<img src="/static/${rod.icon_file}" alt="" onerror="this.remove()">`
        : (rod.icon || "🎣")}</div>
      <div class="rod-info">
        <div class="rod-title">${escapeHtml(rod.title)}${active ? ' <span class="owned-mark">•</span>' : ""}</div>
        <div class="rod-desc">${escapeHtml(rod.desc)}</div>
        ${price}
      </div>
      <button class="rod-btn" data-rod="${rod.key}" data-act="${act}" ${active ? "disabled" : ""}>
        ${active ? "Надета" : rod.owned ? "Надеть" : "Купить"}
      </button>
    </div>`;
  }).join("") || '<div class="empty">Загрузка…</div>';
}

async function loadRods() {
  try {
    const data = await api("/api/fish/rods", { action: "list" });
    state.rods = data;
    renderRods();
  } catch (e) {}
}

async function rodAction(key, act) {
  try {
    const data = await api("/api/fish/rods", { action: act, key });
    state.rods = data;
    if (data.balance !== undefined) state.user.balance = data.balance;
    haptic("success");
    toast(act === "buy" ? "Удочка куплена и надета" : "Удочка надета");
    renderRods();
    renderBalance();
  } catch (e) {
    haptic("error");
    toast(e.message);
  }
}

let renderPending = false;

function renderAll() {
  if (renderPending) return;
  renderPending = true;
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => {
      renderPending = false;
      if (document.hidden) return;
      renderAllNow();
    });
    return;
  }
  renderPending = false;
  renderAllNow();
}

function currentViewName() {
  const v = document.querySelector(".view.active");
  return v ? v.id.replace("view-", "") : "game";
}

function renderAllNow() {
  renderBalance();
  renderDaily();
  renderBonus();
  applyCosmetics();
  applyGameBackground();
  const v = currentViewName();
  if (v === "profile") { renderProfile(); return; }
  if (v === "tasks") { renderTasks(); renderDailySpin(); return; }
  if (v === "bank") { renderBank(); return; }
  if (v === "games") { renderGamesHub(); return; }
  if (v === "history") { renderHistory(); return; }
  if (v === "fair") { renderFair(); return; }
  if (v === "top") {
    const topTab = document.querySelector("#view-top .tab.active");
    renderTop(topTab ? topTab.dataset.tab : "balance");
    return;
  }
  if (v === "social") {
    renderSocialOnce();
    return;
  }
  if (v === "shop" || v === "admin") {
    renderAutoPanel();
    renderTournaments();
    renderNotifications();
    return;
  }
  renderMines();
  renderGameSwitch();
  renderControls();
  renderGrid();
  renderLadder();
  renderBlackjack();
  renderAutoPanel();
  renderTournaments();
  renderNotifications();
}

let socialInited = false;
function renderSocialOnce() {
  renderAutoPanel();
  renderTournaments();
  renderNotifications();
  renderClans();
  renderFriends();
  renderLeagues();
  renderAchievementsDetail();
  renderNewPanels();
  if (socialInited) return;
  socialInited = true;
  loadSocialExtras();
  loadAllNew();
}

const socialCacheTTL = 60000;
const socialLoadedAt = {};
function socialCache(key) {
  return socialLoadedAt[key] && (Date.now() - socialLoadedAt[key] < socialCacheTTL);
}
function socialMark(key) { socialLoadedAt[key] = Date.now(); }
function loadSocialLazy() {
  const jobs = [
    ["extra", loadExtraProgression],
    ["ency", loadEncyclopedia],
    ["live", loadLiveEvents],
    ["rest", loadRestaurantMedals],
    ["dung", loadDungeonGifts],
    ["pvp", loadPvp],
    ["workers", loadWorkers],
    ["farm", loadFarm],
    ["bp", loadBattlepass],
    ["an", loadAnalytics],
    ["cal", loadCalendar],
    ["np", loadNewsPartners],
    ["eco", loadEconomy],
    ["guild", loadGuild],
    ["map", loadMap],
    ["tour", loadTournament],
    ["cards", loadCardMarket],
    ["street", loadStreet],
    ["club", loadClub],
    ["pet", loadPet],
  ];
  for (const [key, fn] of jobs) {
    if (socialCache(key)) continue;
    socialMark(key);
    try { fn(); } catch (e) {}
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) renderAll();
});

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
  state.rank = Number(data.rank) || 0;
  state.account = data.account || null;
  state.quests = data.quests || state.quests;
  state.hourQuests = data.hour_items || state.hourQuests;
  state.achievements = data.achievements || state.achievements;
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
      if (data.cheat) state.cheat = data.cheat;
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
    if (data.cheat) state.cheat = data.cheat;
    state.user.balance = data.balance;
    if (data.finished) sfx.cash(); else sfx.open();
    renderAll();
    if (data.finished) {
      haptic("success");
      confetti();
      if (data.payout > 0) floatWin(`+${fmt(data.payout)}`);
      if (data.capped) {
        modal("🧨", "Достигнут потолок ×100", `Авто-вывод: ${fmt(data.payout)} mCoin. Дальше множитель не растёт.`, "Ещё раз");
      } else if (data.auto) {
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
  const maxBet = state.settings.max_bet || 100000000;
  const bet = Math.max(minBet, Math.min(maxBet, parseInt($("betInput").value || "0", 10) || 0));
  state.bet = bet;
  state.lastBet = bet;
  const autoTarget = Number(($("autoTarget") && $("autoTarget").value) || 0);
  state.autoTarget = autoTarget;
  try {
    const data = await api("/api/game/start", { bet, mines: state.mines, auto_target: autoTarget });
    state.round = data.round;
    if (data.cheat) state.cheat = data.cheat;
    else delete state.cheat;
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
    floatWin(`+${fmt(data.payout)}`);
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
  const navGroup = name === "tasks" ? "shop" : name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === navGroup));
  document.querySelectorAll("[data-shop-tab]").forEach((t) =>
    t.classList.toggle("active", t.dataset.shopTab === name)
  );
  if (name === "top") loadTop();
  if (name === "history") loadHistory();
  if (name === "admin") loadAdmin();
  if (name === "shop") loadShop();
  if (name === "profile") {
    renderProfile();
    loadCosmetics();
    loadInventory();
    loadProfileStats();
    if (!(state.shop && (state.shop.prefixes || []).length)) loadShop();
    else renderProfilePrefixList();
  }
  if (name === "tasks") renderTasks();
  if (name === "bank") renderBank();
  if (name === "games") renderGamesHub();
  if (name === "social") {
    renderSocialOnce();
    if (!socialInited) {
      socialInited = true;
      loadSocialExtras();
      loadAllNew();
    }
    loadSocialLazy();
  }
}

async function loadTop() {
  try {
    const data = await api("/api/leaderboard");
    state.leaderboard.by_balance = data.by_balance;
    state.leaderboard.by_multiplier = data.by_multiplier;
    state.leaderboard.by_level = data.by_level || state.leaderboard.by_level;
    state.leaderboard.weekly = data.weekly || state.leaderboard.weekly;
    state.leaderboard.me = data.me;
  const topTab = document.querySelector("#view-top .tab.active");
  renderTop(topTab ? topTab.dataset.tab : "balance");
  } catch (e) {}
}

async function loadProfileStats() {
  try {
    const data = await api("/api/profile/stats");
    state.stats = data;
    renderProfileStats();
  } catch (e) {}
}

function renderProfileStats() {
  const sum = $("statsSummary");
  const box = $("statsGames");
  if (!sum || !box) return;
  const s = (state.stats && state.stats.summary) || {};
  const rows = (state.stats && state.stats.by_game) || [];
  sum.innerHTML = `
    <div class="stat"><span class="stat-value">${fmt(s.rounds || 0)}</span><span class="stat-label">всего игр</span></div>
    <div class="stat"><span class="stat-value">${fmt(s.wagered || 0)}</span><span class="stat-label">оборот</span></div>
    <div class="stat"><span class="stat-value">${s.winrate || 0}%</span><span class="stat-label">побед</span></div>
    <div class="stat"><span class="stat-value">${s.rtp || 0}%</span><span class="stat-label">отдача</span></div>`;
  box.innerHTML = rows.length
    ? rows.map((r) => `
      <div class="row stats-game-row">
        <span class="row-icon">${r.icon || "🎮"}</span>
        <div class="row-main">
          <div class="row-title">${r.title} <small class="stats-wr">${r.winrate}% побед</small></div>
          <div class="row-sub">${fmt(r.rounds)} игр · оборот ${fmt(r.wagered)} · возврат ${fmt(r.paid)}</div>
        </div>
        <div class="row-value">${r.wins} 🏆</div>
      </div>`).join("")
    : '<div class="empty">Сыграй хоть одну партию, чтобы видеть статистику</div>';
}

async function loadHistory() {
  try {
    const data = await api("/api/history");
    state.history = data.items;
    renderHistory();
  } catch (e) {}
}

function syncSettingsUI() {
  const s = $("setSound");
  if (s) s.checked = !!state.sound;
  const v = $("setVibrate");
  if (v) v.checked = state.vibrate !== false;
  const vol = $("setVolume");
  if (vol) vol.value = String(Math.round((state.soundVol || 1) * 100));
  const a = $("setAnim");
  if (a) a.checked = state.anim !== false;
}

function bindSettings() {
  const s = $("setSound");
  if (s) s.addEventListener("change", () => {
    state.sound = s.checked;
    try { localStorage.setItem("saper_sound", state.sound ? "1" : "0"); } catch (e) {}
    if (state.sound) sfx.open();
    toast(state.sound ? "Звук включён" : "Звук выключен");
  });
  const v = $("setVibrate");
  if (v) v.addEventListener("change", () => {
    state.vibrate = v.checked;
    try { localStorage.setItem("saper_vibrate", state.vibrate ? "1" : "0"); } catch (e) {}
    if (state.vibrate) haptic("light");
    toast(state.vibrate ? "Вибрация включена" : "Вибрация выключена");
  });
  const vol = $("setVolume");
  if (vol) vol.addEventListener("input", () => {
    state.soundVol = Number(vol.value) / 100;
    try { localStorage.setItem("saper_vol", String(state.soundVol)); } catch (e) {}
  });
  const a = $("setAnim");
  if (a) a.addEventListener("change", () => {
    state.anim = a.checked;
    try { localStorage.setItem("saper_anim", state.anim ? "1" : "0"); } catch (e) {}
    toast(state.anim ? "Анимации включены" : "Анимации выключены");
  });
  const cl = $("setClear");
  if (cl) cl.addEventListener("click", () => {
    try {
      localStorage.removeItem("saper_sound");
      localStorage.removeItem("saper_vibrate");
      localStorage.removeItem("saper_vol");
      localStorage.removeItem("saper_anim");
      localStorage.removeItem("saper_theme");
      toast("Настройки сброшены");
    } catch (e) {}
  });
}

function renderWars() {
  const box = $("warBox");
  if (!box) return;
  const wars = state.wars || [];
  box.innerHTML = wars.length
    ? wars.map((w) =>
      `<div class="war-card">
        <div class="war-head">
          <span class="war-clan">[${w.clan_a.tag}] ${w.clan_a.name}</span>
          <span class="war-score">${w.clan_a.score} : ${w.clan_b.score}</span>
          <span class="war-clan">${w.clan_b.name} [${w.clan_b.tag}]</span>
        </div>
        <div class="war-meta">Приз: ${fmt(w.clan_a.prize)} ◈ · до конца ${Math.floor(w.seconds_left / 3600)} ч</div>
        <div class="war-actions">
          <button class="secondary small" data-war-bet="${w.id}" data-side="a">Ставка на [${w.clan_a.tag}]</button>
          <button class="secondary small" data-war-bet="${w.id}" data-side="b">Ставка на [${w.clan_b.tag}]</button>
        </div>
      </div>`).join("")
    : `<div class="empty">Войн кланов сейчас нет</div>`;
  box.querySelectorAll("[data-war-bet]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const amount = prompt("Сумма ставки:");
      if (!amount) return;
      try {
        const data = await api("/api/wars/bet", {
          war_id: btn.dataset.warBet, side: btn.dataset.side,
          amount: Number(amount),
        });
        state.user.balance = data.balance;
        state.wars = (await api("/api/wars")).wars;
        renderAll();
        toast("Ставка принята!");
      } catch (e) { toast(e.message); }
    });
  });
}

function renderRaids() {
  const box = $("raidBox");
  if (!box) return;
  const raids = state.raids || [];
  box.innerHTML = raids.length
    ? raids.map((r) =>
      `<div class="raid-card">
        <div class="raid-head">👹 ${r.boss} · HP <b>${r.hp}</b>/${r.max_hp}</div>
        <div class="raid-bar"><div class="raid-fill" style="width:${Math.round(r.hp / r.max_hp * 100)}%"></div></div>
        <div class="raid-meta">Награда: ${fmt(r.reward)} · Ходов: ${Math.floor(r.seconds_left / 60)} мин</div>
        ${r.hits.length ? `<div class="raid-hits">${r.hits.slice(0, 5).map((h) =>
          `<span>${h.first_name || h.username} — ${h.damage}</span>`).join("")}</div>` : ""}
        <button class="secondary small" data-raid-hit="${r.id}">⚔ Атаковать</button>
      </div>`).join("")
    : `<div class="empty">Рейдов нет — лидер клана может начать</div>`;
  box.querySelectorAll("[data-raid-hit]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/raids/hit", { raid_id: btn.dataset.raidHit });
        toast(`Урон: ${data.damage}${data.killed ? " · Босс повержен!" : ""}`);
        if (data.killed) confetti();
        state.raids = (await api("/api/raids")).raids;
        renderAll();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderLoans() {
  const box = $("loanBox");
  if (!box) return;
  const data = state.loans || { loans: [], plans: [] };
  const loans = data.loans || [];
  box.innerHTML =
    `<div class="loan-plans">${(data.plans || []).map((p) =>
      `<button class="secondary small" data-loan-plan="${p.days}">${p.days} дн · ${p.rate_bps / 100}%</button>`).join("")}</div>
    <div class="loan-create">
      <input id="loanAmount" class="input" type="number" value="10000" min="1000" max="500000">
      <button class="cta small" id="loanTake">Взять кредит</button>
    </div>
    <div class="loan-list">${loans.length ? loans.map((l) =>
      `<div class="loan-row">
        <span>${fmt(l.amount)} · долг ${fmt(l.owed)}</span>
        <button class="secondary small" data-loan-pay="${l.id}" ${l.status !== "active" ? "disabled" : ""}>
          ${l.status === "active" ? "Погасить" : "Закрыт"}
        </button>
      </div>`).join("") : '<div class="empty">Кредитов нет</div>'}</div>`;
  const take = box.querySelector("#loanTake");
  if (take) take.addEventListener("click", async () => {
    try {
      const data = await api("/api/loans/take", {
        amount: Number((box.querySelector("#loanAmount") || {}).value) || 10000,
        term_days: Number(state.loanPlan || 7),
      });
      state.user.balance = data.balance;
      state.loans = await api("/api/loans");
      renderAll();
      toast("Кредит выдан!");
      sfx.cash();
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-loan-plan]").forEach((btn) => {
    btn.addEventListener("click", () => { state.loanPlan = Number(btn.dataset.loanPlan); });
  });
  box.querySelectorAll("[data-loan-pay]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/loans/pay", { loan_id: btn.dataset.loanPay, amount: 999999999 });
        state.user.balance = data.balance;
        state.loans = await api("/api/loans");
        renderAll();
        toast(`Погашено: ${fmt(data.paid)}`);
      } catch (e) { toast(e.message); }
    });
  });
}

function renderStreaks() {
  const box = $("streakBox");
  if (!box) return;
  const data = state.streaks || { streak: 0, rewards: [] };
  const rewards = data.rewards || [];
  const cur = data.streak || 0;
  box.innerHTML =
    `<div class="streak-head">🔥 Серия: <b>${cur}</b> день(дня)</div>
    <div class="streak-dots">${rewards.map((r, i) =>
      `<span class="streak-dot ${i < cur ? "done" : ""}" title="${i + 1} дн — ${fmt(r)}">${i + 1}</span>`).join("")}</div>
    <button class="cta small" id="streakClaim" ${data.claimed_today ? "disabled" : ""}>
      ${data.claimed_today ? "Забрано сегодня" : "Забрать награду"}
    </button>`;
  const claim = box.querySelector("#streakClaim");
  if (claim) claim.addEventListener("click", async () => {
    try {
      const data = await api("/api/streaks/claim");
      state.user.balance = data.balance;
      state.streaks = await api("/api/streaks");
      renderAll();
      toast(`Серия ${data.streak}: +${fmt(data.reward)}!`);
      confetti();
    } catch (e) { toast(e.message); }
  });
}

function renderChests() {
  const box = $("chestBox");
  if (!box) return;
  const chests = state.chests || [];
  box.innerHTML = chests.map((c) =>
    `<div class="chest-row">
      <span>🎁 ${c.title}</span>
      <button class="secondary small" data-chest="${c.key}" ${c.ready ? "" : "disabled"}>
        ${c.ready ? "Открыть" : "ещё " + Math.floor(c.next_in / 3600) + " ч"}
      </button>
    </div>`).join("") || '<div class="empty">Нет сундуков</div>';
  box.querySelectorAll("[data-chest]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/chests/open", { key: btn.dataset.chest });
        state.user.balance = data.balance;
        state.chests = (await api("/api/chests")).chests;
        renderAll();
        toast(`+${fmt(data.reward)} ◈${data.extra.gmpoint ? ` · +${data.extra.gmpoint} G` : ""}`);
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderCraft() {
  const box = $("craftBox");
  if (!box) return;
  const data = state.craft || { recipes: [], jobs: [], inventory: {} };
  const recipes = data.recipes || [];
  const jobs = data.jobs || [];
  box.innerHTML =
    `<div class="craft-jobs">${jobs.length ? jobs.map((j) =>
      `<div class="craft-job">🛠 ${j.recipe_id} · ${j.status === "done" ? "готово" : Math.floor(j.seconds_left / 60) + " мин"}</div>`).join("") : ""}</div>
    <div class="craft-list">${recipes.map((r) =>
      `<div class="craft-row ${r.ready ? "ready" : ""}">
        <div class="craft-info">
          <span class="craft-out">→ ${r.output} ×${r.output_qty}</span>
          <span class="craft-in">${Object.entries(r.inputs).map(([k, v]) => `${k} ${data.inventory[k] || 0}/${v}`).join(" · ")}</span>
        </div>
        <button class="secondary small" data-craft="${r.id}" ${r.ready ? "" : "disabled"}>Крафт</button>
      </div>`).join("")}</div>
    <button class="secondary small" id="craftRefresh">Обновить</button>`;
  box.querySelectorAll("[data-craft]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/craft/start", { recipe_id: btn.dataset.craft });
        state.craft = await api("/api/craft");
        renderAll();
        toast("Крафт запущен!");
      } catch (e) { toast(e.message); }
    });
  });
  const refresh = box.querySelector("#craftRefresh");
  if (refresh) refresh.addEventListener("click", async () => {
    state.craft = await api("/api/craft");
    renderAll();
  });
}

function renderShips() {
  const box = $("shipBox");
  if (!box) return;
  const ships = state.ships || [];
  box.innerHTML = ships.map((s) =>
    `<div class="ship-row ${s.owned ? "owned" : ""}">
      <span>⛵ ${s.title} ${s.xp ? `(ур. ${Math.ceil(Math.sqrt(s.xp / 200))})` : ""}</span>
      <button class="secondary small" data-ship="${s.key}" ${s.owned || s.xp_now < s.xp ? "disabled" : ""}>
        ${s.owned ? "Куплен" : s.xp_now < s.xp ? "Нужен уровень" : fmt(s.cost)}
      </button>
    </div>`).join("") || '<div class="empty">Кораблей нет</div>';
  box.querySelectorAll("[data-ship]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/ships/buy", { key: btn.dataset.ship });
        state.user.balance = data.balance;
        state.ships = (await api("/api/ships")).ships;
        renderAll();
        toast("Корабль куплен!");
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadAllNew() {
  try {
    const [wars, raids, loans, streaks, chests, craft, ships] = await Promise.all([
      api("/api/wars").catch(() => null),
      api("/api/raids").catch(() => null),
      api("/api/loans").catch(() => null),
      api("/api/streaks").catch(() => null),
      api("/api/chests").catch(() => null),
      api("/api/craft").catch(() => null),
      api("/api/ships").catch(() => null),
    ]);
    if (wars) state.wars = wars.wars;
    if (raids) state.raids = raids.raids;
    if (loans) state.loans = loans;
    if (streaks) state.streaks = streaks;
    if (chests) state.chests = chests.chests;
    if (craft) state.craft = craft;
    if (ships) state.ships = ships.ships;
  } catch (e) {}
}

function renderUserSearch() {
  const box = $("searchBox");
  if (!box) return;
  const users = state.searchUsers || [];
  box.innerHTML =
    `<div class="search-row">
      <input id="searchInput" class="input" placeholder="Логин, имя или ID…">
      <button class="secondary small" id="searchGo">Найти</button>
    </div>
    <div class="search-results">${users.length ? users.map((u) =>
      `<div class="search-user">
        <span>${u.first_name || u.username || u.user_id} @${u.username || "—"} · ${fmt(u.balance)} ◈</span>
        ${u.is_friend ? '<span class="muted">— друг</span>' : `<button class="secondary small" data-search-friend="${u.user_id}">В друзья</button>`}
      </div>`).join("") : '<div class="empty">Введите 2+ символа</div>'}</div>`;
  const btn = box.querySelector("#searchGo");
  const input = box.querySelector("#searchInput");
  if (input) input.addEventListener("keydown", (e) => { if (e.key === "Enter" && btn) btn.click(); });
  if (btn) btn.addEventListener("click", async () => {
    try {
      const q = (box.querySelector("#searchInput") || {}).value || "";
      const data = await api("/api/users/search", { query: q });
      state.searchUsers = data.users || [];
      renderUserSearch();
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-search-friend]").forEach((b) => {
    b.addEventListener("click", async () => {
      try {
        await api("/api/friends/add", { user_id: b.dataset.searchFriend });
        toast("Заявка отправлена!");
        state.searchUsers = (state.searchUsers || []).map((u) =>
          u.user_id == b.dataset.searchFriend ? { ...u, is_friend: true } : u);
        renderAll();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderProfileAbilities() {
  const box = $("abilityBox");
  if (!box) return;
  const s = (state.stats && state.stats.summary) || {};
  const level = state.levels || {};
  const ships = state.ships || [];
  const owned = ships.filter((x) => x.owned).length;
  box.innerHTML =
    `<div class="ability-grid">
      <div class="ability"><span class="ability-icon">🏅</span><span class="ability-val">${level.level || 1}</span><span class="ability-label">уровень</span></div>
      <div class="ability"><span class="ability-icon">🔥</span><span class="ability-val">${(state.streaks && state.streaks.streak) || 0}</span><span class="ability-label">стрик</span></div>
      <div class="ability"><span class="ability-icon">⛵</span><span class="ability-val">${owned}</span><span class="ability-label">корабли</span></div>
      <div class="ability"><span class="ability-icon">🏆</span><span class="ability-val">${s.rounds || 0}</span><span class="ability-label">игр</span></div>
    </div>`;
}

function renderNewPanels() {
  renderWars();
  renderRaids();
  renderLoans();
  renderStreaks();
  renderChests();
  renderCraft();
  renderShips();
  renderUserSearch();
  renderProfileAbilities();
  renderPrestige();
  renderOrders();
  renderTokens();
  renderCards();
  renderEnergy();
  renderArena();
  renderBingo();
  renderEncyclopedia();
  renderLive();
  renderEvents();
  renderRestaurant();
  renderMedals();
  renderGoals();
  renderDungeon();
  renderGifts();
  renderPvp();
  renderWorkers();
  renderFarm();
  renderBattlepass();
  renderAnalytics();
  renderCalendar();
  renderNews();
  renderPartners();
  renderEconomy();
  renderGuild();
  renderMap();
  renderTournament();
  renderCardMarket();
  renderStreet();
  renderClub();
  renderPet();
}

async function loadSocialExtras() {
  try {
    const [auto, tours, ach, notif, clan, friend, market, league] = await Promise.all([
      api("/api/auto/status").catch(() => null),
      api("/api/tournaments").catch(() => null),
      api("/api/achievements").catch(() => null),
      api("/api/notifications").catch(() => null),
      api("/api/clans").catch(() => null),
      api("/api/friends").catch(() => null),
      api("/api/market").catch(() => null),
      api("/api/leagues").catch(() => null),
    ]);
    if (auto) state.auto = auto;
    if (tours) state.tournaments = tours.tournaments;
    if (ach) state.achDetail = ach;
    if (notif) state.notifications = notif.notifications;
    if (clan) state.clans = clan;
    if (friend) state.friends = friend;
    if (market) state.market = market;
    if (league) state.leagues = league;
  } catch (e) {}
}

function renderClans() {
  const box = $("clanBox");
  if (!box) return;
  const data = state.clans || { clans: [], my: null };
  const top = data.clans || [];
  box.innerHTML = top.slice(0, 10).map((c) =>
    `<div class="clan-row">
      <div class="clan-info">
        <span class="clan-tag">[${c.tag}]</span>
        <span class="clan-name">${c.name}</span>
        <span class="clan-level">ур. ${c.level}</span>
      </div>
      <div class="clan-meta">${c.members} игроков · ${fmt(c.xp)} xp</div>
    </div>`).join("") || '<div class="empty">Кланов пока нет</div>';
  const my = data.my;
  if (my) {
    box.innerHTML =
      `<div class="clan-card">
        <div class="clan-head"><span class="clan-tag">[${my.tag}]</span><b>${my.name}</b> <span class="clan-level">ур. ${my.level}</span></div>
        <div class="clan-meta">${my.members.length} игроков · ${fmt(my.xp)} xp</div>
        <div class="clan-members">${my.members.slice(0, 12).map((m) =>
          `<span class="clan-member ${m.role}">${m.first_name || m.username || m.user_id}${m.role === "owner" ? " 👑" : ""}</span>`).join("")}</div>
        <div class="clan-actions">
          <button class="secondary small" data-clan-leave>Покинуть</button>
        </div>
      </div>`;
    const leave = box.querySelector("[data-clan-leave]");
    if (leave) leave.addEventListener("click", async () => {
      try {
        await api("/api/clans/leave");
        state.clans = await api("/api/clans");
        renderAll();
        toast("Вы покинули клан");
      } catch (e) { toast(e.message); }
    });
    return;
  }
  box.innerHTML +=
    `<div class="clan-create">
      <input id="clanName" class="input" placeholder="Название клана" maxlength="20">
      <input id="clanTag" class="input" placeholder="Тег (2–5)" maxlength="5" style="width:80px">
      <button class="cta small" id="clanCreate">Создать клан</button>
    </div>`;
  const create = box.querySelector("#clanCreate");
  if (create) create.addEventListener("click", async () => {
    try {
      const name = (box.querySelector("#clanName") || {}).value || "";
      const tag = (box.querySelector("#clanTag") || {}).value || "";
      await api("/api/clans/create", { name, tag });
      state.clans = await api("/api/clans");
      renderAll();
      toast("Клан создан!");
      confetti();
    } catch (e) { toast(e.message); }
  });
}

function renderFriends() {
  const box = $("friendBox");
  if (!box) return;
  const data = state.friends || { friends: [], requests: [] };
  const friends = data.friends || [];
  const requests = data.requests || [];
  box.innerHTML =
    `<div class="friend-head">
      <h4>Друзья (${friends.length})</h4>
    </div>` +
    (requests.length ? `<div class="friend-reqs">${requests.map((r) =>
      `<div class="friend-req-row">
        <span>${r.first_name || r.username} (@${r.username || "—"})</span>
        <button class="secondary small" data-fr-accept="${r.user_id}">Принять</button>
        <button class="secondary small" data-fr-decline="${r.user_id}">Отклонить</button>
      </div>`).join("")}</div>` : "") +
    `<div class="friend-list">` +
    (friends.length ? friends.map((f) =>
      `<div class="friend-row">
        <span class="friend-name">${f.first_name || f.username}</span>
        <span class="friend-sub">@${f.username || "—"} · ур. ${f.xp ? Math.floor(f.xp / 130) + 1 : 1}</span>
        <button class="secondary small" data-fr-remove="${f.user_id}">Удалить</button>
      </div>`).join("") : '<div class="empty">Друзей пока нет — добавьте в профиле игрока</div>') +
    `</div>`;
  box.querySelectorAll("[data-fr-accept]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/friends/accept", { user_id: btn.dataset.frAccept });
        state.friends = await api("/api/friends");
        renderAll();
        toast("Друг добавлен!");
      } catch (e) { toast(e.message); }
    });
  });
  box.querySelectorAll("[data-fr-decline]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/friends/decline", { user_id: btn.dataset.frDecline });
        state.friends = await api("/api/friends");
        renderAll();
      } catch (e) { toast(e.message); }
    });
  });
  box.querySelectorAll("[data-fr-remove]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/friends/remove", { user_id: btn.dataset.frRemove });
        state.friends = await api("/api/friends");
        renderAll();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderMarket() {
  const box = $("marketBox");
  if (!box) return;
  const data = state.market || { lots: [] };
  const lots = data.lots || [];
  box.innerHTML = lots.length ? lots.map((l) =>
    `<div class="lot-row">
      <div class="lot-info">
        <span class="lot-item">${l.item}</span>
        <span class="lot-qty">×${l.qty}</span>
      </div>
      <div class="lot-price">${fmt(l.price)} ◈</div>
      <button class="secondary small" data-lot-buy="${l.id}" ${l.seller_id === state.user.id ? "disabled" : ""}>
        ${l.seller_id === state.user.id ? "Ваш лот" : "Купить"}
      </button>
    </div>`).join("") : '<div class="empty">Лотов нет — выставьте предмет из инвентаря</div>';
  box.querySelectorAll("[data-lot-buy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/market/buy", { lot_id: btn.dataset.lotBuy });
        state.user.balance = data.balance;
        state.market = await api("/api/market");
        renderAll();
        toast("Покупка успешна!");
        sfx.cash();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderLeagues() {
  const box = $("leagueBox");
  if (!box) return;
  const data = state.leagues || {};
  const season = data.season || {};
  const me = data.me || {};
  const lg = me.league || {};
  const leagues = season.leagues || [];
  box.innerHTML =
    `<div class="season-head">
      <h4>${season.name || "Сезон"}</h4>
      <span class="season-status">${season.active ? "идет" : "завершен"}</span>
    </div>
    <div class="my-league">
      <span class="league-icon">${lg.icon || "🎖"}</span>
      <div><b>${lg.name || "—"}</b><br><small>Очки: ${me.points || 0}</small></div>
    </div>
    <div class="league-list">${leagues.map((l) =>
      `<div class="league-row ${l.id === lg.id ? "current" : ""}">
        <span>${l.icon} ${l.name}</span>
        <span>${fmt(l.reward)}</span>
      </div>`).join("")}</div>
    <button class="secondary small" id="leagueClaim" ${me.points < 100 ? "disabled" : ""}>Забрать награду</button>`;
  const claim = box.querySelector("#leagueClaim");
  if (claim) claim.addEventListener("click", async () => {
    try {
      const data = await api("/api/leagues/claim");
      state.user.balance = data.balance;
      renderAll();
      toast(`Награда +${fmt(data.reward)}!`);
      confetti();
    } catch (e) { toast(e.message); }
  });
}

function renderAchievementsDetail() {
  const box = $("achDetailBox");
  if (!box) return;
  const data = state.achDetail || {};
  const items = data.achievements || [];
  const summary = data.summary || {};
  box.innerHTML =
    `<div class="ach-summary">
      <span>Получено: <b>${summary.claimed}</b>/${summary.total}</span>
      <span>Опыт: <b>${fmt(summary.xp || 0)}</b></span>
    </div>
    <div class="ach-progress-track">
      <div class="ach-progress-fill" style="width:${summary.total ? Math.round(summary.claimed / summary.total * 100) : 0}%"></div>
    </div>` +
    items.slice(0, 24).map((a) =>
      `<div class="ach-row ${a.claimed ? "done" : ""} ${a.done && !a.claimed ? "ready" : ""}">
        <span class="ach-icon">${a.icon}</span>
        <div class="ach-main">
          <div class="ach-title">${a.title}</div>
          <div class="ach-desc">${a.desc}</div>
          <div class="ach-bar"><div class="ach-bar-fill" style="width:${a.target ? Math.round(a.progress / a.target * 100) : 0}%"></div></div>
          <div class="ach-progress">${a.progress}/${a.target}</div>
        </div>
        <div class="ach-side">
          <span class="ach-reward">+${fmt(a.reward)}</span>
          ${a.done && !a.claimed ? `<button class="secondary small" data-ach-claim="${a.key}">Забрать</button>` : a.claimed ? "✓" : ""}
        </div>
      </div>`).join("") || '<div class="empty">Достижений нет</div>';
  box.querySelectorAll("[data-ach-claim]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/achievements/claim", { key: btn.dataset.achClaim });
        state.achDetail = await api("/api/achievements");
        renderAll();
        toast("Достижение получено!");
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderAutoPanel() {
  const p = $("autoPanel");
  if (!p) return;
  const active = (state.auto && state.auto.active) || [];
  if (active.length) {
    const row = active[0];
    p.innerHTML =
      `<div class="auto-card active">
        <div class="auto-title">⚡ Автоигра: ${row.game}</div>
        <div class="auto-meta">${row.strategy} · ставка ${fmt(row.bet)} · раунд ${row.rounds_done}/${row.rounds_max}</div>
        <div class="auto-actions">
          <button class="secondary small" data-auto-stop="${row.id}">⏹ Остановить</button>
        </div>
      </div>`;
    const btn = p.querySelector("[data-auto-stop]");
    if (btn) btn.addEventListener("click", async () => {
      try {
        await api("/api/auto/stop", { auto_id: btn.dataset.autoStop });
        state.auto = await api("/api/auto/status");
        renderAll();
        toast("Автоигра остановлена");
      } catch (e) { toast(e.message); }
    });
    return;
  }
  p.innerHTML =
    `<div class="auto-card">
      <div class="auto-row">
        <select id="autoGame" class="input">
          <option value="mines">Сапёр</option>
          <option value="crash">Краш</option>
          <option value="dice">Кости</option>
        </select>
        <select id="autoStrategy" class="input">
          <option value="fixed">Фикс. ставка</option>
          <option value="martingale">Мартингейл</option>
          <option value="paroli">Пароли</option>
        </select>
      </div>
      <div class="auto-row">
        <input id="autoBet" class="input" type="number" min="10" value="100" placeholder="Ставка">
        <input id="autoRounds" class="input" type="number" min="1" max="1000" value="10" placeholder="Раундов">
      </div>
      <button class="cta small" id="autoStart">⚡ Запустить автоигру</button>
    </div>`;
  const start = p.querySelector("#autoStart");
  if (start) start.addEventListener("click", async () => {
    try {
      const data = await api("/api/auto/start", {
        game: (p.querySelector("#autoGame") || {}).value || "mines",
        strategy: (p.querySelector("#autoStrategy") || {}).value || "fixed",
        bet: Number((p.querySelector("#autoBet") || {}).value) || 100,
        rounds_max: Number((p.querySelector("#autoRounds") || {}).value) || 10,
      });
      state.auto = await api("/api/auto/status");
      renderAll();
      toast("Автоигра запущена");
    } catch (e) { toast(e.message); }
  });
}

function renderTournaments() {
  const box = $("tournamentBox");
  if (!box) return;
  const tours = state.tournaments || [];
  box.innerHTML = tours.length
    ? tours.map((t) =>
      `<div class="tour-card">
        <div class="tour-head"><span>🏆 ${t.name}</span><span class="tour-kind">${t.kind}</span></div>
        <div class="tour-meta">Приз: <b>${fmt(t.prize)}</b> · Вход: ${t.entry_fee ? fmt(t.entry_fee) : "бесплатно"}</div>
        <div class="tour-meta">Игроков: ${t.players} · Осталось: ${Math.floor(t.seconds_left / 60)} мин</div>
        <button class="secondary small" data-tour-join="${t.id}" ${t.joined ? "disabled" : ""}>
          ${t.joined ? "✓ Вы участвуете" : "Участвовать"}
        </button>
      </div>`).join("")
    : `<div class="empty">Турниров пока нет — загляните позже</div>`;
  box.querySelectorAll("[data-tour-join]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/tournaments/join", { tour_id: btn.dataset.tourJoin });
        state.user.balance = data.balance != null ? data.balance : state.user.balance;
        state.tournaments = (await api("/api/tournaments")).tournaments;
        renderAll();
        toast("Вы в турнире!");
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderNotifications() {
  const box = $("notificationBox");
  if (!box) return;
  const items = state.notifications || [];
  box.innerHTML = items.length
    ? items.map((n) =>
      `<div class="notif ${n.is_read ? "" : "unread"}">
        <div class="notif-title">${n.title}</div>
        ${n.text ? `<div class="notif-text">${n.text}</div>` : ""}
        <div class="notif-date">${new Date(n.created_at * 1000).toLocaleString("ru-RU")}</div>
      </div>`).join("")
    : `<div class="empty">Уведомлений нет</div>`;
}

function bind() {
  document.querySelectorAll(".nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );

  document.querySelectorAll("[data-shop-tab]").forEach((tab) =>
    tab.addEventListener("click", () => switchView(tab.dataset.shopTab))
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
                   Math.min(state.settings.max_bet || 100000000, v));
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

  /* --- админ: выдача любых наград --- */
  async function loadGrantCatalog() {
    if (grantCatalog) return grantCatalog;
    const data = await api("/api/admin/catalog", {});
    grantCatalog = data.catalog || {};
    return grantCatalog;
  }

  function fillGrantKeys() {
    const kindSel = $("grantKind");
    const keySel = $("grantKey");
    if (!kindSel || !keySel) return;
    const kind = kindSel.value;
    if (kind === "money" || kind === "gmpoint") {
      keySel.innerHTML = '<option value="">— сумма из поля ниже —</option>';
      keySel.disabled = true;
      if ($("grantHint")) $("grantHint").textContent = "Сумму задай в поле «Количество / сумма»";
      return;
    }
    keySel.disabled = false;
    const items = (grantCatalog && grantCatalog[kind]) || [];
    keySel.innerHTML = items.length
      ? items.map((it) => `<option value="${it.key}">${it.title} · ${it.key}</option>`).join("")
      : '<option value="">нет доступных ключей</option>';
  }

  async function grantSend() {
    const hint = $("grantHint");
    const userId = parseInt($("grantUser").value || "0", 10);
    if (!userId) { hint.textContent = "Укажи ID игрока"; return; }
    const kind = $("grantKind").value;
    const qty = parseInt($("grantQty").value || "1", 10) || 1;
    const body = { user_id: userId, kind };
    if (kind === "money" || kind === "gmpoint") {
      body.amount = qty;
    } else {
      body.item = $("grantKey").value;
      body.qty = qty;
    }
    try {
      const data = await api("/api/admin/grant", body);
      hint.textContent = "Готово: " + (data.title || data.item || data.kind)
        + (data.balance !== undefined ? " · баланс " + fmt(data.balance) : "")
        + (data.gmpoint !== undefined ? " · GMPOINT " + fmt(data.gmpoint) : "");
    } catch (e) {
      hint.textContent = e.message;
    }
  }

  if ($("grantKind")) $("grantKind").addEventListener("change", fillGrantKeys);
  if ($("grantSend")) $("grantSend").addEventListener("click", grantSend);

  async function loadCustomPrefixes() {
    try {
      const data = await api("/api/admin/custom-prefix", { action: "list" });
      const box = $("cpList");
      if (!box) return;
      const items = data.items || [];
      box.innerHTML = items.length ? items.map((p) => `
        <div class="admin-row">
          <span style="color:${p.color}">${escapeHtml(p.title)}</span>
          <span class="muted">${p.key} · +${Math.round((p.bonus || 0) * 100)}%</span>
          <button class="chip-btn" data-cp-del="${p.key}">Удалить</button>
        </div>`).join("")
        : '<div class="muted">Пока нет кастомных префиксов</div>';
    } catch (e) {
      toast(e.message);
    }
  }

  async function createCustomPrefix() {
    const hint = $("cpHint");
    if (!hint) return;
    const title = ($("cpTitle").value || "").trim();
    if (!title) { hint.textContent = "Укажи название префикса"; return; }
    try {
      const data = await api("/api/admin/custom-prefix", {
        action: "create",
        title,
        color: ($("cpColor").value || "#ffd166").trim(),
        color2: ($("cpColor2").value || "").trim(),
        style: ($("cpStyle").value || "solid").trim(),
        bonus: parseFloat($("cpBonus").value || "0") || 0,
      });
      hint.textContent = `Создан: ${data.title} (ключ ${data.key}). Выдай его в «Выдать → Префикс».`;
      loadCustomPrefixes();
    } catch (e) {
      hint.textContent = e.message;
    }
  }

  if ($("cpCreate")) $("cpCreate").addEventListener("click", createCustomPrefix);
  if ($("cpList")) $("cpList").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-cp-del]");
    if (!btn) return;
    try {
      await api("/api/admin/custom-prefix", { action: "delete", key: btn.dataset.cpDel });
      toast("Префикс удалён");
      loadCustomPrefixes();
    } catch (err) {
      toast(err.message);
    }
  });

  if ($("adminTabs")) $("adminTabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-atab]");
    if (btn && btn.dataset.atab === "grant") {
      loadGrantCatalog().then(fillGrantKeys).catch((err) => toast(err.message));
    }
    if (btn && btn.dataset.atab === "prefix") loadCustomPrefixes();
  });

  bindAdminEconomy();

  if ($("hourlyCard")) $("hourlyCard").addEventListener("click", claimHourly);
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
    if (state.user && !document.hidden) {
      if (state._bonusLastRender && Date.now() - state._bonusLastRender < 1000) return;
      state._bonusLastRender = Date.now();
      renderBonus();
    }
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
      const pane = btn.closest(".game-pane");
      const input = (pane && pane.querySelector('input[type="number"]')) || $("basketBet");
      let v = parseInt(input.value, 10) || 0;
      const mode = btn.dataset.kbet;
      if (mode === "half") v = Math.floor(v / 2);
      if (mode === "double") v = v * 2;
      if (mode === "max") v = state.user ? state.user.balance : 1000;
      input.value = clampBet(v);
      haptic();
    }));

  if ($("basketShoot")) $("basketShoot").addEventListener("click", playBasket);
  if ($("dartsThrow")) $("dartsThrow").addEventListener("click", playDarts);
  document.querySelectorAll("#dartsPicks .darts-pick").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("#dartsPicks .darts-pick")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      haptic();
    }));
  if ($("fishCast")) $("fishCast").addEventListener("click", castFish);
  if ($("fishSellAll")) $("fishSellAll").addEventListener("click", sellAllFish);
  const rodGrid = $("rodGrid");
  if (rodGrid) {
    rodGrid.addEventListener("click", (e) => {
      const btn = e.target.closest(".rod-btn");
      if (!btn || btn.disabled || !btn.dataset.act) return;
      rodAction(btn.dataset.rod, btn.dataset.act);
    });
  }

  $("view-shop").addEventListener("click", (e) => {
    const btn = e.target.closest(".shop-buy");
    if (!btn || btn.disabled) return;
    if (btn.dataset.act === "equip") equipPrefix(btn.dataset.key);
    else buyItem(btn.dataset.key);
  });

  const inventoryBox = $("inventorySections");
  if (inventoryBox) {
    inventoryBox.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-inv]");
      if (!btn) return;
      haptic();
      inventoryAction(btn.dataset.inv, btn.dataset.key, btn.dataset.qty || 1);
    });
  }

  const shopTabs = $("shopTabs");
  if (shopTabs) {
    shopTabs.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-shop-cat]");
      if (!btn || btn.dataset.shopCat === shopCat) return;
      shopCat = btn.dataset.shopCat;
      haptic();
      renderShop();
      if ($("shopItems")) $("shopItems").scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  const profileNav = $("profileNav");
  if (profileNav) {
    profileNav.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-scroll]");
      if (!btn) return;
      const target = document.getElementById(btn.dataset.scroll);
      haptic();
      if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  const prefixList = $("profilePrefixList");
  if (prefixList) {
    prefixList.addEventListener("click", (e) => {
      const btn = e.target.closest(".prefix-pick");
      if (!btn) return;
      equipPrefix(btn.dataset.act === "off" ? "" : btn.dataset.key);
    });
  }

  const cosBlock = document.querySelector(".cosmetics-card");
  if (cosBlock) {
    cosBlock.addEventListener("click", (e) => {
      const btn = e.target.closest(".cos-item");
      if (!btn) return;
      if (btn.dataset.kind === "avatar" && btn.dataset.act === "upload") {
        if ($("avatarUploadInput")) $("avatarUploadInput").click();
        return;
      }
      cosmeticAction(btn.dataset.kind, btn.dataset.key, btn.dataset.act);
    });
  }

  const avatarUploadInput = $("avatarUploadInput");
  if (avatarUploadInput) {
    avatarUploadInput.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      uploadAvatar(file).finally(() => { e.target.value = ""; });
    });
  }

  const bgCard = document.querySelector(".game-bg-card");
  if (bgCard) {
    bgCard.addEventListener("click", (e) => {
      const btn = e.target.closest(".bg-item");
      if (!btn) return;
      if (btn.dataset.act === "upload") {
        if ($("bgUploadInput")) $("bgUploadInput").click();
        return;
      }
      cosmeticAction("gamebg", btn.dataset.key, btn.dataset.act);
    });
  }
  if ($("bgUploadBtn") && $("bgUploadInput")) {
    $("bgUploadBtn").addEventListener("click", () => $("bgUploadInput").click());
    $("bgUploadInput").addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      uploadBackground(file).finally(() => { e.target.value = ""; });
    });
  }

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

  $("tasksQuests").addEventListener("click", async (e) => {
    const btn = e.target.closest(".quest-claim");
    if (!btn || btn.disabled) return;
    try {
      const data = await api("/api/quests/claim", { key: btn.dataset.quest });
      state.quests = data.quests || state.quests;
      if (data.hour_items) state.hourQuests = data.hour_items;
      if (data.achievements) state.achievements = data.achievements;
      state.user.balance = data.balance;
      sfx.cash();
    toast(data.gmpoint != null && data.gmpoint !== state.user.gmpoint
      ? `Награда +${fmt(data.reward)} GMPOINT${awardsNote(data.awards)}`
      : `Награда +${fmt(data.reward)} mCoin${awardsNote(data.awards)}`);
      if (data.gmpoint != null) state.user.gmpoint = data.gmpoint;
      renderAll();
    } catch (err) {
      toast(err.message);
    }
  });
}

function renderPrestige() {
  const box = $("prestigeBox");
  if (!box) return;
  const data = state.prestige || { prestige: 0, bonus: 0, can: false, cost: 0 };
  box.innerHTML =
    `<div class="prestige-card">
      <div class="prestige-head">
        <span>⭐ Престиж: <b>${data.prestige}</b></span>
        <span class="prestige-bonus">+${Math.round((data.bonus || 0) * 100)}% к выплатам</span>
      </div>
      <div class="prestige-meta">${data.level != null ? `Уровень: ${data.level} · нужно 50` : ""}</div>
      <button class="cta small" id="prestigeDo" ${data.can ? "" : "disabled"}>
        ${data.can ? `Переродиться за ${fmt(data.cost)}` : data.prestige >= 10 ? "Максимум" : "Нужен 50-й уровень"}
      </button>
    </div>`;
  const btn = box.querySelector("#prestigeDo");
  if (btn) btn.addEventListener("click", async () => {
    if (!confirm("Переродиться? Сброс уровня и баланс уменьшится.")) return;
    try {
      const data = await api("/api/prestige/do");
      state.user.balance = data.balance;
      state.user.prestige = data.prestige;
      state.prestige = await api("/api/prestige");
      renderAll();
      toast("Престиж повышен! Награды растут.");
      confetti();
    } catch (e) { toast(e.message); }
  });
}

function renderOrders() {
  const box = $("orderBox");
  if (!box) return;
  const orders = state.orders || [];
  box.innerHTML = orders.length ? orders.map((o) =>
    `<div class="order-row ${o.done ? "done" : ""}">
      <div class="order-info">
        <span class="order-kind">${o.kind === "fishing" ? "🎣 Рыбалка" : o.kind === "games" ? "🎮 Игры" : "📦 " + o.kind}</span>
        <div class="order-bar"><div class="order-fill" style="width:${Math.min(100, Math.round(o.progress / o.target * 100))}%"></div></div>
        <span class="order-progress">${o.progress}/${o.target}</span>
      </div>
      <div class="order-side">
        <span class="order-reward">${fmt(o.reward)}</span>
        ${o.done ? `<button class="secondary small" data-order-claim="${o.id}">Забрать</button>` : ""}
      </div>
    </div>`).join("") : '<div class="empty">Заказов пока нет — новые появятся по мере игры</div>';
  box.querySelectorAll("[data-order-claim]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/orders/claim", { order_id: btn.dataset.orderClaim });
        state.user.balance = data.balance;
        state.orders = (await api("/api/orders")).orders;
        renderAll();
        toast(`Награда +${fmt(data.reward)}!`);
        sfx.cash();
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadExtraProgression() {
  try {
    const [pr, or] = await Promise.all([
      api("/api/prestige").catch(() => null),
      api("/api/orders").catch(() => null),
    ]);
    if (pr) state.prestige = pr;
    if (or) state.orders = or.orders;
  } catch (e) {}
}

function renderTokens() {
  const box = $("tokenBox");
  if (!box) return;
  const data = state.tokens || { tokens: 0, exchange: [] };
  box.innerHTML =
    `<div class="token-head">🪙 Жетоны: <b>${fmt(data.tokens)}</b></div>
    <div class="token-list">${(data.exchange || []).map((e) =>
      `<div class="token-row">
        <span>${e.title}</span>
        <button class="secondary small" data-token-ex="${e.kind}">${e.cost} 🪙</button>
      </div>`).join("")}</div>`;
  box.querySelectorAll("[data-token-ex]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/tokens/exchange", { kind: btn.dataset.tokenEx });
        state.tokens = await api("/api/tokens");
        state.user.balance = data.balance;
        renderAll();
        toast(`Обмен: ${data.result || "готово"}`);
      } catch (e) { toast(e.message); }
    });
  });
}

function renderCards() {
  const box = $("cardBox");
  if (!box) return;
  const data = state.cards || { cards: [], progress: { sets: [] } };
  const cards = data.cards || [];
  const sets = data.progress.sets || [];
  const rarityColor = { common: "#a8b3c5", rare: "#5aa9ff", epic: "#ff8f6b" };
  box.innerHTML =
    `<div class="card-sets">${sets.map((s) =>
      `<span class="card-set">${s.set_key}: ${s.owned}/${s.total}</span>`).join("")}</div>
    <button class="cta small" id="cardUnpack">Открыть 1 пачку (150 ◈)</button>
    <div class="card-grid">${cards.map((c) =>
      `<div class="card-item ${c.owned ? "" : "locked"}" title="${c.title}">
        <span class="card-icon" style="color:${rarityColor[c.rarity] || "#aaa"}">♦</span>
        <span class="card-name">${c.title}</span>
        <span class="card-count">${c.owned ? "×" + c.owned : "—"}</span>
      </div>`).join("")}</div>`;
  const unpack = box.querySelector("#cardUnpack");
  if (unpack) unpack.addEventListener("click", async () => {
    try {
      const data = await api("/api/cards/unpack", { qty: 1 });
      state.user.balance = data.balance;
      state.cards = await api("/api/cards");
      renderAll();
      toast(`Получено: ${data.cards.join(", ")}`);
      confetti();
    } catch (e) { toast(e.message); }
  });
}

async function loadCollections() {
  try {
    const [t, c] = await Promise.all([
      api("/api/tokens").catch(() => null),
      api("/api/cards").catch(() => null),
    ]);
    if (t) state.tokens = t;
    if (c) state.cards = c;
  } catch (e) {}
}

function renderEnergy() {
  const box = $("energyBox");
  if (!box) return;
  const data = state.energy || { energy: 100, max: 100, regen_in: 0 };
  const pct = data.max ? Math.round(data.energy / data.max * 100) : 0;
  box.innerHTML =
    `<div class="energy-head">⚡ Энергия: <b>${data.energy}</b>/${data.max}</div>
    <div class="energy-bar"><div class="energy-fill" style="width:${pct}%"></div></div>
    <div class="energy-meta">${data.regen_in ? `+1 через ${Math.ceil(data.regen_in / 60)} мин` : "Полная"}</div>
    <button class="secondary small" id="energyBuy">Купить 10 (500 ◈)</button>`;
  const btn = box.querySelector("#energyBuy");
  if (btn) btn.addEventListener("click", async () => {
    try {
      const data = await api("/api/energy/buy", { amount: 10 });
      state.user.balance = data.balance;
      state.energy = data.energy;
      renderAll();
    } catch (e) { toast(e.message); }
  });
}

async function loadEnergy() {
  try {
    state.energy = (await api("/api/energy")).energy;
  } catch (e) {}
}

function renderArena() {
  const box = $("arenaBox");
  if (!box) return;
  const data = state.arena || { rating: 1200, stats: { played: 0, won: 0 }, matches: [] };
  const m = data.matches || [];
  box.innerHTML =
    `<div class="arena-head">
      <span>⚔️ Рейтинг: <b>${data.rating}</b></span>
      <span>Побед: ${data.stats.won}/${data.stats.played}</span>
    </div>
    <div class="arena-fight">
      <input id="arenaBet" class="input" type="number" value="1000" min="100" max="100000">
      <button class="cta small" id="arenaFight">Бой</button>
    </div>
    <div class="arena-list">${m.length ? m.slice(0, 8).map((x) =>
      `<div class="arena-row ${x.result === "win" ? "win" : "lose"}">
        <span>${x.result === "win" ? "🏆 Победа" : "💀 Поражение"} vs ${x.opponent}</span>
        <span>${x.result === "win" ? "+" + fmt(x.payout) : "−" + fmt(x.bet)}</span>
      </div>`).join("") : '<div class="empty">Боев пока нет</div>'}</div>`;
  const fight = box.querySelector("#arenaFight");
  if (fight) fight.addEventListener("click", async () => {
    try {
      const data = await api("/api/arena/fight", {
        bet: Number((box.querySelector("#arenaBet") || {}).value) || 1000,
      });
      state.user.balance = data.balance;
      state.arena = await api("/api/arena");
      renderAll();
      toast(data.won ? `Победа! +${fmt(data.payout)}` : "Поражение…");
      if (data.won) confetti();
    } catch (e) { toast(e.message); }
  });
}

function renderBingo() {
  const box = $("bingoBox");
  if (!box) return;
  const game = state.bingo;
  if (!game) {
    box.innerHTML =
      `<div class="bingo-start">
        <p>Собери 2 линии на поле 3×3 и выиграй ×6!</p>
        <input id="bingoBet" class="input" type="number" value="100" min="50" max="20000">
        <button class="cta small" id="bingoStart">Начать (3×3)</button>
      </div>`;
    const start = box.querySelector("#bingoStart");
    if (start) start.addEventListener("click", async () => {
      try {
        const data = await api("/api/bingo/new", {
          bet: Number((box.querySelector("#bingoBet") || {}).value) || 100,
        });
        state.bingo = { ...data, board: data.board, marks: data.board.map(() => 0), numbers: [] };
        renderAll();
      } catch (e) { toast(e.message); }
    });
    return;
  }
  const board = game.board || [];
  const marks = game.marks || board.map(() => 0);
  const nums = game.numbers || [];
  box.innerHTML =
    `<div class="bingo-board">${board.map((n, i) =>
      `<button class="bingo-cell ${marks[i] ? "marked" : ""}" data-bingo-cell="${i}" data-num="${n}">
        ${marks[i] ? "✓" : n}
      </button>`).join("")}</div>
    <div class="bingo-nums">Сыграно: ${nums.join(", ") || "—"}</div>
    <button class="secondary small" id="bingoStop">Сдаться</button>`;
  box.querySelectorAll("[data-bingo-cell]").forEach((cell) => {
    if (marks[Number(cell.dataset.bingoCell)]) return;
    cell.addEventListener("click", async () => {
      try {
        const data = await api("/api/bingo/mark", {
          game_id: game.game_id, number: Number(cell.dataset.num),
        });
        state.user.balance = data.balance;
        state.bingo.marks = data.marks;
        state.bingo.numbers = data.numbers;
        if (data.status !== "active") {
          state.bingo = null;
          toast(data.status === "won" ? `Бинго! +${fmt(data.payout)}` : "Игра окончена");
          if (data.status === "won") confetti();
        }
        renderAll();
      } catch (e) { toast(e.message); }
    });
  });
  const stop = box.querySelector("#bingoStop");
  if (stop) stop.addEventListener("click", () => {
    state.bingo = null;
    renderAll();
  });
}

async function loadArenaBingo() {
  try {
    const [a, b] = await Promise.all([
      api("/api/arena").catch(() => null),
      api("/api/energy").catch(() => null),
    ]);
    if (a) state.arena = a;
    if (b) state.energy = b.energy;
  } catch (e) {}
}

function renderEncyclopedia() {
  const box = $("encyclopediaBox");
  if (!box) return;
  const data = state.encyclopedia || { fish: [], games: [], items: [] };
  const fish = data.fish || [];
  const games = data.games || [];
  const items = data.items || [];
  box.innerHTML =
    `<div class="ency-tabs">
      <button class="secondary small active" data-ency-tab="fish">Рыбы</button>
      <button class="secondary small" data-ency-tab="games">Игры</button>
      <button class="secondary small" data-ency-tab="items">Предметы</button>
    </div>
    <div class="ency-pane" id="encyFish">${fish.map((f) =>
      `<div class="ency-row">
        <span class="ency-title">🐟 ${f.title} <small class="ency-rarity">${f.rarity}</small></span>
        <span class="ency-sub">${f.weight} · ${f.hint || ""}</span>
      </div>`).join("") || '<div class="empty">Нет данных</div>'}</div>
    <div class="ency-pane" id="encyGames" hidden>${games.map((g) =>
      `<div class="ency-row">
        <span class="ency-title">🎮 ${g.title}</span>
        <span class="ency-sub">${g.desc}</span>
      </div>`).join("") || '<div class="empty">Нет данных</div>'}</div>
    <div class="ency-pane" id="encyItems" hidden>${items.map((i) =>
      `<div class="ency-row">
        <span class="ency-title">📦 ${i.title}</span>
        <span class="ency-sub">${i.desc}</span>
      </div>`).join("") || '<div class="empty">Нет данных</div>'}</div>`;
  box.querySelectorAll("[data-ency-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      box.querySelectorAll("[data-ency-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      box.querySelectorAll(".ency-pane").forEach((p) => { p.hidden = true; });
      const map = { fish: "encyFish", games: "encyGames", items: "encyItems" };
      const pane = box.querySelector("#" + map[btn.dataset.encyTab]);
      if (pane) pane.hidden = false;
    });
  });
}

async function loadEncyclopedia() {
  try {
    state.encyclopedia = await api("/api/encyclopedia");
  } catch (e) {}
}

function renderLive() {
  const box = $("liveBox");
  if (!box) return;
  const sessions = state.live || [];
  box.innerHTML =
    `<div class="live-create">
      <select id="liveGame" class="input">
        <option value="mines">Сапёр</option>
        <option value="dice">Кости</option>
      </select>
      <input id="liveBet" class="input" type="number" value="1000" min="100" max="100000">
      <button class="secondary small" id="liveCreate">Создать</button>
    </div>
    <div class="live-list">${sessions.length ? sessions.map((s) =>
      `<div class="live-row">
        <span>🎯 ${s.game} · ставок: ${s.bets_count} · пул ${fmt(s.total_bets)}</span>
        <button class="secondary small" data-live-bet="${s.id}">Поставить ×2</button>
      </div>`).join("") : '<div class="empty">Нет активных сессий</div>'}</div>`;
  const create = box.querySelector("#liveCreate");
  if (create) create.addEventListener("click", async () => {
    try {
      const data = await api("/api/live/create", {
        game: (box.querySelector("#liveGame") || {}).value || "mines",
        bet: Number((box.querySelector("#liveBet") || {}).value) || 1000,
      });
      state.user.balance = data.balance != null ? data.balance : state.user.balance;
      state.live = (await api("/api/live")).sessions;
      renderAll();
      toast("Сессия создана!");
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-live-bet]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const amount = prompt("Сумма ставки:");
      if (!amount) return;
      try {
        const data = await api("/api/live/bet", {
          session_id: btn.dataset.liveBet, amount: Number(amount),
        });
        state.user.balance = data.balance;
        state.live = (await api("/api/live")).sessions;
        renderAll();
        toast(`Ставка ×${data.odds} принята`);
      } catch (e) { toast(e.message); }
    });
  });
}

function renderEvents() {
  const box = $("eventBox");
  if (!box) return;
  const events = state.events || [];
  box.innerHTML = events.length ? events.map((e) =>
    `<div class="event-card">
      <div class="event-head">✨ ${e.title}</div>
      <div class="event-desc">${e.desc}</div>
      <div class="event-meta">Приз: ${fmt(e.prize)} ◈ · осталось ${Math.floor(e.seconds_left / 3600)} ч</div>
      <button class="secondary small" data-event-claim="${e.id}">Забрать</button>
    </div>`).join("") : '<div class="empty">Активных событий нет</div>';
  box.querySelectorAll("[data-event-claim]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/events/claim", { event_id: btn.dataset.eventClaim });
        state.user.balance = data.balance;
        state.events = (await api("/api/events")).events;
        renderAll();
        toast(`Приз +${fmt(data.prize)}!`);
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadLiveEvents() {
  try {
    const [l, e] = await Promise.all([
      api("/api/live").catch(() => null),
      api("/api/events").catch(() => null),
    ]);
    if (l) state.live = l.sessions;
    if (e) state.events = e.events;
  } catch (e) {}
}

function renderRestaurant() {
  const box = $("restaurantBox");
  if (!box) return;
  const data = state.restaurant || { dishes: [], orders: [] };
  const dishes = data.dishes || [];
  const orders = data.orders || [];
  box.innerHTML =
    `<div class="restaurant-dishes">${dishes.map((d) =>
      `<div class="restaurant-dish">
        <div class="restaurant-info">
          <span class="restaurant-title">🍽 ${d.title}</span>
          <span class="restaurant-sub">нужно рыбы: ${d.needed} · награда ${fmt(d.reward)}</span>
        </div>
        <button class="secondary small" data-cook="${d.key}" ${d.available >= d.needed ? "" : "disabled"}>
          Готовить
        </button>
      </div>`).join("")}</div>
    <div class="restaurant-orders">${orders.length ? orders.map((o) =>
      `<div class="restaurant-order">
        <span>${o.dish} ${o.status === "done" ? "готово" : "ещё " + Math.floor(o.seconds_left / 60) + " мин"}</span>
        ${o.status === "done" ? `<button class="secondary small" data-take="${o.id}">Забрать ${fmt(o.reward)}</button>` : ""}
      </div>`).join("") : '<div class="empty">Заказов нет</div>'}</div>`;
  box.querySelectorAll("[data-cook]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/restaurant/cook", { dish: btn.dataset.cook });
        state.restaurant = await api("/api/restaurant");
        renderAll();
        toast("Готовим!");
      } catch (e) { toast(e.message); }
    });
  });
  box.querySelectorAll("[data-take]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/restaurant/take", { order_id: btn.dataset.take });
        state.user.balance = data.balance;
        state.restaurant = await api("/api/restaurant");
        renderAll();
        toast(`+${fmt(data.reward)}!`);
        sfx.cash();
      } catch (e) { toast(e.message); }
    });
  });
}

function renderMedals() {
  const box = $("medalBox");
  if (!box) return;
  const medals = state.medals || [];
  box.innerHTML = medals.length ? medals.map((m) =>
    `<div class="medal-row ${m.owned ? "owned" : ""}">
      <span class="medal-icon">${m.icon}</span>
      <div class="medal-info">
        <span class="medal-title">${m.title} ${m.owned ? "⭐" : ""}</span>
        <span class="medal-desc">${m.desc}</span>
      </div>
    </div>`).join("") : '<div class="empty">Нет медалей</div>';
}

function renderGoals() {
  const box = $("goalBox");
  if (!box) return;
  const goals = state.goals || [];
  box.innerHTML = goals.length ? goals.map((g) =>
    `<div class="goal-row ${g.claimed ? "claimed" : ""} ${g.done ? "done" : ""}">
      <div class="goal-info">
        <span class="goal-kind">${g.kind === "games" ? "🎮 Сыграть игр" : g.kind === "wins" ? "🏆 Побед" : "🐟 Поймать рыбы"}</span>
        <div class="goal-bar"><div class="goal-fill" style="width:${Math.min(100, Math.round(g.progress / g.target * 100))}%"></div></div>
        <span class="goal-progress">${g.progress}/${g.target}</span>
      </div>
      <div class="goal-side">
        <span class="goal-reward">${fmt(g.reward)}</span>
        ${g.done && !g.claimed ? `<button class="secondary small" data-goal-claim="${g.kind}">Забрать</button>` : g.claimed ? "✓" : ""}
      </div>
    </div>`).join("") : '<div class="empty">Целей нет</div>';
  box.querySelectorAll("[data-goal-claim]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/goals/claim", { kind: btn.dataset.goalClaim });
        state.user.balance = data.balance;
        state.goals = (await api("/api/goals")).goals;
        renderAll();
        toast(`+${fmt(data.reward)}!`);
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadRestaurantMedals() {
  try {
    const [r, m, g] = await Promise.all([
      api("/api/restaurant").catch(() => null),
      api("/api/medals").catch(() => null),
      api("/api/goals").catch(() => null),
    ]);
    if (r) state.restaurant = r;
    if (m) state.medals = m.medals;
    if (g) state.goals = g.goals;
  } catch (e) {}
}

function renderDungeon() {
  const box = $("dungeonBox");
  if (!box) return;
  const data = state.dungeon || { run: null, best: { kills: 0 } };
  if (!data.run) {
    box.innerHTML =
      `<div class="dungeon-start">
        <p>Отправляйся в экспедицию, сражайся с монстрами и собирай золото!</p>
        <p class="dungeon-best">Рекорд: ${data.best.kills} убийств</p>
        <button class="cta small" data-dungeon-start="cave">🕳 Пещера</button>
        <button class="secondary small" data-dungeon-start="forest">🌲 Лес</button>
        <button class="secondary small" data-dungeon-start="tower">🗼 Башня</button>
      </div>`;
    box.querySelectorAll("[data-dungeon-start]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api("/api/dungeon/start", { dungeon: btn.dataset.dungeonStart });
          state.dungeon = await api("/api/dungeon");
          renderAll();
        } catch (e) { toast(e.message); }
      });
    });
    return;
  }
  const run = data.run;
  const pct = Math.round(run.hp / run.max_hp * 100);
  box.innerHTML =
    `<div class="dungeon-head">🗡 ${run.dungeon} · уровень ${run.level}</div>
    <div class="dungeon-hp"><div class="dungeon-hp-fill" style="width:${pct}%"></div></div>
    <div class="dungeon-meta">HP: ${run.hp}/${run.max_hp} · Золото: ${fmt(run.gold)} · Убийств: ${run.kills}</div>
    <button class="cta small" id="dungeonFight">⚔ Сразиться</button>
    <button class="secondary small" id="dungeonLeave">Выйти (+${fmt(run.gold)})</button>`;
  const fight = box.querySelector("#dungeonFight");
  if (fight) fight.addEventListener("click", async () => {
    try {
      const data = await api("/api/dungeon/fight", { run_id: run.id });
      if (data.dead) {
        state.user.balance = data.balance;
        state.dungeon = await api("/api/dungeon");
        toast(`Вы погибли. Спасено: ${fmt(data.gold_saved)}`);
      } else if (data.killed) {
        toast(`Монстр повержен! +${fmt(data.gold)} золота`);
        if (data.run) state.dungeon = { ...state.dungeon, run: data.run };
      } else {
        toast(`Урон получен: ${data.damage_taken}`);
        state.dungeon = { ...state.dungeon, run: data.run };
      }
      renderAll();
    } catch (e) { toast(e.message); }
  });
  const leave = box.querySelector("#dungeonLeave");
  if (leave) leave.addEventListener("click", async () => {
    try {
      const data = await api("/api/dungeon/leave", { run_id: run.id });
      state.user.balance = data.balance;
      state.dungeon = await api("/api/dungeon");
      renderAll();
      toast(`Забрано: ${fmt(data.gold)}`);
    } catch (e) { toast(e.message); }
  });
}

function renderGifts() {
  const box = $("giftBox");
  if (!box) return;
  const gifts = state.gifts || [];
  box.innerHTML =
    `<div class="gift-send">
      <input id="giftUser" class="input" type="number" placeholder="ID друга">
      <select id="giftType" class="input">
        <option value="charm">Талисман (80)</option>
        <option value="insurance">Страховка (60)</option>
        <option value="lootbox">Кейс (250)</option>
        <option value="double_daily">Двойной бонус (120)</option>
      </select>
      <button class="secondary small" id="giftSend">Отправить</button>
    </div>
    <div class="gift-list">${gifts.length ? gifts.map((g) =>
      `<div class="gift-row">
        <span>🎁 ${g.gift} от ${g.from_name} ${g.note ? "· " + g.note : ""}</span>
        <button class="secondary small" data-gift-accept="${g.id}">Принять</button>
      </div>`).join("") : '<div class="empty">Нет подарков</div>'}</div>`;
  const send = box.querySelector("#giftSend");
  if (send) send.addEventListener("click", async () => {
    try {
      const data = await api("/api/gifts/send", {
        user_id: Number((box.querySelector("#giftUser") || {}).value) || 0,
        gift: (box.querySelector("#giftType") || {}).value || "charm",
        note: "",
      });
      state.user.balance = data.balance;
      renderAll();
      toast("Подарок отправлен!");
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-gift-accept]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/gifts/accept", { gift_id: btn.dataset.giftAccept });
        state.gifts = (await api("/api/gifts")).gifts;
        state.shop.inventory = (await api("/api/inventory")).inventory;
        renderAll();
        toast("Подарок принят!");
        confetti();
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadDungeonGifts() {
  try {
    const [d, g] = await Promise.all([
      api("/api/dungeon").catch(() => null),
      api("/api/gifts").catch(() => null),
    ]);
    if (d) state.dungeon = d;
    if (g) state.gifts = g.gifts;
  } catch (e) {}
}

function renderPvp() {
  const box = $("pvpBox");
  if (!box) return;
  const data = state.pvp || { rooms: [], active: null };
  if (data.active) {
    const a = data.active;
    box.innerHTML =
      `<div class="pvp-active">
        <div class="pvp-head">⚔ PvP: ${a.game} · ставка ${fmt(a.bet)}</div>
        <div class="pvp-meta">Статус: ${a.status === "waiting" ? "ожидание соперника" : "идёт бой"}</div>
        ${a.winner_id ? `<div class="pvp-winner">Победитель: ${a.winner_id === state.user.id ? "вы!" : "соперник"}</div>` : ""}
      </div>`;
    return;
  }
  box.innerHTML =
    `<div class="pvp-create">
      <select id="pvpGame" class="input">
        <option value="dice">Кости</option>
        <option value="coinflip">Орёл и решка</option>
        <option value="crash">Краш</option>
      </select>
      <input id="pvpBet" class="input" type="number" value="1000" min="100" max="100000">
      <button class="secondary small" id="pvpCreate">Создать</button>
    </div>
    <div class="pvp-list">${data.rooms.length ? data.rooms.map((r) =>
      `<div class="pvp-row">
        <span>${r.owner_name} · ${r.game} · ${fmt(r.bet)}</span>
        <button class="secondary small" data-pvp-join="${r.id}">Войти</button>
      </div>`).join("") : '<div class="empty">Нет открытых комнат</div>'}</div>`;
  const create = box.querySelector("#pvpCreate");
  if (create) create.addEventListener("click", async () => {
    try {
      const data = await api("/api/pvp/create", {
        game: (box.querySelector("#pvpGame") || {}).value || "dice",
        bet: Number((box.querySelector("#pvpBet") || {}).value) || 1000,
      });
      state.user.balance = data.balance != null ? data.balance : state.user.balance;
      state.pvp = await api("/api/pvp");
      renderAll();
      toast("Комната создана, ждите соперника!");
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-pvp-join]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/pvp/join", { room_id: btn.dataset.pvpJoin });
        state.user.balance = data.balance;
        state.pvp = await api("/api/pvp");
        renderAll();
        if (data.winner === state.user.id) {
          toast(`Победа! +${fmt(data.bet * 2)}`);
          confetti();
        } else {
          toast(`Поражение. Ваш бросок: ${data.guest_roll} против ${data.owner_roll}`);
        }
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadPvp() {
  try {
    state.pvp = await api("/api/pvp");
  } catch (e) {}
}

function renderWorkers() {
  const box = $("workerBox");
  if (!box) return;
  const data = state.workers || { recipes: [], hired: "", pending: 0, total_earned: 0 };
  const recipes = data.recipes || [];
  box.innerHTML =
    `<div class="worker-hired">${data.hired ?
      `💼 Рабочий: <b>${data.hired}</b> · накоплено: ${fmt(data.pending)} · всего: ${fmt(data.total_earned)}
       <button class="secondary small" id="workerCollect">Забрать (${fmt(data.pending)})</button>` :
      'Свободных рабочих нет — найми!'}</div>
    <div class="worker-list">${recipes.map((r) =>
      `<div class="worker-row ${r.hired ? "hired" : ""}">
        <div class="worker-info">
          <span class="worker-title">${r.worker === "fisher" ? "🐟 Рыбак" : r.worker === "farmer" ? "🌾 Фермер" : r.worker === "miner" ? "⛏ Шахтёр" : r.worker === "engineer" ? "🔧 Инженер" : "🔬 Учёный"}</span>
          <span class="worker-sub">+${fmt(r.income)} / ${r.period / 3600} ч</span>
        </div>
        <button class="secondary small" data-worker-hire="${r.worker}" ${r.hired ? "disabled" : ""}>
          ${r.hired ? "Нанят" : fmt(r.cost)}
        </button>
      </div>`).join("")}</div>`;
  const collect = box.querySelector("#workerCollect");
  if (collect) collect.addEventListener("click", async () => {
    try {
      const data = await api("/api/workers/collect");
      state.user.balance = data.balance;
      state.workers = await api("/api/workers");
      renderAll();
      toast(`+${fmt(data.earned)} заработано!`);
      sfx.cash();
    } catch (e) { toast(e.message); }
  });
  box.querySelectorAll("[data-worker-hire]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/workers/hire", { worker: btn.dataset.workerHire });
        state.user.balance = data.balance;
        state.workers = await api("/api/workers");
        renderAll();
        toast("Рабочий нанят!");
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadWorkers() {
  try {
    state.workers = await api("/api/workers");
  } catch (e) {}
}

function renderFarm() {
  const box = $("farmBox");
  if (!box) return;
  const data = state.farm || { plots: [], crops: [] };
  const plots = data.plots || [];
  const crops = data.crops || [];
  box.innerHTML =
    `<div class="farm-crops">${crops.map((c) =>
      `<button class="secondary small" data-farm-select="${c.key}">${c.title} · ${Math.floor(c.grow / 60)} мин</button>`).join("")}</div>
    <div class="farm-plots">${[0, 1, 2].map((i) => {
      const p = plots.find((x) => x.plot === i) || { crop: "", collected: 0 };
      return `<div class="farm-plot ${p.ready ? "ready" : ""}">
        <span class="farm-icon">${p.crop ? (p.ready ? "✅" : "🌱") : "🟫"}</span>
        <span class="farm-label">${p.crop ? (p.ready ? "Готово!" : Math.floor(p.seconds_left / 60) + " мин") : "Пусто"}</span>
        ${p.ready ? `<button class="secondary small" data-farm-collect="${i}">Собрать</button>` : ""}
      </div>`;
    }).join("")}</div>`;
  let selectedCrop = "";
  box.querySelectorAll("[data-farm-select]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedCrop = btn.dataset.farmSelect;
      toast(`Выбрано: ${btn.textContent}`);
    });
  });
  box.querySelectorAll("[data-farm-collect]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const data = await api("/api/farm/collect", { plot: Number(btn.dataset.farmCollect) });
        state.user.balance = data.balance;
        state.farm = await api("/api/farm");
        renderAll();
        toast(`Урожай! +${fmt(data.reward)}`);
        sfx.cash();
      } catch (e) { toast(e.message); }
    });
  });
  box.querySelectorAll(".farm-plots, .farm-icon").forEach((el) => {
    el.addEventListener("click", async () => {
      const plotEl = el.closest(".farm-plot");
      if (!plotEl || plotEl.classList.contains("ready")) return;
      const plotIndex = [...box.querySelectorAll(".farm-plot")].indexOf(plotEl);
      if (!selectedCrop) { toast("Сначала выбери культуру"); return; }
      try {
        await api("/api/farm/plant", { plot: plotIndex, crop: selectedCrop });
        state.farm = await api("/api/farm");
        renderAll();
        toast("Посажено!");
      } catch (e) { toast(e.message); }
    });
  });
}

async function loadFarm() {
  try {
    state.farm = await api("/api/farm");
  } catch (e) {}
}

function renderBattlepass() {
  const box = $("bpBox");
  if (!box) return;
  const data = state.bp || { season: "Сезон 1", bp: { level: 0, premium: 0 }, levels: [] };
  const bp = data.bp || {};
  const levels = data.levels || [];
  const claimed = (bp.rewards || []) || [];
  box.innerHTML =
    `<div class="bp-head">
      <span>🎫 ${data.season}</span>
      <span class="bp-levels">Уровень: <b>${bp.level}</b>${bp.premium ? " · PREMIUM" : ""}</span>
    </div>
    <div class="bp-track">${levels.map((l) => {
      const icon = l.free ? "🎁" : "🔒";
      const c = claimed.includes("f" + l.level) || claimed.includes("p" + l.level);
      return `<div class="bp-level ${l.level <= bp.level ? "open" : ""} ${c ? "claimed" : ""}">
        <span class="bp-icon">${c ? "✓" : icon}</span>
        <span class="bp-num">${l.level}</span>
      </div>`;
    }).join("")}</div>
    <div class="bp-actions">
      ${bp.premium ? "" : `<button class="cta small" id="bpBuy">Купить PREMIUM за 50 000</button>`}
      <button class="secondary small" id="bpClaimNext">Забрать награду</button>
    </div>`;
  const buy = box.querySelector("#bpBuy");
  if (buy) buy.addEventListener("click", async () => {
    try {
      const data = await api("/api/battlepass/buy");
      state.user.balance = data.balance;
      state.bp = await api("/api/battlepass");
      renderAll();
      toast("Премиум активирован!");
      confetti();
    } catch (e) { toast(e.message); }
  });
  const claim = box.querySelector("#bpClaimNext");
  if (claim) claim.addEventListener("click", async () => {
    const next = levels.find((l) => l.level <= bp.level
      && !claimed.includes("f" + l.level) && !claimed.includes("p" + l.level));
    if (!next) { toast("Нет доступных наград"); return; }
    const premium = claimed.includes("p" + next.level);
    try {
      const data = await api("/api/battlepass/claim", {
        level: next.level, premium: !!bp.premium,
      });
      state.user.balance = data.balance;
      state.bp = await api("/api/battlepass");
      renderAll();
      toast(`Награда +${fmt(data.amount)}!`);
      sfx.cash();
    } catch (e) { toast(e.message); }
  });
}

async function loadBattlepass() {
  try {
    state.bp = await api("/api/battlepass");
  } catch (e) {}
}

function renderAnalytics() {
  const box = $("analyticsBox");
  if (!box) return;
  const data = state.analytics || { by_game: [], daily: [], overview: {} };
  const o = data.overview || {};
  const byGame = data.by_game || [];
  const daily = data.daily || [];
  const maxWagered = Math.max(1, ...daily.map((d) => d.wagered));
  box.innerHTML =
    `<div class="an-overview">
      <div class="an-stat"><span class="an-val">${o.level || 1}</span><span class="an-lbl">уровень</span></div>
      <div class="an-stat"><span class="an-val">#${o.rank || 0}</span><span class="an-lbl">место в топе</span></div>
      <div class="an-stat"><span class="an-val">×${Number(o.best_multiplier || 1).toFixed(2)}</span><span class="an-lbl">лучший множитель</span></div>
      <div class="an-stat"><span class="an-val">${fmt(o.total_won || 0)}</span><span class="an-lbl">выиграно всего</span></div>
    </div>
    <div class="an-section">
      <h5>Последняя неделя</h5>
      <div class="an-bars">${daily.map((d) =>
        `<div class="an-bar-col">
          <div class="an-bar" title="${d.day}: ${fmt(d.wagered)} оборот" style="height:${Math.round(d.wagered / maxWagered * 60)}px"></div>
          <span class="an-bar-day">${d.day}</span>
        </div>`).join("")}</div>
    </div>
    <div class="an-section">
      <h5>По играм</h5>
      ${byGame.map((g) =>
        `<div class="an-game-row">
          <span>${g.game}</span>
          <span class="an-game-meta">${g.rounds} игр · оборот ${fmt(g.wagered)} · ${Math.round(g.wins / Math.max(1, g.rounds) * 100)}% побед</span>
        </div>`).join("") || '<div class="empty">Нет данных за 7 дней</div>'}
    </div>`;
}

async function loadAnalytics() {
  try {
    state.analytics = await api("/api/analytics");
  } catch (e) {}
}

function renderCalendar() {
  const box = $("calendarBox");
  if (!box) return;
  const rewards = state.calendar || [];
  const claimed = new Set(rewards.filter((r) => r.claimed).map((r) => r.day));
  const nextDay = rewards.length ? Math.min(...rewards.filter((r) => !r.claimed).map((r) => r.day), 31) : 1;
  box.innerHTML =
    `<div class="cal-grid">${rewards.map((r) =>
      `<div class="cal-cell ${r.claimed ? "claimed" : r.day === nextDay ? "next" : ""}">
        <span class="cal-day">${r.day}</span>
        <span class="cal-reward">${fmt(r.reward)}</span>
      </div>`).join("") || '<div class="empty">Календарь пуст</div>'}</div>
    <button class="cta small" id="calClaim" ${nextDay <= 30 ? "" : "disabled"}>
      ${nextDay <= 30 ? `Забрать день ${nextDay}` : "Календарь пройден"}
    </button>`;
  const claim = box.querySelector("#calClaim");
  if (claim) claim.addEventListener("click", async () => {
    try {
      const data = await api("/api/calendar/claim", { day: nextDay });
      state.user.balance = data.balance;
      state.calendar = (await api("/api/calendar")).rewards;
      renderAll();
      toast(`День ${data.day}: +${fmt(data.reward)}!`);
      confetti();
    } catch (e) { toast(e.message); }
  });
}

async function loadCalendar() {
  try {
    state.calendar = (await api("/api/calendar")).rewards;
  } catch (e) {}
}

function renderNews() {
  const box = $("newsBox");
  if (!box) return;
  const news = state.news || [];
  box.innerHTML = news.length ? news.map((n) =>
    `<div class="news-item ${n.read ? "" : "unread"}" data-news-id="${n.id}">
      <span class="news-icon">${n.icon}</span>
      <div class="news-body">
        <span class="news-title">${n.title}</span>
        <span class="news-text">${n.body}</span>
        <span class="news-date">${new Date(n.created_at * 1000).toLocaleString("ru-RU")}</span>
      </div>
    </div>`).join("") : '<div class="empty">Новостей нет</div>';
  box.querySelectorAll("[data-news-id]").forEach(async (el) => {
    if (el.classList.contains("unread")) {
      try {
        await api("/api/news/read", { news_id: el.dataset.newsId });
        el.classList.remove("unread");
      } catch (e) {}
    }
  });
}

function renderPartners() {
  const box = $("partnerBox");
  if (!box) return;
  const data = state.partners || { stats: { children: [], active: 0, level: 1, title: "Новичок", bonus: 0 }, levels: [] };
  const s = data.stats || {};
  box.innerHTML =
    `<div class="partner-head">
      <span>🤝 Уровень: <b>${s.title} (${s.level})</b></span>
      <span class="partner-bonus">+${Math.round((s.bonus || 0) * 100)}% бонус</span>
    </div>
    <div class="partner-meta">Активных приглашённых: <b>${s.active}</b></div>
    <div class="partner-levels">${(data.levels || []).map((l) =>
      `<div class="partner-level ${l.level === s.level ? "current" : ""}">
        <span>${l.title} — ${Math.round(l.bonus * 100)}%</span>
        <span class="partner-need">нужно ${l.min_children} приглашённых</span>
      </div>`).join("")}</div>
    <button class="secondary small" id="partnerLink">Скопировать ссылку</button>`;
  const link = box.querySelector("#partnerLink");
  if (link) link.addEventListener("click", async () => {
    try {
      const data = await api("/api/partners/link", {});
      try {
        await navigator.clipboard.writeText(data.link);
        toast("Ссылка скопирована");
      } catch (e) {
        toast(data.link);
      }
    } catch (e) { toast(e.message); }
  });
}

async function loadNewsPartners() {
  try {
    const [n, p] = await Promise.all([
      api("/api/news").catch(() => null),
      api("/api/partners").catch(() => null),
    ]);
    if (n) state.news = n.news;
    if (p) state.partners = p;
  } catch (e) {}
}

function fmtNum(n) {
  return Number(n || 0).toLocaleString("ru-RU");
}

function renderEconomy() {
  const box = $("economyBox");
  if (!box) return;
  const data = state.economy || {};
  const acc = data.account || {};
  box.innerHTML = `
    <div class="ec-balances">
      <div class="ec-bal"><span>💵 Наличные</span><b>${fmtNum(acc.cash)}</b></div>
      <div class="ec-bal"><span>🏦 Банк</span><b>${fmtNum(acc.bank)}</b></div>
      <div class="ec-bal"><span>💠 Кредиты</span><b>${fmtNum(acc.credits)}</b></div>
      <div class="ec-bal"><span>💎 Гемы</span><b>${fmtNum(acc.gems)}</b></div>
      <div class="ec-bal"><span>⚡ Энергия</span><b>${acc.energy}/${acc.energy_max}</b></div>
    </div>
    <div class="ec-wealth">Совокупное богатство: <b>${fmtNum(data.wealth)}</b></div>
    <details class="ec-block" open>
      <summary>💹 Биржа акций</summary>
      <div class="ec-stocks">${(data.stocks || []).map((s) => `
        <div class="ec-stock">
          <span class="ec-sym">${s.symbol}</span>
          <span class="ec-comp">${s.company}</span>
          <span class="ec-price">${Number(s.price).toFixed(1)}</span>
          <span class="ec-trend" style="color:${s.price >= s.base_price ? "var(--ok,#4caf50)" : "var(--bad,#e53935)"}">
            ${s.price >= s.base_price ? "▲" : "▼"} ${Math.abs(((s.price / s.base_price) - 1) * 100).toFixed(1)}%</span>
          <button class="secondary small" data-buy="${s.symbol}">Купить</button>
        </div>`).join("")}</div>
    </details>
    <details class="ec-block">
      <summary>📈 Мой портфель</summary>
      <div class="ec-port">${(data.portfolio || []).length ? (data.portfolio).map((p) => `
        <div class="ec-port-item">
          <span>${p.symbol}: <b>${p.shares} шт</b></span>
          <span>${fmtNum(p.value)} (вложено ${fmtNum(p.invested)})</span>
          <button class="secondary small danger" data-sell="${p.symbol}">Продать 1</button>
        </div>`).join("") : '<div class="empty">Нет акций</div>'}</div>
    </details>
    <details class="ec-block">
      <summary>🏦 Депозиты</summary>
      <div class="ec-deposits">${(data.deposits || []).length ? (data.deposits).map((d) => `
        <div class="ec-dep">
          <span>Вклад на ${d.term_days} дн. · ${d.interest_pct}%</span>
          <span>${fmtNum(d.principal)}</span>
          <button class="secondary small" data-close="${d.plan_id}">Забрать</button>
        </div>`).join("") : '<div class="empty">Нет вкладов. Открой от 500 монет.</div>'}</div>
      <div class="ec-actions">
        <button class="secondary small" data-dep="starter">Вклад 500 (3 дн, 3%)</button>
        <button class="secondary small" data-dep="econom">Вклад 2000 (7 дн, 5%)</button>
        <button class="secondary small" data-dep="growth">Вклад 5000 (14 дн, 7.5%)</button>
        <button class="secondary small" data-dep="premium">Вклад 10000 (30 дн, 10%)</button>
      </div>
    </details>
    <details class="ec-block">
      <summary>🔄 Обмен валют</summary>
      <div class="ec-info">${(data.rates || {})["gem"] ? `Гем = ${Number(data.rates.gem.rate).toFixed(0)} золота, кредит = ${Number((data.rates.credit || {}).rate || 10).toFixed(0)} золота` : ""}</div>
      <div class="ec-actions">
        <button class="secondary small" data-ex="gold:gem">Купить гемы за золото</button>
        <button class="secondary small" data-ex="gem:gold">Продать гемы</button>
      </div>
    </details>
    <details class="ec-block">
      <summary>🧾 История операций</summary>
      <div class="ec-log">${(data.log || []).slice(0, 10).map((l) => `
        <div class="ec-log-item">${l.action} · ${fmtNum(l.amount)} · баланс ${fmtNum(l.balance_after)}</div>`).join("")}</div>
    </details>`;
  box.querySelectorAll("[data-buy]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/economy/stock/buy", { symbol: b.dataset.buy, shares: 1 });
      state.economy.portfolio = r.portfolio;
      toast(`Куплена 1 акция ${b.dataset.buy}`);
      renderEconomy();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-sell]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/economy/stock/sell", { symbol: b.dataset.sell, shares: 1 });
      state.economy.portfolio = r.portfolio;
      toast(`Продана 1 акция ${b.dataset.sell}`);
      renderEconomy();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/economy/deposit/close", { plan_id: b.dataset.close });
      toast(`Вклад закрыт: +${fmtNum(r.payout)}`);
      renderEconomy();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-dep]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/economy/deposit", { plan_id: b.dataset.dep, amount: 0 });
      toast(`Вклад открыт: ${fmtNum(r.plan.principal)}`);
      renderEconomy();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const [from, to] = b.dataset.ex.split(":");
      const amount = from === "gold" ? 100 : 1;
      await api("/api/economy/exchange", { from, to, amount });
      toast(`Обмен ${from} → ${to} выполнен`);
      renderEconomy();
    } catch (e) { toast(e.message); }
  }));
}

async function loadEconomy() {
  try {
    const data = await api("/api/economy").catch(() => null);
    if (data) state.economy = data;
  } catch (e) {}
}

function renderGuild() {
  const box = $("guildBox");
  if (!box) return;
  const data = state.guild || {};
  if (!data.clan) {
    box.innerHTML = '<div class="empty">Вступи в гильдию, чтобы строить здания</div>';
    return;
  }
  const c = data.clan;
  const res = data.resources || {};
  const prod = data.production || {};
  box.innerHTML = `
    <div class="guild-head">
      <span class="guild-name">${c.name} <b>[${c.tag}]</b></span>
      <span class="guild-power">⚔ ${fmtNum(c.power)}</span>
    </div>
    <div class="guild-meta">Уровень ${c.level} · Члены ${c.members}/${c.member_limit}</div>
    <div class="guild-res">
      <span>🪵 ${fmtNum(res.wood)} <small>+${prod.wood}/час</small></span>
      <span>🪨 ${fmtNum(res.stone)} <small>+${prod.stone}/час</small></span>
      <span>⛏ ${fmtNum(res.iron)} <small>+${prod.iron}/час</small></span>
      <span>🌾 ${fmtNum(res.food)} <small>+${prod.food}/час</small></span>
      <span>🪙 ${fmtNum(res.gold)}</span>
    </div>
    <div class="guild-buildings">${(data.buildings || []).map((b) => `
      <div class="guild-building">
        <div class="gb-top">
          <span class="gb-name">${b.name}</span>
          <span class="gb-level">ур. ${b.level}/${b.max_level}</span>
        </div>
        <div class="gb-desc">${b.desc}</div>
        ${b.level < b.max_level ? `
          <button class="secondary small" data-gup="${b.key}">
            Построить (🪵${b.next_cost.wood} 🪨${b.next_cost.stone} ⛏${b.next_cost.iron})
          </button>` : '<span class="gb-max">Максимум</span>'}
      </div>`).join("")}</div>
    <div class="guild-actions">
      <button class="secondary small" data-gdon="wood">+100 дерева (200💰)</button>
      <button class="secondary small" data-gdon="stone">+100 камня (200💰)</button>
      <button class="secondary small" data-gdon="iron">+100 железа (200💰)</button>
    </div>`;
  box.querySelectorAll("[data-gup]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/guild/upgrade", { building: b.dataset.gup });
      toast(`Здание улучшено до ур. ${r.level}`);
      renderGuild();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-gdon]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/guild/donate", { resource: b.dataset.gdon, amount: 100 });
      toast(`Пожертвовано ресурсов в гильдию`);
      renderGuild();
    } catch (e) { toast(e.message); }
  }));
}

async function loadGuild() {
  try {
    const data = await api("/api/guild").catch(() => null);
    if (data) state.guild = data;
  } catch (e) {}
}

function renderMap() {
  const box = $("mapBox");
  if (!box) return;
  const data = state.map || {};
  const provs = data.provinces || [];
  const st = data.stats || {};
  const myClan = data.my_clan;
  box.innerHTML = `
    <div class="map-top">
      <span>Провинций: <b>${st.total || 0}</b></span>
      <span>Захвачено: <b>${st.owned_count || 0}</b></span>
      ${myClan ? `<span>Ваш клан: <b>${myClan}</b></span>` : ""}
    </div>
    <div class="map-grid">${provs.map((p) => {
      const owned = p.owner_clan && p.owner_clan === myClan;
      const neutral = !p.owner_clan;
      return `
        <div class="map-cell ${owned ? "mine" : neutral ? "neutral" : "enemy"}" style="grid-column:${p.x};grid-row:${p.y}">
          <div class="mp-name">${p.name}</div>
          <div class="mp-inc">💰 ${p.base_income}/ч</div>
          <div class="mp-def">🛡 ${p.defense}</div>
          <div class="mp-owner">${p.owner_clan ? `Клан ${p.owner_clan}` : "Свободна"}</div>
          ${myClan ? `
            <div class="mp-actions">
              ${neutral ? `<button class="secondary small" data-mclaim="${p.province_id}">Захватить</button>` : ""}
              ${p.owner_clan && p.owner_clan !== myClan ? `
                <button class="secondary small" data-mattack="${p.province_id}">Атаковать</button>
                ${p.defense <= 0 ? `<button class="secondary small" data-mcap="${p.province_id}">Завоевать</button>` : ""}
              ` : ""}
              ${owned ? `<button class="secondary small" data-mcollect="${p.province_id}">Собрать доход</button>` : ""}
            </div>` : ""}
        </div>`;
    }).join("")}</div>
    <div class="map-leaders">${(st.leaders || []).map((l) =>
      `<span>Клан ${l.owner_clan}: ${l.c} пров.</span>`).join(" · ") || "Пока никто не захватил провинции"}</div>`;
  const act = async (path, payload, msg) => {
    try {
      await api(path, payload);
      toast(msg);
      const d = await api("/api/map");
      if (d) state.map = d;
      renderMap();
    } catch (e) { toast(e.message); }
  };
  box.querySelectorAll("[data-mclaim]").forEach((b) => b.addEventListener("click", () =>
    act("/api/map/claim", { province_id: b.dataset.mclaim }, "Провинция захвачена!")));
  box.querySelectorAll("[data-mattack]").forEach((b) => b.addEventListener("click", () =>
    act("/api/map/attack", { province_id: b.dataset.mattack, force: 150 }, "Атака выполнена")));
  box.querySelectorAll("[data-mcap]").forEach((b) => b.addEventListener("click", () =>
    act("/api/map/capture", { province_id: b.dataset.mcap }, "Провинция завоёвана!")));
  box.querySelectorAll("[data-mcollect]").forEach((b) => b.addEventListener("click", () =>
    act("/api/map/collect", { province_id: b.dataset.mcollect }, "Доход собран")));
}

async function loadMap() {
  try {
    const data = await api("/api/map").catch(() => null);
    if (data) state.map = data;
  } catch (e) {}
}

function renderTournament() {
  const box = $("tournamentSeasonBox");
  if (!box) return;
  const data = state.tournament || {};
  const seasons = data.seasons || [];
  if (!seasons.length) {
    box.innerHTML = '<div class="empty">Турниров пока нет. Заглядывай позже!</div>';
    return;
  }
  box.innerHTML = seasons.map((t) => {
    const s = t.season || {};
    const parts = t.participants || [];
    const matches = t.matches || [];
    const my = t.my_participant;
    const statusIcon = s.status === "qualify" ? "⏳" : s.status === "active" ? "⚔️" : "🏁";
    return `
      <div class="trn-season">
        <div class="trn-head">
          <span>${statusIcon} ${s.title} <small>(${s.game})</small></span>
          <span class="trn-pool">💰 ${fmtNum(s.prize_pool)}</span>
        </div>
        <div class="trn-status">Статус: <b>${s.status === "qualify" ? "Квалификация" : s.status === "active" ? "Плей-офф" : "Завершён"}</b>
          ${my ? ` · Ваш результат: <b>${Number(my.score).toFixed(0)}</b>${my.qualified ? " ✅" : ""}` : ""}
        </div>
        ${s.status === "qualify" ? `
          <div class="trn-qualify">
            <div class="trn-parts">${parts.slice(0, 8).map((p, i) =>
              `<span class="trn-part ${p.user_id === (state.me || {}).id ? "me" : ""}">${i + 1}. ID ${p.user_id} — ${Number(p.score).toFixed(0)}</span>`
            ).join("")}</div>
            <button class="secondary small" data-trqual="${s.season_id}">Записать результат (лучшая игра)</button>
          </div>` : s.status === "active" ? `
          <div class="trn-matches">${matches.filter((m) => !m.finished).slice(0, 6).map((m) => `
            <div class="trn-match">
              <span>${m.user_a ?? "—"} vs ${m.user_b ?? "—"}</span>
              <span class="trn-score">${Number(m.score_a).toFixed(0)} : ${Number(m.score_b).toFixed(0)}</span>
              <button class="secondary small" data-trplay="${m.match_id}">Сыграть</button>
            </div>`).join("") || '<div class="empty">Матчей нет</div>'}</div>` : `
          <div class="trn-done">Турнир завершён. Победители получают призы!</div>`}
        <div class="trn-prizes">${(t.prizes || []).map((p) =>
          `<span class="trn-prize">${p.place} место: ${p.title} — ${fmtNum(p.prize)}</span>`).join(" · ")}</div>
      </div>`;
  }).join("");
  box.querySelectorAll("[data-trqual]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const score = Number(prompt("Ваш лучший результат в игре:")) || 0;
      await api("/api/tournament/qualify", { season_id: b.dataset.trqual, score });
      toast("Результат записан!");
      loadTournament().then(renderTournament);
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-trplay]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const score = Number(prompt("Ваш результат в матче:")) || 0;
      await api("/api/tournament/play", { match_id: b.dataset.trplay, score });
      toast("Матч сыгран!");
      loadTournament().then(renderTournament);
    } catch (e) { toast(e.message); }
  }));
}

async function loadTournament() {
  try {
    const data = await api("/api/tournament").catch(() => null);
    if (data) state.tournament = data;
  } catch (e) {}
}

function renderCardMarket() {
  const box = $("cardMarketBox");
  if (!box) return;
  const data = state.cardMarket || {};
  const cards = data.cards || {};
  const album = data.album || [];
  const progress = data.progress || { sets: [] };
  const rarityCls = { common: "c-common", uncommon: "c-uncommon", rare: "c-rare", epic: "c-epic", legendary: "c-legendary" };
  box.innerHTML = `
    <div class="cm-top">
      <span>Карт: <b>${Object.keys(cards).length}</b></span>
      <span>Дубликатов: <b>${data.duplicates || 0}</b></span>
      <span>Пыль: <b>${data.dust || 0}</b></span>
    </div>
    <div class="cm-sets">${(progress.sets || []).map((s) =>
      `<span class="cm-set">${s.set_key}: ${s.owned}/${s.total}</span>`).join(" · ") || ""}</div>
    <details class="ec-block">
      <summary>🖼 Мой альбом</summary>
      <div class="cm-cards">${album.map((c) => {
        const qty = cards[c.card] || 0;
        return `
        <div class="cm-card ${rarityCls[c.rarity] || "c-common"}">
          <div class="cm-card-title">${c.title}</div>
          <div class="cm-card-meta">${c.set_key} #${c.number} · ${c.rarity}</div>
          <div class="cm-qty">×${qty}</div>
          ${qty > 1 ? `<button class="secondary small" data-cm-dis="${c.card}">Разобрать (1)</button>` : ""}
          ${qty >= 1 ? `<button class="secondary small" data-cm-sell="${c.card}">Продать (50💠)</button>` : ""}
        </div>`;
      }).join("")}</div>
    </details>
    <details class="ec-block">
      <summary>🏪 Рынок карт</summary>
      <div class="cm-offers">${(data.offers || []).map((o) => `
        <div class="cm-offer">
          <span>${o.card} ×${o.qty} — ${fmtNum(o.price)}💠</span>
          <button class="secondary small" data-cm-buy="${o.offer_id}">Купить</button>
        </div>`).join("") || '<div class="empty">Нет предложений</div>'}</div>
    </details>`;
  box.querySelectorAll("[data-cm-dis]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/cards/dismantle", { card: b.dataset.cmDis, qty: 1 });
      toast("Карта разобрана в пыль/жетоны");
      refreshCardMarket();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-cm-sell]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/cards/offer/create", { card: b.dataset.cmSell, price: 50 });
      toast("Предложение выставлено за 50💠");
      refreshCardMarket();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-cm-buy]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/cards/offer/buy", { offer_id: b.dataset.cmBuy });
      toast("Карта куплена!");
      refreshCardMarket();
    } catch (e) { toast(e.message); }
  }));
}

async function refreshCardMarket() {
  try {
    const data = await api("/api/cards/market");
    if (data) state.cardMarket = data;
    renderCardMarket();
  } catch (e) { toast(e.message); }
}

async function loadCardMarket() {
  try {
    const data = await api("/api/cards/market").catch(() => null);
    if (data) state.cardMarket = data;
  } catch (e) {}
}

function renderStreet() {
  const box = $("streetBox");
  if (!box) return;
  const data = state.street || {};
  box.innerHTML = `
    <div class="st-top">
      <span>Опыт: <b>${fmtNum(data.exp)}</b></span>
      <span>Доход/час: <b>${fmtNum(data.income)}</b></span>
      <span>Наличные: <b>${fmtNum(data.cash)}</b></span>
    </div>
    <details class="ec-block" open>
      <summary>🏠 Недвижимость</summary>
      <div class="st-props">${(data.properties || []).map((p) => `
        <div class="st-prop">
          <div class="stp-name">${p.name} <small>ур. ${p.level}/${p.max_level}</small></div>
          <div class="stp-inc">💰 ${fmtNum(p.income)}/час</div>
          <div class="stp-desc">${p.desc}</div>
          ${p.level < p.max_level ? `<button class="secondary small" data-stbuy="${p.key}">${p.level ? "Улучшить" : "Купить"} (${fmtNum(Math.round(p.cost * (p.level + 1)))})</button>` : '<span class="gb-max">Максимум</span>'}
        </div>`).join("")}</div>
    </details>
    <details class="ec-block">
      <summary>💼 Работа</summary>
      ${data.my_job ? `<div class="st-job-current">Текущая: <b>${data.my_job.job_key}</b>
        <button class="secondary small" data-stjobcollect>Собрать</button></div>` : ""}
      <div class="st-jobs">${(data.jobs || []).map((j) => `
        <div class="st-job">
          <span>${j.name} <small>(${j.desc})</small></span>
          <button class="secondary small" data-stjob="${j.key}">Устроиться · +${fmtNum(j.reward)}</button>
        </div>`).join("")}</div>
    </details>
    <details class="ec-block">
      <summary>🎰 Джекпот</summary>
      <div class="st-jack">
        <div class="st-jack-pool">Банк: <b>${fmtNum((data.jackpot || {}).pool)}</b></div>
        <div class="st-jack-meta">Ваши билеты: ${fmtNum(data.my_tickets)} · Розыгрыш ${new Date((data.jackpot || {}).next_draw * 1000 || Date.now() + 86400000).toLocaleString("ru-RU")}</div>
        <div class="st-jack-actions">
          <button class="secondary small" data-jack="100">Купить билет (100)</button>
          <button class="secondary small" data-jack="500">Купить билет (500)</button>
        </div>
      </div>
    </details>`;
  box.querySelectorAll("[data-stbuy]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/street/buy", { prop_type: b.dataset.stbuy });
      toast(`Недвижимость: ур. ${r.level}`);
      state.street.cash = r.cash;
      state.street.income = r.income;
      renderStreet();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-stjob]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/street/job/apply", { job_key: b.dataset.stjob });
      toast("Устроились на работу!");
      loadStreet().then(renderStreet);
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-stjobcollect]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/street/job/collect", {});
      toast(`Зарплата: +${fmtNum(r.reward)}`);
      if (state.street) state.street.cash = r.cash;
      renderStreet();
    } catch (e) { toast(e.message); }
  }));
  box.querySelectorAll("[data-jack]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const r = await api("/api/jackpot/buy", { amount: Number(b.dataset.jack) });
      toast("Билет джекпота куплен!");
      if (state.street) state.street.cash = r.cash;
      loadStreet().then(renderStreet);
    } catch (e) { toast(e.message); }
  }));
}

async function loadStreet() {
  try {
    const data = await api("/api/street").catch(() => null);
    if (data) state.street = data;
  } catch (e) {}
}

const ONBOARD_STEPS = [
  { emoji: "💣", title: "Добро пожаловать!",
    text: "Открывай клетки, собирай множитель и забирай выигрыш. Внизу — вкладки: Игра, Активности, Топ и Профиль." },
  { emoji: "🎯", title: "Ставка и мины",
    text: "Выбери ставку и число мин. Чем больше мин — тем выше множитель, но и риск выше." },
  { emoji: "💰", title: "Забирай выигрыш",
    text: "Открыл несколько клеток — жми «Забрать». Первая мина закрывает партию и сжигает ставку." },
  { emoji: "🎁", title: "Бонусы каждый день",
    text: "Заходи за часовым и ежедневным бонусом, крути колесо дня, забирай награды за уровни и задания." },
];

function setupOnboard() {
  const box = $("onboard");
  if (!box) return;
  const btn = $("onboardNext");
  const dots = $("onboardDots");
  const emojiEl = $("onboardEmoji");
  const titleEl = $("onboardTitle");
  const textEl = $("onboardText");
  let step = 0;
  let done = false;
  try { done = localStorage.getItem("saper_onboard_done") === "1"; } catch (e) {}
  if (done) { box.hidden = true; return; }
  const paint = () => {
    const item = ONBOARD_STEPS[step];
    if (emojiEl) emojiEl.textContent = item.emoji;
    if (titleEl) titleEl.textContent = item.title;
    if (textEl) textEl.textContent = item.text;
    if (dots) {
      dots.innerHTML = ONBOARD_STEPS
        .map((_, i) => `<span class="onboard-dot${i === step ? " active" : ""}"></span>`)
        .join("");
    }
    if (btn) btn.textContent = step === ONBOARD_STEPS.length - 1 ? "Начать" : "Далее";
  };
  const close = () => {
    box.classList.remove("show");
    box.hidden = true;
    try { localStorage.setItem("saper_onboard_done", "1"); } catch (e) {}
  };
  if (btn) {
    btn.addEventListener("click", () => {
      if (step < ONBOARD_STEPS.length - 1) {
        step += 1;
        paint();
      } else {
        close();
      }
    });
  }
  paint();
  box.hidden = false;
  requestAnimationFrame(() => box.classList.add("show"));
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
  setupOnboard();
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
