import hashlib
import hmac
import math
import time

CELLS = 25
SIDE = 5
RTP = 0.92
MIN_BET = 10
MAX_BET = 100_000_000
START_BALANCE = 1000
REGISTER_BONUS = 1000
DAILY_BONUS = 1000
DAILY_COOLDOWN = 24 * 60 * 60
HOURLY_BONUS = 500
HOURLY_COOLDOWN = 60 * 60
REF_BONUS = 500
REF_GAMES_REQUIRED = 5
REF_WIN_SHARE = 0.05

# Зависшая партия «Сапёр» авто-закрывается с возвратом ставки.
ROUND_TTL = 30 * 60

XP_PER_GAME = 7
XP_PER_WIN = 10
XP_PER_DUEL_WIN = 30

LEVEL_TITLES = (
    (1, "Новобранец"),
    (3, "Сапёр"),
    (5, "Старшина"),
    (8, "Ветеран"),
    (12, "Мастер"),
    (18, "Легенда"),
    (25, "Гроссмейстер"),
)

GMPOINT_NAME = "GMPOINT"
GMPOINT_ICON = "G"

PREFIXES = (
    {"key": "novice", "title": "Новобранец", "price": 0, "currency": "mcoin",
     "level": 1, "color": "#9aa4b2"},
    {"key": "saper", "title": "Сапёр", "price": 1500, "currency": "mcoin",
     "level": 3, "color": "#2ee6a8"},
    {"key": "veteran", "title": "Ветеран", "price": 5000, "currency": "mcoin",
     "level": 8, "color": "#7c5cff"},
    {"key": "legend", "title": "Легенда", "price": 25, "currency": "gmpoint",
     "level": 18, "color": "#ffb020"},
    {"key": "gmpoint", "title": "GMPOINT", "price": 50, "currency": "gmpoint",
     "level": 1, "color": "#ffd166"},
    {"key": "april", "title": "Апрель", "price": 100, "currency": "gmpoint",
     "level": 25, "color": "#ff5c8a"},
    {"key": "king", "title": "Король сапёров", "price": 250, "currency": "gmpoint",
     "level": 40, "color": "#f7c948"},
    {"key": "sapper_10", "title": "Взрывотехник", "price": 0, "currency": "level",
     "level": 10, "color": "#57c7ff"},
    {"key": "master_25", "title": "Гроссмейстер", "price": 0, "currency": "level",
     "level": 25, "color": "#c084fc"},
    {"key": "immortal_50", "title": "Бессмертный", "price": 0, "currency": "level",
     "level": 50, "color": "#ff6b6b"},
    {"key": "dracula", "title": "Дракула", "price": 15, "currency": "gmpoint",
     "level": 1, "color": "#e11d48", "bonus": 0.05,
     "desc": "+5% к выигрышу во всех играх"},
    {"key": "owner", "title": "Владелец", "price": 0, "currency": "role",
     "level": 1, "color": "#ff3b30", "role": "owner", "bonus": 0.10,
     "desc": "+10% к выигрышу · только для владельца"},
    {"key": "admin_prefix", "title": "Админ", "price": 0, "currency": "role",
     "level": 1, "color": "#ff9500", "role": "admin", "bonus": 0.07,
     "desc": "+7% к выигрышу · только для админа"},
    {"key": "moderator_prefix", "title": "Модератор", "price": 0, "currency": "role",
     "level": 1, "color": "#34c759", "role": "moderator", "bonus": 0.05,
     "desc": "+5% к выигрышу · только для модератора"},
    {"key": "tester_prefix", "title": "Тестер", "price": 0, "currency": "role",
     "level": 1, "color": "#64d2ff", "role": "tester", "bonus": 0.03,
     "desc": "+3% к выигрышу · только для тестера"},
    # --- оформления ника: цветная обводка в профиле и топе --------------
    {"key": "red_glow", "title": "Алый", "price": 3000, "currency": "mcoin",
     "level": 3, "color": "#ff2d2d", "style": "glow",
     "desc": "Красная обводка и свечение ника"},
    {"key": "white_pure", "title": "Белый", "price": 4000, "currency": "mcoin",
     "level": 4, "color": "#ffffff", "style": "outline",
     "desc": "Строгая белая обводка"},
    {"key": "neon_cyan", "title": "Неон", "price": 6000, "currency": "mcoin",
     "level": 8, "color": "#19f9ff", "style": "neon",
     "desc": "Неоновая бирюзовая подсветка"},
    {"key": "rainbow", "title": "Радужный", "price": 12000, "currency": "mcoin",
     "level": 12, "color": "#ff5c8a", "color2": "#57c7ff", "style": "rainbow",
     "desc": "Переливающаяся радужная обводка"},
    {"key": "ice", "title": "Ледяной", "price": 5000, "currency": "mcoin",
     "level": 6, "color": "#8fdcff", "color2": "#3b82f6", "style": "gradient",
     "desc": "Холодный градиент от льда к синему"},
    {"key": "toxic", "title": "Токсичный", "price": 7000, "currency": "mcoin",
     "level": 10, "color": "#a3ff12", "style": "glow",
     "desc": "Кислотно-зелёное свечение"},
    {"key": "sunset", "title": "Закат", "price": 9000, "currency": "mcoin",
     "level": 15, "color": "#ff9a3c", "color2": "#ff2d6f", "style": "gradient",
     "desc": "Тёплый градиент заката"},
    {"key": "gold_dust", "title": "Золотая пыль", "price": 15000, "currency": "mcoin",
     "level": 20, "color": "#ffd166", "style": "sparkle",
     "desc": "Золотая обводка с искрами"},
)

PREFIX_BY_KEY = {prefix["key"]: prefix for prefix in PREFIXES}


def register_custom_prefixes(custom: list[dict]) -> None:
    """Добавляет созданные админом префиксы в каталог."""
    for cp in custom:
        key = str(cp["key"] or "").strip()
        if not key:
            continue
        PREFIX_BY_KEY[key] = {
            "key": key,
            "title": str(cp.get("title") or key),
            "price": 0,
            "currency": "role",
            "level": 1,
            "color": str(cp.get("color") or "#ffd166"),
            "color2": str(cp.get("color2") or "") or None,
            "style": str(cp.get("style") or "solid"),
            "bonus": float(cp.get("bonus") or 0.0),
            "desc": f"+{round(float(cp.get('bonus') or 0.0) * 100)}% к выплате · кастомный",
        }

# Бонусы к выплатам для цветных префиксов: чем дороже префикс, тем выше бонус.
PREFIX_PAYOUT_BONUS = {
    "red_glow": 0.01,
    "white_pure": 0.015,
    "ice": 0.02,
    "neon_cyan": 0.025,
    "toxic": 0.03,
    "sunset": 0.035,
    "rainbow": 0.04,
    "gold_dust": 0.05,
}
for _prefix in PREFIXES:
    _bonus = PREFIX_PAYOUT_BONUS.get(_prefix["key"])
    if _bonus and not _prefix.get("bonus"):
        _prefix["bonus"] = _bonus
        _base = _prefix.get("desc") or ""
        _prefix["desc"] = f"+{round(_bonus * 100)}% к выплате" + (f" · {_base}" if _base else "")

# Оформления без бонуса к выигрышу: только внешний вид.
PREFIX_STYLES = ("solid", "outline", "glow", "neon", "gradient", "rainbow", "sparkle")


def prefix_bonus(key: str | None) -> float:
    prefix = PREFIX_BY_KEY.get((key or "").strip())
    if not prefix:
        return 0.0
    return float(prefix.get("bonus") or 0.0)


def prefix_style(key: str | None) -> str:
    prefix = PREFIX_BY_KEY.get((key or "").strip())
    style = (prefix or {}).get("style") or "solid"
    return style if style in PREFIX_STYLES else "solid"


def role_prefix(role: str | None) -> str:
    role = (role or "user").strip()
    for prefix in PREFIXES:
        if prefix.get("currency") == "role" and prefix.get("role") == role:
            return prefix["key"]
    return ""


def xp_for_level(level: int) -> int:
    """Сколько всего XP нужно, чтобы достичь уровня (крутая кривая)."""
    level = max(1, int(level))
    return 90 * (level - 1) * level


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


def prefix_view(key: str | None) -> dict | None:
    prefix = PREFIX_BY_KEY.get((key or "").strip())
    if not prefix:
        return None
    return {
        "key": prefix["key"],
        "title": prefix["title"],
        "color": prefix["color"],
        "color2": prefix.get("color2") or prefix["color"],
        "style": prefix_style(prefix["key"]),
        "bonus": float(prefix.get("bonus") or 0.0),
    }


def level_reward(level: int) -> dict:
    level = max(1, int(level))
    coins = 80 + (level - 1) * 35
    gmpoint = 5 if level % 15 == 0 else 0
    lootbox = 1 if level % 7 == 0 else 0
    prefix = next(
        (item["key"] for item in PREFIXES
         if item["currency"] == "level" and item["level"] == level),
        "",
    )
    return {
        "level": level,
        "coins": coins,
        "gmpoint": gmpoint,
        "lootbox": lootbox,
        "prefix": prefix,
    }


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


DICE_MULTIPLIER = 1.84

DUEL_RAKE = 0.05
DUEL_TTL = 10 * 60


def duel_roll(server_seed: str, client_seed: str, nonce: int) -> int:
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return min(100, int(value * 100) + 1)


def duel_prize(bet: int) -> int:
    return int(math.floor(int(bet) * 2 * (1 - DUEL_RAKE)))

WHEEL_SEGMENTS = (
    {"multiplier": 0.0, "weight": 38},
    {"multiplier": 1.1, "weight": 24},
    {"multiplier": 1.35, "weight": 16},
    {"multiplier": 1.7, "weight": 11},
    {"multiplier": 2.3, "weight": 7},
    {"multiplier": 3.2, "weight": 3},
)

DAY_OFFSET = 3 * 3600

# Прогрессивный ежедневный бонус: 1 000 в первый день, +1 000 за день серии.
DAILY_BASE = 1000
DAILY_STEP = 1000
DAILY_MAX = 30000
DAILY_STREAK_CAP = 30


def daily_bonus_for_streak(streak: int) -> int:
    """Сумма бонуса за день серии: 1 000 → 30 000."""
    streak = max(1, min(DAILY_STREAK_CAP, int(streak)))
    return min(DAILY_MAX, DAILY_BASE + (streak - 1) * DAILY_STEP)


def day_diff(today: str, previous: str) -> int:
    """Сколько дней между двумя ключами дат. При мусоре — большое число."""
    if not today or not previous:
        return 9999
    try:
        from datetime import date

        return (date.fromisoformat(today) - date.fromisoformat(previous)).days
    except (TypeError, ValueError):
        return 9999

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
    {"kind": "gmpoint", "amount": 1, "weight": 14},
    {"kind": "gmpoint", "amount": 3, "weight": 6},
    {"kind": "coins", "amount": 3000, "weight": 4},
    {"kind": "coins", "amount": 5000, "weight": 2},
    {"kind": "item", "item": "insurance", "weight": 60},
    {"kind": "item", "item": "charm", "weight": 30},
)

SPIN_COOLDOWN = 12 * 60 * 60
SPIN_STREAK_DAYS = 7

HOUR_QUESTS = (
    {"key": "h_games", "title": "Сыграй 5 партий за час", "metric": "games",
     "target": 5, "reward": 150},
    {"key": "h_win", "title": "Выиграй 2 партии за час", "metric": "wins",
     "target": 2, "reward": 200},
    {"key": "h_wager", "title": "Поставь 1000 mCoin за час", "metric": "wagered",
     "target": 1000, "reward": 250},
)


def hour_key() -> str:
    return time.strftime("%Y-%m-%d %H", time.gmtime(time.time() + DAY_OFFSET))


def hour_start() -> int:
    shifted = time.time() + DAY_OFFSET
    return int(shifted - (shifted % 3600) - DAY_OFFSET)


DAILY_QUESTS = (
    {"key": "games5", "title": "Сыграть 8 партий", "metric": "games", "target": 8, "reward": 300},
    {"key": "wins3", "title": "Выиграть 4 раза", "metric": "wins", "target": 4, "reward": 500},
    {"key": "wager1000", "title": "Поставить 2000 mCoin", "metric": "wagered", "target": 2000,
     "reward": 700},
    {"key": "games12", "title": "Сыграть 20 партий", "metric": "games", "target": 20,
     "reward": 1000},
    {"key": "gmp3", "title": "Выиграть 6 партий", "metric": "wins", "target": 6,
     "reward": 3, "currency": "gmpoint"},
    {"key": "gmp7", "title": "Поставить 6000 mCoin", "metric": "wagered", "target": 6000,
     "reward": 4, "currency": "gmpoint"},
)

_ACH_REWARDS = (1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, 20000,
                30000, 50000, 75000, 100000)

_ACH_CHAINS = (
    {"key": "games_played", "icon": "🎯", "title": "Партии",
     "metric": "games_played",
      "targets": (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
      "desc": "Сыграть {value} партий"},
    {"key": "games_won", "icon": "🏅", "title": "Победы",
     "metric": "games_won",
      "targets": (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500),
      "desc": "Выиграть {value} раз"},
    {"key": "total_wagered", "icon": "🎲", "title": "Оборот",
     "metric": "total_wagered",
     "targets": (100, 500, 1000, 5000, 10000, 50000, 100000, 500000,
                 1000000, 5000000),
     "desc": "Поставить {value} mCoin"},
    {"key": "balance", "icon": "💰", "title": "Баланс",
     "metric": "balance",
     "targets": (5000, 10000, 25000, 50000, 100000, 250000, 500000,
                 1000000),
     "desc": "Накопить {value} mCoin"},
    {"key": "best_multiplier", "icon": "🔥", "title": "Множитель",
     "metric": "best_multiplier",
     "targets": (2, 3, 5, 10, 25, 50, 100, 250),
     "desc": "Забрать выигрыш на множителе ×{value}"},
    {"key": "duels_won", "icon": "⚔️", "title": "Дуэли",
     "metric": "duels_won",
     "targets": (1, 3, 10, 30, 100),
     "desc": "Выиграть {value} дуэлей"},
    {"key": "referrals", "icon": "👥", "title": "Друзья",
     "metric": "referrals",
     "targets": (1, 3, 5, 10, 25, 50),
     "desc": "Пригласить {value} друзей"},
    {"key": "deposits_count", "icon": "🏦", "title": "Вклады",
     "metric": "deposits_count",
     "targets": (1, 3, 10, 25),
     "desc": "Открыть {value} вкладов"},
    {"key": "spin_day", "icon": "🎡", "title": "Серия колеса",
     "metric": "spin_day",
     "targets": (3, 7, 14, 30),
     "desc": "Дойти до {value}-го дня серии колеса"},
    {"key": "fish_count", "icon": "🐟", "title": "Улов",
     "metric": "fish_count",
     "targets": (1, 10, 50, 100, 500, 1000),
     "desc": "Поймать {value} рыб"},
    {"key": "fish_weight", "icon": "🐋", "title": "Трофей",
     "metric": "fish_weight",
      "targets": (5000, 20000, 100000, 250000, 500000),
      "desc": "Поймать рыбу весом {value} г"},
    {"key": "user_level", "icon": "⭐", "title": "Уровень",
     "metric": "user_level",
     "targets": (5, 10, 20, 30, 40, 50, 75, 100),
     "desc": "Достичь {value} уровня"},
    {"key": "daily_streak", "icon": "📅", "title": "Серия входов",
     "metric": "daily_streak",
     "targets": (3, 7, 14, 30),
     "desc": "Заходить {value} дней подряд"},
    {"key": "variety", "icon": "🧭", "title": "Разнообразие",
     "metric": "unique_games",
     "targets": (2, 3, 5, 7, 9),
     "desc": "Попробовать {value} разных игр"},
    {"key": "quests", "icon": "📋", "title": "Задания",
     "metric": "quests_claimed",
     "targets": (5, 15, 30, 60, 100),
     "desc": "Выполнить {value} заданий"},
    {"key": "collection", "icon": "🎒", "title": "Коллекция",
     "metric": "items_owned",
     "targets": (1, 5, 10, 20, 40),
     "desc": "Собрать {value} предметов"},
    {"key": "capital", "icon": "💎", "title": "Капитал",
     "metric": "balance",
     "targets": (2000000, 5000000, 10000000),
     "desc": "Накопить {value} mCoin"},
)


def _ach_display(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _achievement(chain: dict, target: int, index: int, levels: int) -> dict:
    value = _ach_display(target)
    metric = chain["metric"]
    if metric == "best_multiplier":
        title = f"{chain['title']} ×{target}"
    elif metric == "fish_weight":
        title = f"{chain['title']} {value} г"
    elif metric == "user_level":
        title = f"{chain['title']} {target}"
    else:
        title = f"{chain['title']} {value}"
    span = len(_ACH_REWARDS) - 1
    position = round(index / max(1, levels - 1) * span) if levels > 1 else 0
    return {
        "key": f"{chain['key']}_{target}",
        "icon": chain["icon"],
        "title": title,
        "desc": chain["desc"].format(value=value),
        "metric": metric,
        "target": target,
        "reward": int(_ACH_REWARDS[max(0, min(span, position))]),
        "xp": 20 + index * 15,
    }


ACHIEVEMENTS = tuple(
    _achievement(chain, target, index, len(chain["targets"]))
    for chain in _ACH_CHAINS
    for index, target in enumerate(chain["targets"])
)

ACHIEVEMENT_BY_KEY = {ach["key"]: ach for ach in ACHIEVEMENTS}
ACH_CHAINS = _ACH_CHAINS

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
    {"key": "boost_win", "title": "Буст выигрыша", "price": 2500, "category": "boosts",
     "charges": 10, "desc": "+5% к выплате. 10 зарядов — по одному на выигрыш"},
    {"key": "boost_loss", "title": "Кэшбэк-буст", "price": 3000, "category": "boosts",
     "charges": 10, "desc": "Возврат 5% ставки при проигрыше. 10 зарядов"},
)

BOOST_WIN_RATE = 0.05
BOOST_LOSS_RATE = 0.05
BOOST_CHARGES = 10

# Расходники: покупаются пачками зарядов, «куплено» для них не показываем.
CONSUMABLE_KEYS = frozenset({
    "insurance", "double_daily", "charm", "lootbox", "boost_win", "boost_loss",
})

# --- кастомизация профиля: аватарки и фоны ------------------------------
AVATARS = (
    {"key": "letter", "title": "Буква", "icon": "", "price": 0},
    {"key": "fox", "title": "Лис", "icon": "🦊", "price": 800},
    {"key": "wolf", "title": "Волк", "icon": "🐺", "price": 800},
    {"key": "tiger", "title": "Тигр", "icon": "🐯", "price": 1200},
    {"key": "lion", "title": "Лев", "icon": "🦁", "price": 1500},
    {"key": "frog", "title": "Жаба", "icon": "🐸", "price": 600},
    {"key": "panda", "title": "Панда", "icon": "🐼", "price": 1000},
    {"key": "owl", "title": "Сова", "icon": "🦉", "price": 1000},
    {"key": "octopus", "title": "Осьминог", "icon": "🐙", "price": 1200},
    {"key": "unicorn", "title": "Единорог", "icon": "🦄", "price": 3000},
    {"key": "alien", "title": "Пришелец", "icon": "👾", "price": 2500},
    {"key": "robot", "title": "Робот", "icon": "🤖", "price": 2000},
    {"key": "tophat", "title": "Цилиндр", "icon": "🎩", "price": 1800},
    {"key": "crown", "title": "Корона", "icon": "👑", "price": 5000},
    {"key": "diamond", "title": "Алмаз", "icon": "💎", "price": 6000},
    {"key": "fire", "title": "Огонь", "icon": "🔥", "price": 3500},
)

BACKGROUNDS = (
    {"key": "default", "title": "Стандарт", "price": 0,
     "css": "linear-gradient(135deg, #131722, #1e2533)"},
    {"key": "aurora", "title": "Аврора", "price": 2000,
     "css": "linear-gradient(135deg, #0f766e, #312e81 55%, #9d174d)"},
    {"key": "ocean", "title": "Океан", "price": 1500,
     "css": "linear-gradient(135deg, #0c4a6e, #0ea5e9)"},
    {"key": "sunset", "title": "Закат", "price": 1500,
     "css": "linear-gradient(135deg, #7c2d12, #f97316 60%, #ec4899)"},
    {"key": "matrix", "title": "Матрица", "price": 2500,
     "css": "linear-gradient(135deg, #00221a, #0b3d2e 60%, #16a34a)"},
    {"key": "gold", "title": "Золото", "price": 4000,
     "css": "linear-gradient(135deg, #4a2c07, #b7791f 60%, #facc15)"},
    {"key": "violet", "title": "Фиалка", "price": 3000,
     "css": "linear-gradient(135deg, #2e1065, #7c3aed 60%, #f472b6)"},
    {"key": "steel", "title": "Сталь", "price": 1000,
     "css": "linear-gradient(135deg, #111827, #4b5563)"},
)

AVATAR_BY_KEY = {item["key"]: item for item in AVATARS}
BACKGROUND_BY_KEY = {item["key"]: item for item in BACKGROUNDS}

# --- фоны игрового экрана: пейзажи и своё фото --------------------------
GAME_BACKGROUNDS = (
    {"key": "default", "title": "Стандарт", "price": 0, "file": ""},
    {"key": "forest", "title": "Лес", "price": 1500, "file": "bg_forest.jpg"},
    {"key": "mountains", "title": "Горы", "price": 2000, "file": "bg_mountains.jpg"},
    {"key": "ocean", "title": "Океан", "price": 1800, "file": "bg_ocean.jpg"},
    {"key": "desert", "title": "Пустыня", "price": 1600, "file": "bg_desert.jpg"},
    {"key": "night", "title": "Ночной город", "price": 2500, "file": "bg_night.jpg"},
    {"key": "aurora", "title": "Северное сияние", "price": 3000,
     "file": "bg_aurora.jpg"},
)

GAME_BACKGROUND_BY_KEY = {item["key"]: item for item in GAME_BACKGROUNDS}
CUSTOM_BG_KEY = "custom"
CUSTOM_BG_MAX_BYTES = 400_000
CUSTOM_BG_MIME = ("image/jpeg", "image/png", "image/webp")


def game_background_view(key: str | None) -> dict:
    key = (key or "").strip()
    if key == CUSTOM_BG_KEY:
        return {"key": CUSTOM_BG_KEY, "title": "Своё фото", "file": "", "price": 0}
    item = GAME_BACKGROUND_BY_KEY.get(key) or GAME_BACKGROUND_BY_KEY["default"]
    return {"key": item["key"], "title": item["title"],
            "file": item["file"], "price": item["price"]}

COSMETIC_PREFIX = {"avatar": "avatar_", "background": "bg_"}


def avatar_view(key: str | None) -> dict:
    key = (key or "").strip()
    if key == "custom":
        return {"key": "custom", "title": "Своё фото", "icon": ""}
    item = AVATAR_BY_KEY.get(key) or AVATAR_BY_KEY["letter"]
    return {"key": item["key"], "title": item["title"], "icon": item["icon"]}


def background_view(key: str | None) -> dict:
    item = BACKGROUND_BY_KEY.get((key or "").strip()) or BACKGROUND_BY_KEY["default"]
    return {"key": item["key"], "title": item["title"], "css": item["css"]}


def cosmetic_item_key(kind: str, key: str) -> str:
    return COSMETIC_PREFIX.get(kind, "") + (key or "").strip()


def cosmetic_from_inventory(kind: str, key: str | None) -> bool:
    """Бесплатные оформления считаются купленными всегда."""
    key = (key or "").strip()
    if kind == "avatar":
        return key in AVATAR_BY_KEY and int(AVATAR_BY_KEY[key]["price"]) == 0
    if kind == "background":
        return key in BACKGROUND_BY_KEY and int(BACKGROUND_BY_KEY[key]["price"]) == 0
    return False

SHOP_BUNDLES = (
    {"key": "starter", "title": "Набор новичка", "price": 320, "category": "bundles",
     "desc": "Страховка и двойной бонус", "items": {"insurance": 1, "double_daily": 1}},
    {"key": "pro", "title": "Набор сапёра", "price": 520, "category": "bundles",
     "desc": "Талисман и две страховки", "items": {"charm": 1, "insurance": 2}},
    {"key": "relic_set", "title": "Набор реликвий", "price": 8000, "category": "bundles",
     "desc": "Реликвия сапёра и краш-модуль со скидкой",
     "items": {"relic_mines": 1, "relic_crash": 1}},
    {"key": "boost_pack", "title": "Набор бустов", "price": 4500, "category": "bundles",
     "desc": "Пять бустов на выигрыш и пять на кэшбэк",
     "items": {"boost_win": 5, "boost_loss": 5}},
    {"key": "loot_pack", "title": "Ящик удачи", "price": 15000, "category": "bundles",
     "desc": "Десять кейсов удачи одним набором",
     "items": {"lootbox": 10}},
    {"key": "mega_bundle", "title": "Мега-набор", "price": 45000, "category": "bundles",
     "desc": "Реликвии, талисманы, кейсы и бусты — всё сразу",
     "items": {"relic_mines": 1, "relic_crash": 1, "charm": 3,
               "lootbox": 5, "boost_win": 3}},
    {"key": "whale_bundle", "title": "Набор магната", "price": 150000, "category": "bundles",
     "desc": "Для тех, кому девать mCoin уже некуда",
     "items": {"relic_mines": 1, "relic_crash": 1, "charm": 10,
               "lootbox": 25, "boost_win": 10, "boost_loss": 10}},
)

DONATE_ITEMS = (
    {"key": "gmp_lootbox", "title": "Премиум-кейс", "price": 20,
     "currency": "gmpoint", "category": "donate",
     "desc": "Пять кейсов удачи", "items": {"lootbox": 5}},
    {"key": "gmp_insurance", "title": "Золотая страховка", "price": 15,
     "currency": "gmpoint", "category": "donate",
     "desc": "Пять страховок", "items": {"insurance": 5}},
    {"key": "gmp_charm", "title": "Талисманы удачи", "price": 30,
     "currency": "gmpoint", "category": "donate",
     "desc": "Три талисмана по пять зарядов", "items": {"charm": 3}},
    {"key": "gmp_booster", "title": "Донат-бустер", "price": 40,
     "currency": "gmpoint", "category": "donate",
     "desc": "По десять бустов на выигрыш и кэшбэк",
     "items": {"boost_win": 10, "boost_loss": 10}},
    {"key": "gmp_mega_case", "title": "Мега-кейс", "price": 75,
     "currency": "gmpoint", "category": "donate",
     "desc": "Двадцать пять кейсов удачи", "items": {"lootbox": 25}},
    {"key": "gmp_daily", "title": "Донат-бонус", "price": 10,
     "currency": "gmpoint", "category": "donate",
     "desc": "Три двойных ежедневных бонуса",
     "items": {"double_daily": 3}},
    {"key": "gmp_relics", "title": "Набор реликвий", "price": 120,
     "currency": "gmpoint", "category": "donate",
     "desc": "Реликвии сапёра, костей, колеса и краша — всё сразу",
     "items": {"relic_mines": 1, "relic_dice": 1, "relic_wheel": 1,
               "relic_crash": 1}},
    {"key": "gmp_goldpick", "title": "Золотая кирка", "price": 50,
     "currency": "gmpoint", "category": "donate",
     "desc": "Навсегда +3% к выплатам в «Сапёре»",
     "items": {"gold_pick": 1}},
    {"key": "gmp_themes", "title": "Обе темы", "price": 35,
     "currency": "gmpoint", "category": "donate",
     "desc": "Неоновая тема и золотые клетки",
     "items": {"theme_neon": 1, "theme_gold": 1}},
)

# Картинки товаров (лежат в web/ и раздаются как /static/<файл>).
SHOP_ICONS = {
    "insurance": "shop_insurance.jpg",
    "double_daily": "shop_double_daily.jpg",
    "charm": "shop_charm.jpg",
    "relic_mines": "shop_relic_mines.jpg",
    "relic_dice": "shop_relic_dice.jpg",
    "relic_wheel": "shop_relic_wheel.jpg",
    "relic_crash": "shop_relic_crash.jpg",
    "theme_neon": "shop_theme_neon.jpg",
    "theme_gold": "shop_theme_gold.jpg",
    "gold_pick": "shop_gold_pick.jpg",
    "lootbox": "shop_lootbox.jpg",
    "boost_win": "",
    "boost_loss": "",
}
for _shop_item in SHOP_ITEMS:
    _shop_item["icon"] = SHOP_ICONS.get(_shop_item["key"], "")

INSURANCE_REFUND = 0.25
INSURANCE_CAP = 200
CHARM_BONUS = 0.1
CHARM_CHARGES = 5

# Продажа расходников: возврат 50% цены из магазина.
SELL_REFUND_RATE = 0.5


def sell_refund_price(item_key: str) -> int:
    """Сколько mCoin вернётся за продажу одного расходника."""
    for it in SHOP_ITEMS:
        if it["key"] == item_key and item_key in CONSUMABLE_KEYS:
            return max(1, int(int(it["price"]) * SELL_REFUND_RATE))
    return 0

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
        return 34.0 if number == ROULETTE_GREEN else 0.0
    if number == ROULETTE_GREEN:
        return 0.0
    red = number in ROULETTE_RED
    if pick == "red" and red:
        return 1.9
    if pick == "black" and not red:
        return 1.9
    return 0.0


SLOT_SYMBOLS = (
    {"key": "cherry", "icon": "🍒", "weight": 30, "triple": 3.8},
    {"key": "lemon", "icon": "🍋", "weight": 25, "triple": 5.6},
    {"key": "bell", "icon": "🔔", "weight": 20, "triple": 9.0},
    {"key": "diamond", "icon": "💎", "weight": 12, "triple": 23.0},
    {"key": "seven", "icon": "7️⃣", "weight": 8, "triple": 56.0},
    {"key": "star", "icon": "⭐", "weight": 5, "triple": 185.0},
)
SLOT_PAIR = 1.15


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

CRASH_RTP = 0.92
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
DEPOSIT_MAX = 100_000_000


def deposit_interest(amount: int, rate_bps: int) -> int:
    return int(amount) * rate_bps // 10000


def savings_interest(amount: int, rate_bps: int, seconds: int) -> int:
    seconds = max(0, int(seconds))
    return int(amount) * rate_bps * seconds // (10000 * 86400)


COINFLIP_MULTIPLIER = 1.84


def coinflip(server_seed: str, client_seed: str, nonce: int) -> str:
    """«Орёл» (heads) или «решка» (tails) из HMAC-потока."""
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return "heads" if value < 0.5 else "tails"


BASKET_CHANCE = 0.40
BASKET_MULTIPLIER = 2.3
BASKET_MISS_MULTIPLIER = 1.6
BASKET_SCORE_MIN = 4


def basket_shot(server_seed: str, client_seed: str, nonce: int) -> bool:
    """Бросок в кольцо: попадание с шансом 40%, выплата ×2,4."""
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return value < BASKET_CHANCE


# --- дартс: три исхода броска 🎯 ---------------------------------------
DARTS_SECTORS = (
    {"key": "miss", "title": "Мимо", "icon": "💨", "values": (1, 2),
     "multiplier": 2.4, "desc": "дротик уйдёт мимо мишени"},
    {"key": "sector", "title": "Сектор", "icon": "🎯", "values": (3, 4, 5),
     "multiplier": 1.88, "desc": "дротик попадёт в поле"},
    {"key": "bull", "title": "Яблочко", "icon": "🔴", "values": (6,),
     "multiplier": 5.5, "desc": "дротик попадёт в центр"},
)

DARTS_BY_KEY = {item["key"]: item for item in DARTS_SECTORS}
DARTS_MAX = 6


def dart_throw(server_seed: str, client_seed: str, nonce: int) -> int:
    """Значение броска 1–6: 6 — яблочко, 3–5 — сектор, 1–2 — мимо."""
    value = next(_floats(server_seed, client_seed, nonce, 0, 1))
    return min(DARTS_MAX, int(value * DARTS_MAX) + 1)


def darts_pick(key: str | None) -> dict | None:
    return DARTS_BY_KEY.get((key or "").strip())


def darts_lands(key: str | None, value: int) -> bool:
    pick = darts_pick(key)
    if not pick:
        return False
    return int(value) in pick["values"]


def darts_multiplier(key: str | None, value: int) -> float:
    pick = darts_pick(key)
    if not pick or not darts_lands(key, value):
        return 0.0
    return float(pick["multiplier"])


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


FISH_RARITY = (
    ("common", "Обычная", 0.55, (100, 700), "🐟"),
    ("rare", "Редкая", 0.25, (700, 1500), "🐠"),
    ("epic", "Эпическая", 0.12, (1500, 3000), "🐡"),
    ("mythic", "Мифическая", 0.06, (3000, 5000), "🦈"),
    ("legendary", "Легендарная", 0.02, (5000, 25000), "🐋"),
)

FISH_RARITY_MAP = {
    code: {"title": title, "chance": chance, "price": price, "icon": icon}
    for code, title, chance, price, icon in FISH_RARITY
}

FISH_SPECIES = (
    {"key": "crucian", "name": "Карась", "rarity": "common", "weight": (100, 900)},
    {"key": "perch", "name": "Окунь", "rarity": "common", "weight": (100, 1200)},
    {"key": "roach", "name": "Плотва", "rarity": "common", "weight": (100, 600)},
    {"key": "bream", "name": "Лещ", "rarity": "common", "weight": (300, 1500)},
    {"key": "pike", "name": "Щука", "rarity": "rare", "weight": (500, 4000)},
    {"key": "zander", "name": "Судак", "rarity": "rare", "weight": (700, 5000)},
    {"key": "carp", "name": "Карп", "rarity": "rare", "weight": (1000, 8000)},
    {"key": "catfish", "name": "Сом", "rarity": "epic", "weight": (3000, 20000)},
    {"key": "sturgeon", "name": "Осётр", "rarity": "epic", "weight": (5000, 30000)},
    {"key": "beluga", "name": "Белуга", "rarity": "mythic", "weight": (10000, 80000)},
    {"key": "swordfish", "name": "Меч-рыба", "rarity": "mythic",
     "weight": (20000, 120000)},
    {"key": "goldfish", "name": "Золотая рыбка", "rarity": "legendary",
     "weight": (100, 500)},
    {"key": "leviathan", "name": "Левиафан", "rarity": "legendary",
     "weight": (200000, 1000000)},
)

FISH_COOLDOWN = 4
FISH_CELLS = 25
FISH_GRAB_SECONDS = 3.0
FISH_LOCK_SECONDS = 15


def fish_cell(server_seed: str, client_seed: str, nonce: int) -> int:
    """Клетка 0..24, где покажется рыба."""
    value = next(_floats(server_seed, client_seed, nonce, 97, 1))
    return int(value * FISH_CELLS) % FISH_CELLS


# --- удочки: редкость, вес и удача -------------------------------------
RODS = (
    {"key": "bamboo", "title": "Бамбуковая", "price": 0, "rarity": 0.0,
     "weight": 0.0, "luck": 0.0, "icon": "🎣",
     "desc": "Стартовая удочка без бонусов"},
    {"key": "lucky", "title": "Удочка удачи", "price": 2500, "rarity": 0.10,
     "weight": 0.0, "luck": 0.05, "icon": "🍀",
     "desc": "+10% к шансу редкой рыбы · +5% к цене"},
    {"key": "heavy", "title": "Карповая", "price": 3000, "rarity": 0.0,
     "weight": 0.25, "luck": 0.0, "icon": "🎏",
     "desc": "+25% к весу рыбы"},
    {"key": "hunter", "title": "Хищник", "price": 4500, "rarity": 0.20,
     "weight": 0.10, "luck": 0.0, "icon": "🦈",
     "desc": "+20% к шансу редкости · +10% к весу"},
    {"key": "pro", "title": "Профи", "price": 8000, "rarity": 0.15,
     "weight": 0.20, "luck": 0.10, "icon": "🏆",
     "desc": "+15% редкость · +20% вес · +10% к цене"},
    {"key": "gold", "title": "Золотая", "price": 15000, "rarity": 0.30,
     "weight": 0.35, "luck": 0.15, "icon": "👑",
     "desc": "+30% редкость · +35% вес · +15% к цене"},
)

ROD_BY_KEY = {rod["key"]: rod for rod in RODS}
ROD_DEFAULT = "bamboo"


def rod_view(key: str | None) -> dict:
    rod = ROD_BY_KEY.get((key or "").strip()) or ROD_BY_KEY[ROD_DEFAULT]
    return dict(rod)


def fish_catch(server_seed: str, client_seed: str, nonce: int,
               rod: dict | None = None) -> dict:
    """Пойманная рыба: вид, редкость, вес и цена скупщика."""
    r1, r2, r3 = (next(_floats(server_seed, client_seed, nonce, i, 1))
                  for i in range(3))
    rarity_bonus = float((rod or {}).get("rarity") or 0.0)
    weight_bonus = float((rod or {}).get("weight") or 0.0)
    luck_bonus = float((rod or {}).get("luck") or 0.0)
    r1 = min(0.999, r1 + rarity_bonus)
    acc = 0.0
    rarity = "common"
    for code, _title, chance, _price, _icon in FISH_RARITY:
        acc += chance
        if r1 < acc:
            rarity = code
            break
    species = [item for item in FISH_SPECIES if item["rarity"] == rarity] or \
        [FISH_SPECIES[0]]
    sp = species[min(len(species) - 1, int(r2 * len(species)))]
    lo, hi = sp["weight"]
    fraction = min(1.0, r3 * (1 + weight_bonus))
    weight = int(lo + (hi - lo) * fraction)
    plo, phi = FISH_RARITY_MAP[rarity]["price"]
    share = min(1.0, (weight - lo) / max(1, hi - lo))
    price = int((plo + (phi - plo) * share) * (1 + luck_bonus))
    return {"key": sp["key"], "name": sp["name"], "rarity": rarity,
            "rarity_title": FISH_RARITY_MAP[rarity]["title"],
            "icon": FISH_RARITY_MAP[rarity]["icon"], "weight_g": weight,
            "price": max(1, price)}
