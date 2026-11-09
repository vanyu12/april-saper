import hashlib
import hmac
import json
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
            "daily_amount": game.DAILY_BONUS,
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
            "rank": self.db.rank(user["user_id"]),
            "referrals": self.db.referrals(user["user_id"]),
            "leaderboard": self.db.leaderboard(10),
            "history": self.db.history(user["user_id"], 10),
            "fair": {
                "seed_hash": user["server_seed_hash"],
                "client_seed": user["client_seed"],
                "nonce": user["nonce"],
            },
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

        if not (game.MIN_BET <= bet <= game.MAX_BET):
            return self._fail(f"Ставка от {game.MIN_BET} до {game.MAX_BET}")
        if not (1 <= mines <= 24):
            return self._fail("Мин от 1 до 24")
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
            self._settle_referral(user["user_id"])
            return self._json({
                "ok": True,
                "lost": True,
                "cell": cell,
                "mine_positions": rnd["mine_positions"],
                "multiplier": rnd["multiplier"],
                "balance": self.db.user(user["user_id"])["balance"],
                "status": "lost",
            })

        opened = rnd["opened"] + [cell]
        mult = game.multiplier(rnd["mines"], len(opened))
        safe = game.CELLS - rnd["mines"]
        finished = len(opened) >= safe
        payout = game.payout_for(rnd["bet"], mult) if finished else 0
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
        now = int(time.time())
        if now - user["last_daily"] < game.DAILY_COOLDOWN:
            left = user["last_daily"] + game.DAILY_COOLDOWN - now
            return self._fail(f"Бонус будет доступен через {left // 3600} ч")
        self.db._exec("UPDATE users SET last_daily = ? WHERE user_id = ?",
                      (now, user["user_id"]))
        balance = self.db.add_balance(user["user_id"], game.DAILY_BONUS)
        return self._json({"ok": True, "amount": game.DAILY_BONUS, "balance": balance})

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

    here = __import__("os").path.dirname(__file__)
    web_dir = __import__("os").path.join(here, "web")
    if not __import__("os").path.isdir(web_dir):
        web_dir = here

    async def index(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(__import__("os").path.join(web_dir, "index.html"))

    app.router.add_get("/", index)
    app.router.add_static("/static/", web_dir, show_index=False)
    return app
