import hashlib
import hmac
import json
import math
import secrets
import time
import uuid
from urllib.parse import parse_qsl

from aiohttp import web

import game
from config import config
from db import Database


def parse_init_data(init_data: str, bot_token: str) -> dict | None:
    if not init_data:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    data = {}
    received_hash = ""
    for key, value in pairs:
        if key == "hash":
            received_hash = value
        else:
            data[key] = value
    if not received_hash:
        return None
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if auth_date and time.time() - auth_date > 48 * 3600:
        return None
    try:
        user = json.loads(data.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    if not user.get("id"):
        return None
    return user


class Api:
    def __init__(self, db: Database):
        self.db = db
        self._last_click: dict[int, float] = {}

    def _auth(self, request: web.Request) -> dict | None:
        init_data = request.headers.get("X-Init-Data", "")
        user = parse_init_data(init_data, config.bot_token) if config.bot_token else None
        if not user and config.dev_mode:
            user = {"id": config.dev_user_id or 1, "first_name": "Dev", "username": "dev"}
        if not user:
            return None
        referrer = None
        start_param = request.headers.get("X-Start-Param", "")
        if start_param.startswith("ref_"):
            try:
                referrer = int(start_param[4:])
            except ValueError:
                referrer = None
        return self.db.ensure_user(
            user["id"], user.get("username"), user.get("first_name"), referrer)

    @staticmethod
    def _json(data: dict, status: int = 200) -> web.Response:
        return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False))

    def _fail(self, message: str, status: int = 400) -> web.Response:
        return self._json({"ok": False, "error": message}, status)

    @staticmethod
    def _is_admin(user: dict) -> bool:
        if user["user_id"] in config.admin_ids:
            return True
        username = (user.get("username") or "").lower()
        return bool(username) and username in config.admin_usernames

    def _require_admin(self, request: web.Request):
        user = self._auth(request)
        if not user:
            return None, self._fail("unauthorized", 401)
        if not self._is_admin(user):
            return None, self._fail("Недостаточно прав", 403)
        return user, None

    def _settings(self) -> dict:
        return self.db.settings()

    def _public_settings(self) -> dict:
        raw = self._settings()
        return {
            "min_bet": raw.get("min_bet", 10),
            "max_bet": raw.get("max_bet", 100000),
            "min_mines": raw.get("min_mines", 1),
            "max_mines": raw.get("max_mines", 24),
            "daily_bonus": raw.get("daily_bonus", 500),
            "maintenance": raw.get("maintenance", 0),
        }

    def _public_user(self, user: dict) -> dict:
        now = int(time.time())
        cooldown_left = max(0, user["last_daily"] + game.DAILY_COOLDOWN - now)
        return {
            "id": user["user_id"],
            "username": user["username"],
            "first_name": user["first_name"],
            "balance": user["balance"],
            "games_played": user["games_played"],
            "games_won": user["games_won"],
            "total_wagered": user["total_wagered"],
            "total_won": user["total_won"],
            "best_multiplier": user["best_multiplier"],
            "daily_ready": cooldown_left == 0,
            "daily_in": cooldown_left,
            "daily_amount": int(self._settings().get("daily_bonus", game.DAILY_BONUS)),
            "ref_code": f"ref_{user['user_id']}",
        }

    async def state(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        active = self.db.active_round(user["user_id"])
        payload = {
            "ok": True,
            "user": self._public_user(user),
            "bot_username": config.bot_username,
            "is_admin": self._is_admin(user),
            "settings": self._public_settings(),
            "rank": self.db.rank(user["user_id"]),
            "referrals": self.db.referrals(user["user_id"]),
            "leaderboard": self.db.leaderboard(10),
            "history": self.db.history(user["user_id"], 10),
            "fair": {
                "seed_hash": user["server_seed_hash"],
                "client_seed": user["client_seed"],
                "nonce": user["nonce"],
            },
            "quests": self._quests_view(user),
            "inventory": self._inventory_view(user),
            "active_round": None,
        }
        if active:
            payload["active_round"] = self._round_view(active, user, reveal=False)
        return self._json(payload)

    def _round_view(self, rnd: dict, user: dict, reveal: bool) -> dict:
        mines = rnd["mine_positions"]
        data = {
            "id": rnd["id"],
            "bet": rnd["bet"],
            "mines": rnd["mines"],
            "opened": rnd["opened"],
            "multiplier": rnd["multiplier"],
            "status": rnd["status"],
            "payout": rnd["payout"],
            "next_chance": game.next_chance(rnd["mines"], len(rnd["opened"])),
            "max_multiplier": game.max_multiplier(rnd["mines"]),
            "ladder": game.ladder(rnd["mines"], len(rnd["opened"])),
        }
        if reveal or rnd["status"] != "active":
            data["mine_positions"] = mines
        return data

    async def start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return self._fail("bad json")

        try:
            bet = int(body.get("bet", 0))
            mines = int(body.get("mines", 3))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")

        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)

        settings = self._settings()
        if int(settings.get("maintenance", 0)) and not self._is_admin(user):
            return self._fail("Идут технические работы — игра скоро вернётся")

        min_bet = int(settings.get("min_bet", game.MIN_BET))
        max_bet = int(settings.get("max_bet", game.MAX_BET))
        min_mines = int(settings.get("min_mines", 1))
        max_mines = int(settings.get("max_mines", 24))

        if not (min_bet <= bet <= max_bet):
            return self._fail(f"Ставка от {min_bet} до {max_bet}")
        if not (min_mines <= mines <= max_mines):
            return self._fail(f"Мин от {min_mines} до {max_mines}")
        if self.db.active_round(user["user_id"]):
            return self._fail("Сначала завершите текущую игру")
        if user["balance"] < bet:
            return self._fail("Недостаточно средств")

        nonce = self.db.bump_nonce(user["user_id"])
        positions = game.generate_mines(
            user["server_seed"], user["client_seed"], nonce, mines)
        round_id = uuid.uuid4().hex[:16]
        balance = self.db.add_balance(user["user_id"], -bet)
        self.db.create_round(round_id, user["user_id"], bet, mines, positions,
                             user["server_seed"], user["client_seed"], nonce)
        return self._json({
            "ok": True,
            "round": {
                "id": round_id,
                "bet": bet,
                "mines": mines,
                "opened": [],
                "multiplier": 1.0,
                "payout": 0,
                "status": "active",
                "next_chance": game.next_chance(mines, 0),
                "max_multiplier": game.max_multiplier(mines),
                "ladder": game.ladder(mines, 0),
            },
            "balance": balance,
        })

    async def open(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = time.time()
        if now - self._last_click.get(user["user_id"], 0) < 0.08:
            return self._fail("Слишком быстро")
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return self._fail("bad json")
        rnd = self.db.active_round(user["user_id"])
        if not rnd:
            return self._fail("Активной игры нет")
        try:
            cell = int(body.get("cell", -1))
        except (TypeError, ValueError):
            return self._fail("Некорректная клетка")
        if not (0 <= cell < game.CELLS):
            return self._fail("Некорректная клетка")
        if cell in rnd["opened"]:
            return self._fail("Клетка уже открыта")
        self._last_click[user["user_id"]] = now

        if cell in rnd["mine_positions"]:
            self.db.update_round(rnd["id"], rnd["opened"], rnd["multiplier"], "lost", 0)
            self.db.finish_stats(user["user_id"], rnd["bet"], 0, 0)
            refund = self._insurance_refund(user, rnd["bet"])
            self._settle_referral(user["user_id"])
            return self._json({
                "ok": True,
                "lost": True,
                "cell": cell,
                "mine_positions": rnd["mine_positions"],
                "multiplier": rnd["multiplier"],
                "refund": refund,
                "balance": self.db.user(user["user_id"])["balance"],
                "status": "lost",
            })

        opened = rnd["opened"] + [cell]
        mult = game.multiplier(rnd["mines"], len(opened))
        safe = game.CELLS - rnd["mines"]
        finished = len(opened) >= safe
        payout = game.payout_for(rnd["bet"], mult) if finished else 0
        if finished:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "mines", payout)
        status = "won" if finished else "active"
        self.db.update_round(rnd["id"], opened, mult, status, payout)

        balance = self.db.user(user["user_id"])["balance"]
        if finished:
            balance = self.db.add_balance(user["user_id"], payout)
            self.db.finish_stats(user["user_id"], rnd["bet"], payout, mult)
            self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "lost": False,
            "cell": cell,
            "opened": opened,
            "multiplier": mult,
            "payout": payout,
            "finished": finished,
            "status": status,
            "next_chance": game.next_chance(rnd["mines"], len(opened)),
            "ladder": game.ladder(rnd["mines"], len(opened)),
            "mine_positions": rnd["mine_positions"] if finished else None,
            "balance": balance,
        })

    async def cashout(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        rnd = self.db.active_round(user["user_id"])
        if not rnd:
            return self._fail("Активной игры нет")
        if not rnd["opened"]:
            return self._fail("Откройте хотя бы одну клетку")
        mult = game.multiplier(rnd["mines"], len(rnd["opened"]))
        payout = game.payout_for(rnd["bet"], mult)
        payout = self._charm_bonus(user, payout)
        payout = self._apply_relic(user, "mines", payout)
        self.db.update_round(rnd["id"], rnd["opened"], mult, "cashed", payout)
        balance = self.db.add_balance(user["user_id"], payout)
        self.db.finish_stats(user["user_id"], rnd["bet"], payout, mult)
        self._settle_referral(user["user_id"])
        return self._json({
            "ok": True,
            "multiplier": mult,
            "payout": payout,
            "balance": balance,
            "mine_positions": rnd["mine_positions"],
            "status": "cashed",
        })

    def _settle_referral(self, user_id: int) -> None:
        self.db.claim_referral_bonus(user_id)

    async def daily(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        now = int(time.time())
        if now - user["last_daily"] < game.DAILY_COOLDOWN:
            left = user["last_daily"] + game.DAILY_COOLDOWN - now
            return self._fail(f"Бонус будет доступен через {left // 3600} ч")
        bonus = int(self._settings().get("daily_bonus", game.DAILY_BONUS))
        doubled = self.db.take_item(user["user_id"], "double_daily")
        if doubled:
            bonus *= 2
        self.db._exec("UPDATE users SET last_daily = ? WHERE user_id = ?",
                      (now, user["user_id"]))
        balance = self.db.add_balance(user["user_id"], bonus)
        return self._json({"ok": True, "amount": bonus, "doubled": doubled,
                           "balance": balance})

    async def history(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, "items": self.db.history(user["user_id"], 30)})

    async def leaderboard(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({
            "ok": True,
            "by_balance": self.db.leaderboard(20),
            "by_multiplier": self.db.top_multiplier(10),
            "me": user["user_id"],
        })

    async def fairness(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({
            "ok": True,
            "seed_hash": user["server_seed_hash"],
            "client_seed": user["client_seed"],
            "nonce": user["nonce"],
        })

    async def fairness_rotate(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        client_seed = str(body.get("client_seed") or "").strip()[:64]
        if client_seed and not client_seed.isalnum() and not all(
                c.isalnum() or c in "-_" for c in client_seed):
            return self._fail("Клиентский seed: только буквы, цифры, - и _")
        new_seed = secrets.token_hex(32)
        new_client = client_seed or secrets.token_hex(8)
        self.db.rotate_seed(user["user_id"], new_seed, game.hash_seed(new_seed), new_client)
        return self._json({
            "ok": True,
            "revealed_server_seed": user["server_seed"],
            "revealed_hash": user["server_seed_hash"],
            "previous_client_seed": user["client_seed"],
            "previous_nonce": user["nonce"],
            "seed_hash": game.hash_seed(new_seed),
            "client_seed": new_client,
            "nonce": 0,
        })

    async def verify_round(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return self._fail("bad json")
        round_id = str(body.get("round_id", ""))
        rnd = self.db.round(round_id)
        if not rnd or rnd["user_id"] != user["user_id"]:
            return self._fail("Раунд не найден", 404)
        ok = game.verify(rnd["server_seed"], rnd["client_seed"], rnd["nonce"],
                         rnd["mine_positions"], rnd["mines"])
        return self._json({
            "ok": True,
            "verified": ok,
            "server_seed": rnd["server_seed"],
            "server_seed_hash": game.hash_seed(rnd["server_seed"]),
            "client_seed": rnd["client_seed"],
            "nonce": rnd["nonce"],
            "mine_positions": rnd["mine_positions"],
            "mines": rnd["mines"],
        })

    # --- другие игры -----------------------------------------------------
    def _bet_error(self, user: dict, bet: int) -> str | None:
        if user.get("is_banned"):
            return "Аккаунт заблокирован"
        settings = self._settings()
        if int(settings.get("maintenance", 0)) and not self._is_admin(user):
            return "Идут технические работы — игра скоро вернётся"
        min_bet = int(settings.get("min_bet", game.MIN_BET))
        max_bet = int(settings.get("max_bet", game.MAX_BET))
        if not (min_bet <= bet <= max_bet):
            return f"Ставка от {min_bet} до {max_bet}"
        if user["balance"] < bet:
            return "Недостаточно средств"
        return None

    async def dice(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        pick = str(body.get("pick", "even")).lower()
        if pick not in ("even", "odd"):
            return self._fail("Выберите «чёт» или «нечёт»")
        error = self._bet_error(user, bet)
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        roll = game.roll_dice(user["server_seed"], user["client_seed"], nonce)
        is_even = roll % 2 == 0
        win = is_even if pick == "even" else not is_even
        multiplier = game.DICE_MULTIPLIER if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "dice", payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "dice", bet, win, payout,
                         {"roll": roll, "pick": pick, "nonce": nonce})
        self.db.finish_stats(user["user_id"], bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "roll": roll,
            "pick": pick,
            "win": win,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "quests": self._quests_view(user),
        })

    async def wheel(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        error = self._bet_error(user, bet)
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        index, multiplier = game.spin_wheel(user["server_seed"], user["client_seed"], nonce)
        payout = int(math.floor(bet * multiplier)) if multiplier > 0 else 0
        refund = 0
        if multiplier > 0:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "wheel", payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "wheel", bet,
                         multiplier > 0, payout, {"segment": index, "nonce": nonce})
        self.db.finish_stats(user["user_id"], bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "segment": index,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "segments": game.WHEEL_SEGMENTS,
            "quests": self._quests_view(user),
        })

    # --- квесты ----------------------------------------------------------
    def _quests_view(self, user: dict) -> list[dict]:
        day = game.day_key()
        stats = self.db.day_stats(user["user_id"], game.day_start())
        claimed = self.db.claimed_quests(user["user_id"], day)
        items = []
        for quest in game.DAILY_QUESTS:
            progress = min(quest["target"], int(stats.get(quest["metric"], 0)))
            items.append({
                "key": quest["key"],
                "title": quest["title"],
                "target": quest["target"],
                "reward": quest["reward"],
                "progress": progress,
                "ready": progress >= quest["target"] and quest["key"] not in claimed,
                "claimed": quest["key"] in claimed,
            })
        return items

    async def quests(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, "day": game.day_key(),
                           "items": self._quests_view(user)})

    async def quest_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        quest = next((q for q in game.DAILY_QUESTS if q["key"] == key), None)
        if not quest:
            return self._fail("Неизвестное задание", 404)
        stats = self.db.day_stats(user["user_id"], game.day_start())
        if int(stats.get(quest["metric"], 0)) < quest["target"]:
            return self._fail("Задание ещё не выполнено")
        if not self.db.claim_quest(user["user_id"], game.day_key(), key):
            return self._fail("Награда уже получена")
        balance = self.db.add_balance(user["user_id"], quest["reward"])
        return self._json({"ok": True, "reward": quest["reward"], "balance": balance,
                           "quests": self._quests_view(user)})

    # --- магазин ---------------------------------------------------------
    def _inventory_view(self, user: dict) -> dict:
        inv = self.db.inventory(user["user_id"])
        keys = {item["key"] for item in game.SHOP_ITEMS}
        keys.update({"insurance", "double_daily", "charm"})
        return {key: int(inv.get(key, 0)) for key in sorted(keys)}

    def _insurance_refund(self, user: dict, bet: int) -> int:
        if not self.db.take_item(user["user_id"], "insurance"):
            return 0
        refund = min(int(bet * game.INSURANCE_REFUND), game.INSURANCE_CAP)
        if refund > 0:
            self.db.add_balance(user["user_id"], refund)
        return refund

    def _charm_bonus(self, user: dict, payout: int) -> int:
        if payout <= 0:
            return payout
        if not self.db.take_item(user["user_id"], "charm"):
            return payout
        extra = int(payout * game.CHARM_BONUS)
        if extra <= 0:
            return payout
        self.db.add_balance(user["user_id"], extra)
        return payout + extra

    def _apply_relic(self, user: dict, game_key: str, payout: int) -> int:
        if payout <= 0:
            return payout
        relic = game.GAME_RELICS.get(game_key)
        if not relic or self.db.item_qty(user["user_id"], relic) <= 0:
            return payout
        bonus = int(payout * game.RELIC_BONUS)
        if bonus <= 0:
            return payout
        self.db.add_balance(user["user_id"], bonus)
        return payout + bonus

    async def crash(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
            target = float(body.get("target", 2.0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        if not (game.CRASH_MIN <= target <= game.CRASH_MAX):
            return self._fail(f"Множитель от {game.CRASH_MIN} до {game.CRASH_MAX}")
        error = self._bet_error(user, bet)
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        point = game.crash_point(user["server_seed"], user["client_seed"], nonce)
        win = point >= target
        multiplier = target if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "crash", payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "crash", bet, win, payout,
                         {"point": point, "target": target, "nonce": nonce})
        self.db.finish_stats(user["user_id"], bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "point": point,
            "target": target,
            "win": win,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "quests": self._quests_view(user),
        })

    async def shop(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        inv = self.db.inventory(user["user_id"])
        items = []
        for item in game.SHOP_ITEMS:
            entry = dict(item)
            entry["owned"] = inv.get(item["key"], 0) > 0
            items.append(entry)
        bundles = []
        for bundle in game.SHOP_BUNDLES:
            entry = dict(bundle)
            entry["owned"] = all(inv.get(key, 0) > 0 for key in bundle["items"])
            bundles.append(entry)
        return self._json({
            "ok": True,
            "balance": user["balance"],
            "inventory": self._inventory_view(user),
            "items": items,
            "bundles": bundles,
        })

    async def shop_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        entry = next((item for item in game.SHOP_ITEMS if item["key"] == key), None)
        grant = {key: 1} if entry else None
        if entry is None:
            bundle = next((b for b in game.SHOP_BUNDLES if b["key"] == key), None)
            if not bundle:
                return self._fail("Товар не найден", 404)
            entry = bundle
            grant = dict(bundle["items"])
        price = int(entry["price"])
        unique = {"relic_mines", "relic_dice", "relic_wheel", "relic_crash",
                  "theme_neon", "theme_gold"}
        for item_key in (grant or {}):
            if item_key in unique and self.db.item_qty(user["user_id"], item_key) > 0:
                return self._fail("Этот предмет уже куплен")
        if user["balance"] < price:
            return self._fail("Недостаточно сапов")
        balance = self.db.add_balance(user["user_id"], -price)
        for item_key, qty in (grant or {}).items():
            if item_key == "charm":
                qty *= game.CHARM_CHARGES
            self.db.add_item(user["user_id"], item_key, qty)
        return self._json({
            "ok": True,
            "balance": balance,
            "inventory": self._inventory_view(user),
            "bought": entry["title"],
        })

    # --- admin -----------------------------------------------------------
    @staticmethod
    async def _body(request: web.Request) -> dict:
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    async def admin_overview(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        return self._json({
            "ok": True,
            "stats": self.db.admin_stats(),
            "settings": self._public_settings(),
            "recent": self.db.admin_recent(12),
        })

    async def admin_users(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        query = str(body.get("query", ""))[:64]
        try:
            limit = int(body.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        return self._json({"ok": True, "items": self.db.admin_users(query, limit)})

    async def admin_balance(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        try:
            target = int(body.get("user_id", 0))
            value = int(body.get("value", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректные данные")
        if not self.db.user(target):
            return self._fail("Игрок не найден", 404)
        if str(body.get("mode", "set")) == "grant":
            balance = self.db.add_balance(target, value)
        else:
            balance = self.db.admin_set_balance(target, value)
        return self._json({"ok": True, "user_id": target, "balance": balance})

    async def admin_ban(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        try:
            target = int(body.get("user_id", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректные данные")
        if not self.db.user(target):
            return self._fail("Игрок не найден", 404)
        if target == admin["user_id"]:
            return self._fail("Себя блокировать не нужно")
        banned = bool(body.get("banned", True))
        self.db.admin_set_ban(target, banned)
        return self._json({"ok": True, "user_id": target, "is_banned": 1 if banned else 0})

    async def admin_rounds(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        try:
            user_id = int(body["user_id"]) if body.get("user_id") else None
        except (TypeError, ValueError):
            user_id = None
        try:
            limit = int(body.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(100, limit))
        return self._json({"ok": True, "items": self.db.admin_rounds(user_id, limit)})

    async def admin_settings(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        allowed = ("min_bet", "max_bet", "min_mines", "max_mines",
                   "daily_bonus", "maintenance")
        updates: dict[str, int] = {}
        for key in allowed:
            if key not in body:
                continue
            try:
                updates[key] = int(body[key])
            except (TypeError, ValueError):
                return self._fail(f"Некорректное значение: {key}")
        if not updates:
            return self._fail("Нет изменений")

        current = self._settings()
        merged = {**current, **updates}
        if merged["min_bet"] < 1 or merged["min_bet"] > merged["max_bet"]:
            return self._fail("Проверьте границы ставки")
        if merged["max_bet"] > 10_000_000:
            return self._fail("Слишком большой максимум ставки")
        if merged["min_mines"] < 1 or merged["min_mines"] > merged["max_mines"]:
            return self._fail("Проверьте число мин")
        if merged["max_mines"] > 24:
            return self._fail("Мин не больше 24")
        if merged["daily_bonus"] < 0 or merged["daily_bonus"] > 1_000_000:
            return self._fail("Некорректный ежедневный бонус")
        if merged["maintenance"] not in (0, 1):
            return self._fail("Техработы: 0 или 1")

        saved = self.db.set_settings(updates)
        return self._json({"ok": True, "settings": saved})


def build_app(db: Database) -> web.Application:
    api = Api(db)
    app = web.Application(client_max_size=64 * 1024)
    app["api"] = api

    app.router.add_post("/api/state", api.state)
    app.router.add_post("/api/game/start", api.start)
    app.router.add_post("/api/game/open", api.open)
    app.router.add_post("/api/game/cashout", api.cashout)
    app.router.add_post("/api/daily", api.daily)
    app.router.add_post("/api/history", api.history)
    app.router.add_post("/api/leaderboard", api.leaderboard)
    app.router.add_post("/api/fairness", api.fairness)
    app.router.add_post("/api/fairness/rotate", api.fairness_rotate)
    app.router.add_post("/api/fairness/verify", api.verify_round)
    app.router.add_post("/api/games/dice", api.dice)
    app.router.add_post("/api/games/wheel", api.wheel)
    app.router.add_post("/api/games/crash", api.crash)
    app.router.add_post("/api/quests", api.quests)
    app.router.add_post("/api/quests/claim", api.quest_claim)
    app.router.add_post("/api/shop", api.shop)
    app.router.add_post("/api/shop/buy", api.shop_buy)
    app.router.add_post("/api/admin/overview", api.admin_overview)
    app.router.add_post("/api/admin/users", api.admin_users)
    app.router.add_post("/api/admin/balance", api.admin_balance)
    app.router.add_post("/api/admin/ban", api.admin_ban)
    app.router.add_post("/api/admin/rounds", api.admin_rounds)
    app.router.add_post("/api/admin/settings", api.admin_settings)

    here = __import__("os").path.dirname(__file__)
    web_dir = __import__("os").path.join(here, "web")
    if not __import__("os").path.isdir(web_dir):
        web_dir = here

    async def index(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(__import__("os").path.join(web_dir, "index.html"))

    app.router.add_get("/", index)
    app.router.add_static("/static/", web_dir, show_index=False)
    return app
