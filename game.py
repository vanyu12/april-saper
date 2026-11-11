import hashlib
import hmac
import math
import time

CELLS = 25
SIDE = 5
RTP = 0.99
MIN_BET = 10
MAX_BET = 100_000
START_BALANCE = 1000
DAILY_BONUS = 300
DAILY_COOLDOWN = 24 * 60 * 60
HOURLY_BONUS = 100
HOURLY_COOLDOWN = 60 * 60
REF_BONUS = 500
REF_GAMES_REQUIRED = 5

XP_PER_GAME = 10
XP_PER_WIN = 15
XP_PER_DUEL_WIN = 40

LEVEL_TITLES = (
    (1, "Новобранец"),
    (3, "Сапёр"),
    (5, "Старшина"),
    (8, "Ветеран"),
    (12, "Мастер"),
    (18, "Легенда"),
    (25, "Гроссмейстер"),
)


def xp_for_level(level: int) -> int:
    """Сколько всего XP нужно, чтобы достичь уровня."""
    level = max(1, int(level))
    return 50 * (level - 1) * level


def level_from_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def level_title(level: int) -> str:
    title = LEVEL_TITLES[0][1]
    for start, name in LEVEL_TITLES:
        if level >= start:
            title = name
    return title


def level_view(xp: int) -> dict:
    xp = max(0, int(xp))
    level = level_from_xp(xp)
    floor_xp = xp_for_level(level)
    next_xp = xp_for_level(level + 1)
    need = next_xp - floor_xp
    into = xp - floor_xp
    percent = round(into / need * 100, 1) if need else 100.0
    return {"level": level, "title": level_title(level), "xp": xp,
            "into": into, "need": need, "percent": percent, "next": next_xp}

REF_LADDER = (
    {"step": 3, "reward": 350},
    {"step": 6, "reward": 800},
    {"step": 10, "reward": 1200},
    {"step": 25, "reward": 2500},
    {"step": 50, "reward": 5500},
)

SPONSOR_REWARD = 500


def _safe_count(mines: int) -> int:
    return CELLS - mines


def multiplier(mines: int, opened: int) -> float:
    """M = RTP / P(k), округлённый вниз до сотых."""
    safe = _safe_count(mines)
    if opened <= 0:
        return 1.0
    opened = min(opened, safe)
    p = 1.0
    for i in range(opened):
        p *= (safe - i) / (CELLS - i)
    value = math.floor((RTP / p) * 100) / 100
    return max(1.0, value)


def max_multiplier(mines: int) -> float:
    return multiplier(mines, _safe_count(mines))


def next_chance(mines: int, opened: int) -> float:
    """Вероятность, что следующая открытая клетка окажется безопасной."""
    safe = _safe_count(mines) - opened
    left = CELLS - opened
    if left <= 0:
        return 0.0
    return safe / left


def payout_for(bet: int, mult: float) -> int:
    return int(math.floor(bet * mult))


def ladder(mines: int, opened: int, steps: int = 5) -> list[dict]:
    """Следующие шаги: сколько даст каждая открытая клетка и её шанс."""
    safe = _safe_count(mines)
    result = []
    for k in range(opened + 1, min(opened + 1 + steps, safe + 1)):
        result.append({
            "opened": k,
            "multiplier": multiplier(mines, k),
            "chance": next_chance(mines, k),
        })
    return result


def _byte_stream(server_seed: str, client_seed: str, nonce: int, cursor: int):
    counter = 0
    key = server_seed.encode()
    while True:
        msg = f"{client_seed}:{nonce}:{cursor}:{counter}".encode()
        digest = hmac.new(key, msg, hashlib.sha256).digest()
        for byte in digest:
            yield byte
        counter += 1


def _floats(server_seed: str, client_seed: str, nonce: int, cursor: int, count: int):
    stream = _byte_stream(server_seed, client_seed, nonce, cursor)
    for _ in range(count):
        raw = 0
        for _ in range(4):
            raw = (raw << 8) | next(stream)
        yield raw / 2 ** 32


def generate_mines(server_seed: str, client_seed: str, nonce: int, count: int) -> list[int]:
    """Детерминированный выбор позиций мин: Fisher-Yates на HMAC-потоке."""
    count = max(1, min(CELLS - 1, count))
    tiles = list(range(CELLS))
    for i in range(CELLS - 1, 0, -1):
        r = next(_floats(server_seed, client_seed, nonce, i, 1))
        j = int(r * (i + 1))
        tiles[i], tiles[j] = tiles[j], tiles[i]
    return sorted(tiles[:count])


def verify(server_seed: str, client_seed: str, nonce: int,
           positions: list[int], count: int) -> bool:
    return generate_mines(server_seed, client_seed, nonce, count) == sorted(positions)


def hash_seed(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


DICE_MULTIPLIER = 1.96

DUEL_RAKE = 0.05
DUEL_TTL = 10 * 60


def duel_roll(server_seed: str, client_seed: str, nonce: int) -> int:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return min(100, int(value * 100) + 1)


def duel_prize(bet: int) -> int:
    return int(math.floor(int(bet) * 2 * (1 - DUEL_RAKE)))

WHEEL_SEGMENTS = (
    {"multiplier": 0.0, "weight": 35},
    {"multiplier": 1.1, "weight": 25},
    {"multiplier": 1.35, "weight": 18},
    {"multiplier": 1.7, "weight": 12},
    {"multiplier": 2.3, "weight": 7},
    {"multiplier": 3.2, "weight": 3},
)

DAY_OFFSET = 3 * 3600

DAILY_SPIN = (
    {"kind": "coins", "amount": 25, "weight": 150},
    {"kind": "coins", "amount": 50, "weight": 150},
    {"kind": "coins", "amount": 75, "weight": 100},
    {"kind": "coins", "amount": 100, "weight": 120},
    {"kind": "coins", "amount": 150, "weight": 90},
    {"kind": "coins", "amount": 200, "weight": 80},
    {"kind": "coins", "amount": 250, "weight": 80},
    {"kind": "coins", "amount": 350, "weight": 60},
    {"kind": "coins", "amount": 500, "weight": 45},
    {"kind": "coins", "amount": 800, "weight": 30},
    {"kind": "coins", "amount": 1000, "weight": 18},
    {"kind": "coins", "amount": 1500, "weight": 10},
    {"kind": "coins", "amount": 3000, "weight": 4},
    {"kind": "coins", "amount": 5000, "weight": 2},
    {"kind": "item", "item": "insurance", "weight": 60},
    {"kind": "item", "item": "charm", "weight": 30},
)

SPIN_COOLDOWN = 12 * 60 * 60
SPIN_STREAK_DAYS = 7

DAILY_QUESTS = (
    {"key": "games5", "title": "Сыграть 5 партий", "metric": "games", "target": 5, "reward": 300},
    {"key": "wins3", "title": "Выиграть 3 раза", "metric": "wins", "target": 3, "reward": 500},
    {"key": "wager1000", "title": "Поставить 1000 mCoin", "metric": "wagered", "target": 1000,
     "reward": 700},
)

ACHIEVEMENTS = (
    {"key": "first_game", "icon": "🎯", "title": "Первая партия",
     "desc": "Сыграть одну партию", "metric": "games_played", "target": 1,
     "reward": 100, "xp": 20},
    {"key": "games_10", "icon": "🔟", "title": "Десятка",
     "desc": "Сыграть 10 партий", "metric": "games_played", "target": 10,
     "reward": 200, "xp": 30},
    {"key": "games_50", "icon": "🎖", "title": "Полсотни",
     "desc": "Сыграть 50 партий", "metric": "games_played", "target": 50,
     "reward": 500, "xp": 60},
    {"key": "win_1", "icon": "🏅", "title": "Первая победа",
     "desc": "Выиграть один раз", "metric": "games_won", "target": 1,
     "reward": 100, "xp": 20},
    {"key": "win_10", "icon": "🥇", "title": "Десять побед",
     "desc": "Выиграть 10 раз", "metric": "games_won", "target": 10,
     "reward": 400, "xp": 50},
    {"key": "mult_3", "icon": "🔥", "title": "Кэшаут ×3",
     "desc": "Забрать выигрыш на множителе ×3", "metric": "best_multiplier", "target": 3,
     "reward": 250, "xp": 40},
    {"key": "mult_10", "icon": "💎", "title": "Кэшаут ×10",
     "desc": "Забрать выигрыш на множителе ×10", "metric": "best_multiplier", "target": 10,
     "reward": 1000, "xp": 100},
    {"key": "balance_5000", "icon": "🪙", "title": "Пять тысяч",
     "desc": "Накопить 5 000 mCoin", "metric": "balance", "target": 5000,
     "reward": 300, "xp": 50},
    {"key": "deposit_first", "icon": "🏦", "title": "Первый вклад",
     "desc": "Открыть депозит", "metric": "deposits_count", "target": 1,
     "reward": 150, "xp": 25},
    {"key": "duel_win_1", "icon": "⚔️", "title": "Первая дуэль",
     "desc": "Выиграть дуэль 1×1", "metric": "duels_won", "target": 1,
     "reward": 300, "xp": 50},
    {"key": "invite_3", "icon": "👥", "title": "Три друга",
     "desc": "Пригласить трёх друзей", "metric": "referrals", "target": 3,
     "reward": 300, "xp": 40},
    {"key": "spin_7", "icon": "🎡", "title": "Неделя удачи",
     "desc": "Дойти до 7-го дня серии колеса", "metric": "spin_day", "target": 7,
     "reward": 500, "xp": 60},
)

SHOP_ITEMS = (
    {"key": "insurance", "title": "Страховка", "price": 120, "category": "items",
     "desc": "Возврат 25% ставки при проигрыше, максимум 200 mCoin"},
    {"key": "double_daily", "title": "Двойной бонус", "price": 250, "category": "items",
     "desc": "Следующий ежедневный бонус ×2"},
    {"key": "charm", "title": "Талисман удачи", "price": 350, "category": "items",
     "desc": "+10% к выплате на 5 выигрышей"},
    {"key": "relic_mines", "title": "Реликвия сапёра", "price": 4000, "category": "relics",
     "desc": "Навсегда +5% к выплатам в «Сапёре»"},
    {"key": "relic_dice", "title": "Кости судьбы", "price": 2500, "category": "relics",
     "desc": "Навсегда +5% к выплатам в «Костях»"},
    {"key": "relic_wheel", "title": "Колесо фортуны", "price": 3000, "category": "relics",
     "desc": "Навсегда +5% к выплатам в «Колесе»"},
    {"key": "relic_crash", "title": "Краш-модуль", "price": 3000, "category": "relics",
     "desc": "Навсегда +5% к выплатам в «Краше»"},
    {"key": "theme_neon", "title": "Неоновая тема", "price": 1500, "category": "cosmetics",
     "desc": "Бирюзовые акценты интерфейса"},
    {"key": "theme_gold", "title": "Золотые клетки", "price": 2000, "category": "cosmetics",
     "desc": "Золотая подсветка безопасных клеток"},
    {"key": "gold_pick", "title": "Золотая кирка", "price": 6000, "category": "relics",
     "desc": "Навсегда +3% к выплатам в «Сапёре»"},
    {"key": "lootbox", "title": "Кейс удачи", "price": 800, "category": "exclusive",
     "desc": "Случайная награда: mCoin, страховка или талисман"},
)

SHOP_BUNDLES = (
    {"key": "starter", "title": "Набор новичка", "price": 320, "category": "bundles",
     "desc": "Страховка и двойной бонус", "items": {"insurance": 1, "double_daily": 1}},
    {"key": "pro", "title": "Набор сапёра", "price": 520, "category": "bundles",
     "desc": "Талисман и две страховки", "items": {"charm": 1, "insurance": 2}},
    {"key": "relic_set", "title": "Набор реликвий", "price": 8000, "category": "bundles",
     "desc": "Реликвия сапёра и краш-модуль со скидкой",
     "items": {"relic_mines": 1, "relic_crash": 1}},
)

INSURANCE_REFUND = 0.25
INSURANCE_CAP = 200
CHARM_BONUS = 0.1
CHARM_CHARGES = 5

RELIC_BONUS = 0.05
GOLD_PICK_BONUS = 0.03
GAME_RELICS = {
    "mines": "relic_mines",
    "dice": "relic_dice",
    "wheel": "relic_wheel",
    "roulette": "relic_wheel",
    "crash": "relic_crash",
}

ROULETTE_RED = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})
ROULETTE_GREEN = 0


def roulette_number(server_seed: str, client_seed: str, nonce: int) -> int:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return min(36, int(value * 37))


def roulette_multiplier(number: int, pick: str) -> float:
    if pick == "green":
        return 36.0 if number == ROULETTE_GREEN else 0.0
    if number == ROULETTE_GREEN:
        return 0.0
    red = number in ROULETTE_RED
    if pick == "red" and red:
        return 2.0
    if pick == "black" and not red:
        return 2.0
    return 0.0


SLOT_SYMBOLS = (
    {"key": "cherry", "icon": "🍒", "weight": 30, "triple": 4.0},
    {"key": "lemon", "icon": "🍋", "weight": 25, "triple": 6.0},
    {"key": "bell", "icon": "🔔", "weight": 20, "triple": 10.0},
    {"key": "diamond", "icon": "💎", "weight": 12, "triple": 25.0},
    {"key": "seven", "icon": "7️⃣", "weight": 8, "triple": 60.0},
    {"key": "star", "icon": "⭐", "weight": 5, "triple": 200.0},
)
SLOT_PAIR = 1.2


def spin_slots(server_seed: str, client_seed: str, nonce: int) -> tuple[list[dict], float]:
    values = list(_floats(server_seed, client_seed, nonce, 0, 3))
    total = sum(symbol["weight"] for symbol in SLOT_SYMBOLS)
    reels = []
    for value in values:
        point = value * total
        acc = 0.0
        chosen = SLOT_SYMBOLS[-1]
        for symbol in SLOT_SYMBOLS:
            acc += symbol["weight"]
            if point < acc:
                chosen = symbol
                break
        reels.append(chosen)
    keys = [symbol["key"] for symbol in reels]
    if keys[0] == keys[1] == keys[2]:
        multiplier = next(symbol["triple"] for symbol in SLOT_SYMBOLS
                          if symbol["key"] == keys[0])
    elif keys[0] == keys[1] or keys[0] == keys[2] or keys[1] == keys[2]:
        multiplier = SLOT_PAIR
    else:
        multiplier = 0.0
    return reels, multiplier

CRASH_RTP = 0.99
CRASH_MIN = 1.2
CRASH_MAX = 10.0


def day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + DAY_OFFSET))


def day_start() -> int:
    shifted = time.time() + DAY_OFFSET
    return int(shifted - (shifted % 86400) - DAY_OFFSET)


def roll_dice(server_seed: str, client_seed: str, nonce: int) -> int:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return min(6, int(value * 6) + 1)


def spin_wheel(server_seed: str, client_seed: str, nonce: int) -> tuple[int, float]:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    total = sum(segment["weight"] for segment in WHEEL_SEGMENTS)
    point = value * total
    acc = 0.0
    for index, segment in enumerate(WHEEL_SEGMENTS):
        acc += segment["weight"]
        if point < acc:
            return index, segment["multiplier"]
    return len(WHEEL_SEGMENTS) - 1, WHEEL_SEGMENTS[-1]["multiplier"]


def spin_daily(server_seed: str, client_seed: str, nonce: int) -> tuple[int, dict]:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    total = sum(segment["weight"] for segment in DAILY_SPIN)
    point = value * total
    acc = 0.0
    for index, segment in enumerate(DAILY_SPIN):
        acc += segment["weight"]
        if point < acc:
            return index, segment
    return len(DAILY_SPIN) - 1, DAILY_SPIN[-1]


def crash_point(server_seed: str, client_seed: str, nonce: int) -> float:
    """Точка краша: P(точка ≥ m) = 0.99 / m, поэтому EV ставки равен 0.99."""
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    value = min(max(value, 1e-6), 0.999999)
    return max(1.0, math.floor((CRASH_RTP / value) * 100) / 100)


DEPOSIT_PLANS = (
    {"days": 1, "rate_bps": 15},
    {"days": 3, "rate_bps": 50},
    {"days": 7, "rate_bps": 120},
    {"days": 15, "rate_bps": 300},
    {"days": 30, "rate_bps": 700},
)
SAVINGS_RATE_BPS = 10
DEPOSIT_MIN = 100
DEPOSIT_MAX = 1_000_000


def deposit_interest(amount: int, rate_bps: int) -> int:
    return int(amount) * rate_bps // 10000


def savings_interest(amount: int, rate_bps: int, seconds: int) -> int:
    seconds = max(0, int(seconds))
    return int(amount) * rate_bps * seconds // (10000 * 86400)


COINFLIP_MULTIPLIER = 1.96


def coinflip(server_seed: str, client_seed: str, nonce: int) -> str:
    """«Орёл» (heads) и «решка» (tails) из HMAC-потока."""
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return "heads" if value < 0.5 else "tails"


def open_lootbox(server_seed: str, client_seed: str, nonce: int) -> dict:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    if value < 0.40:
        return {"kind": "coins", "amount": 200}
    if value < 0.70:
        return {"kind": "coins", "amount": 600}
    if value < 0.88:
        return {"kind": "coins", "amount": 1500}
    if value < 0.96:
        return {"kind": "coins", "amount": 3000}
    if value < 0.99:
        return {"kind": "item", "item": "insurance", "qty": 1}
    return {"kind": "item", "item": "charm", "qty": CHARM_CHARGES}


BJ_SUITS = ("♠", "♥", "♦", "♣")
BJ_RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
BJ_BLACKJACK = 2.5
BJ_TARGET = 21
BJ_DEALER_STANDS = 17


def bj_deck(server_seed: str, client_seed: str, nonce: int) -> list[dict]:
    """Перемешанная колода 52 карты: тот же HMAC-поток, что и в остальных играх."""
    deck = [{"rank": rank, "suit": suit} for suit in BJ_SUITS for rank in BJ_RANKS]
    for i in range(len(deck) - 1, 0, -1):
        r = next(_floats(server_seed, client_seed, nonce, i, 1))
        j = int(r * (i + 1))
        deck[i], deck[j] = deck[j], deck[i]
    return deck


def bj_rank_value(rank: str) -> int:
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def bj_value(cards: list[dict]) -> int:
    """Стоимость руки: тузы считаются 11, пока перебор, иначе 1."""
    total = sum(bj_rank_value(card["rank"]) for card in cards)
    aces = sum(1 for card in cards if card["rank"] == "A")
    while total > BJ_TARGET and aces:
        total -= 10
        aces -= 1
    return total


def bj_blackjack(cards: list[dict]) -> bool:
    return len(cards) == 2 and bj_value(cards) == BJ_TARGET


def bj_multiplier(player: list[dict], dealer: list[dict]) -> float:
    """0 — проигрыш, 1 — ничья, 2 — победа, 2.5 — блэкджек."""
    player_value = bj_value(player)
    dealer_value = bj_value(dealer)
    if player_value > BJ_TARGET:
        return 0.0
    if bj_blackjack(player) and not bj_blackjack(dealer):
        return BJ_BLACKJACK
    if dealer_value > BJ_TARGET:
        return 2.0
    if player_value > dealer_value:
        return 2.0
    if player_value == dealer_value:
        return 1.0
    return 0.0


def bj_dealer_play(deck: list[dict], dealer: list[dict]) -> list[dict]:
    """Дилер добирает до 17 включительно (мягкие 17 останавливают)."""
    dealer = list(dealer)
    index = len(dealer)
    while bj_value(dealer) < BJ_DEALER_STANDS and index < len(deck):
        dealer.append(deck[index])
        index += 1
    return dealer
