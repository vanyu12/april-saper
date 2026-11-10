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
    {"key": "wager1000", "title": "Поставить 1000 сапов", "metric": "wagered", "target": 1000,
     "reward": 700},
)

SHOP_ITEMS = (
    {"key": "insurance", "title": "Страховка", "price": 120, "category": "items",
     "desc": "Возврат 25% ставки при проигрыше, максимум 200 сапов"},
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
GAME_RELICS = {
    "mines": "relic_mines",
    "dice": "relic_dice",
    "wheel": "relic_wheel",
    "crash": "relic_crash",
}

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
