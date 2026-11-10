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
DAILY_BONUS = 500
DAILY_COOLDOWN = 24 * 60 * 60
REF_BONUS = 500
REF_GAMES_REQUIRED = 5


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

DAILY_QUESTS = (
    {"key": "games5", "title": "Сыграть 5 партий", "metric": "games", "target": 5, "reward": 300},
    {"key": "wins3", "title": "Выиграть 3 раза", "metric": "wins", "target": 3, "reward": 500},
    {"key": "wager1000", "title": "Поставить 1000 сапов", "metric": "wagered", "target": 1000,
     "reward": 700},
)

SHOP_ITEMS = (
    {"key": "insurance", "title": "Страховка", "price": 400,
     "desc": "Возвращает 50% ставки при следующем проигрыше"},
    {"key": "double_daily", "title": "Двойной бонус", "price": 600,
     "desc": "Следующий ежедневный бонус ×2"},
    {"key": "charm", "title": "Талисман удачи", "price": 900,
     "desc": "+10% к выплате на 5 выигрышей"},
)

SHOP_BUNDLES = (
    {"key": "starter", "title": "Набор новичка", "price": 1100,
     "desc": "2 страховки + двойной бонус",
     "items": {"insurance": 2, "double_daily": 1}},
    {"key": "pro", "title": "Набор сапёра", "price": 2000,
     "desc": "Талисман и 3 страховки",
     "items": {"charm": 1, "insurance": 3}},
)

INSURANCE_REFUND = 0.5
CHARM_BONUS = 0.1
CHARM_CHARGES = 5


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
