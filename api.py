import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from urllib.parse import parse_qsl

import aiohttp
from aiohttp import web

import auth
import awards
import game
import updates
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
        self._last_action: dict[int, float] = {}
        self._last_fish: dict[int, float] = {}
        self._fish_pending: dict[int, dict] = {}
        self._fish_lock: dict[int, float] = {}
        self._lb_cache: tuple[float, dict | None] = (0.0, None)
        self._inflight = 0

    def _auth(self, request: web.Request) -> dict | None:
        init_data = request.headers.get("X-Init-Data", "")
        user = parse_init_data(init_data, config.bot_token) if config.bot_token else None
        if not user:
            token = request.headers.get("X-Auth-Token", "").strip()
            if token:
                row = self.db.user_by_token(auth.token_hash(token), int(time.time()))
                if row:
                    return row
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
            user["id"], user.get("username"), user.get("first_name"), referrer,
            user.get("photo_url"))

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
        if username and username in config.admin_usernames:
            return True
        return (user.get("role") or "user") in ("admin", "owner")

    @staticmethod
    def _is_staff(user: dict) -> bool:
        if Api._is_admin(user):
            return True
        return (user.get("role") or "user") in ("moderator", "tester")

    def _require_admin(self, request: web.Request):
        user = self._auth(request)
        if not user:
            return None, self._fail("unauthorized", 401)
        if not self._is_admin(user):
            return None, self._fail("Недостаточно прав", 403)
        return user, None

    def _require_staff(self, request: web.Request):
        user = self._auth(request)
        if not user:
            return None, self._fail("unauthorized", 401)
        if not self._is_staff(user):
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
            "daily_bonus": raw.get("daily_bonus", game.DAILY_BONUS),
            "hourly_bonus": raw.get("hourly_bonus", game.HOURLY_BONUS),
            "maintenance": raw.get("maintenance", 0),
            "chat_url": raw.get("chat_url", config.chat_url),
            "games": {
                "mines": int(raw.get("game_mines", 1)) == 1,
                "dice": int(raw.get("game_dice", 1)) == 1,
                "wheel": int(raw.get("game_wheel", 1)) == 1,
                "crash": int(raw.get("game_crash", 1)) == 1,
                "roulette": int(raw.get("game_roulette", 1)) == 1,
                "slots": int(raw.get("game_slots", 1)) == 1,
                "coinflip": int(raw.get("game_coinflip", 1)) == 1,
                "blackjack": int(raw.get("game_blackjack", 1)) == 1,
                "basket": int(raw.get("game_basket", 1)) == 1,
                "darts": int(raw.get("game_darts", 1)) == 1,
                "fishing": int(raw.get("game_fishing", 1)) == 1,
            },
        }

    def _game_enabled(self, settings: dict, key: str) -> bool:
        return int(settings.get("game_" + key, 1)) == 1

    @staticmethod
    def _prize_view(prize: dict) -> dict:
        if prize["kind"] == "coins":
            return {"kind": "coins", "title": "+" + str(prize["amount"]),
                    "amount": prize["amount"]}
        if prize["kind"] == "gmpoint":
            return {"kind": "gmpoint", "title": "+" + str(prize["amount"]) + " G",
                    "amount": prize["amount"]}
        item = next((i for i in game.SHOP_ITEMS if i["key"] == prize["item"]), None)
        return {"kind": "item", "title": item["title"] if item else prize["item"],
                "item": prize["item"]}

    def _invites_view(self, user: dict) -> dict:
        refs = self.db.referrals(user["user_id"])
        claimed = self.db.invite_claims(user["user_id"])
        ladder = [
            {"step": item["step"], "reward": item["reward"],
             "done": refs["total"] >= item["step"], "claimed": item["step"] in claimed}
            for item in game.REF_LADDER
        ]
        return {"total": refs["total"], "active": refs["active"], "ladder": ladder}

    def _sponsors_view(self, user: dict) -> list[dict]:
        claimed = self.db.sponsor_claims(user["user_id"])
        return [{"channel": "@" + channel, "reward": game.SPONSOR_REWARD,
                 "claimed": channel in claimed}
                for channel in config.sponsor_channels]

    def _deposits_view(self, user: dict) -> dict:
        now = int(time.time())
        items = []
        for row in self.db.deposits(user["user_id"]):
            if row["kind"] != "fixed":
                continue
            interest = game.deposit_interest(row["amount"], row["rate_bps"])
            items.append({
                "id": row["id"],
                "amount": row["amount"],
                "rate_bps": row["rate_bps"],
                "ends_at": row["ends_at"],
                "ready": now >= int(row["ends_at"] or 0),
                "payout": row["amount"] + interest,
            })
        savings = self.db.savings(user["user_id"])
        savings_data = None
        if savings:
            accrued = game.savings_interest(
                savings["amount"], savings["rate_bps"],
                now - int(savings["started_at"]))
            savings_data = {
                "id": savings["id"],
                "amount": savings["amount"],
                "rate_bps": savings["rate_bps"],
                "accrued": accrued,
            }
        plans = [
            {"days": plan["days"], "rate_bps": plan["rate_bps"],
             "percent": plan["rate_bps"] / 100}
            for plan in game.DEPOSIT_PLANS
        ]
        return {"plans": plans, "items": items, "savings": savings_data,
                "min": game.DEPOSIT_MIN, "max": game.DEPOSIT_MAX}

    def _spin_view(self) -> dict:
        return {
            "prizes": [self._prize_view(segment) for segment in game.DAILY_SPIN],
            "cooldown": game.SPIN_COOLDOWN,
            "streak_days": game.SPIN_STREAK_DAYS,
        }

    def _achievements_view(self, user: dict) -> list[dict]:
        claimed = self.db.user_achievements(user["user_id"])
        stats = awards.metrics(self.db, user["user_id"])
        items = []
        for ach in game.ACHIEVEMENTS:
            target = ach["target"]
            progress = stats.get(ach["metric"], 0)
            items.append({
                "key": ach["key"],
                "icon": ach["icon"],
                "title": ach["title"],
                "desc": ach["desc"],
                "reward": ach["reward"],
                "xp": ach["xp"],
                "target": target,
                "progress": min(target, progress),
                "done": progress >= target,
                "claimed": ach["key"] in claimed,
            })
        return items

    def _public_user(self, user: dict) -> dict:
        now = int(time.time())
        cooldown_left = max(0, user["last_daily"] + game.DAILY_COOLDOWN - now)
        hourly_left = max(0, int(user.get("last_hourly") or 0) + game.HOURLY_COOLDOWN - now)
        spin_left = max(0, int(user.get("last_spin") or 0) + game.SPIN_COOLDOWN - now)
        level = game.level_view(user.get("xp") or 0)
        prefix = game.prefix_view(user.get("prefix"))
        avatar = game.avatar_view(user.get("avatar_key"))
        bg = game.background_view(user.get("bg_key"))
        game_bg = game.game_background_view(user.get("game_bg_key"))
        custom_bg = self.db.user_background(user["user_id"])
        custom_av = self.db.user_avatar(user["user_id"])
        avatar_url = ""
        if (user.get("avatar_key") or "") == "custom" and custom_av:
            avatar_url = (f"/api/profile/avatar/{user['user_id']}"
                          f"?v={int(custom_av['updated_at'])}")
        if (user.get("game_bg_key") or "") == game.CUSTOM_BG_KEY and custom_bg:
            game_bg_url = (f"/api/profile/background/{user['user_id']}"
                           f"?v={int(custom_bg['updated_at'])}")
        elif game_bg["file"]:
            game_bg_url = "/static/" + game_bg["file"]
        else:
            game_bg_url = ""
        return {
            "prefix": user.get("prefix") or "",
            "prefix_title": prefix["title"] if prefix else "",
            "prefix_color": prefix["color"] if prefix else "",
            "prefix_color2": prefix["color2"] if prefix else "",
            "prefix_style": prefix["style"] if prefix else "solid",
            "prefix_bonus": prefix["bonus"] if prefix else 0.0,
            "avatar_key": avatar["key"],
            "avatar_icon": avatar["icon"],
            "avatar_url": avatar_url,
            "bg_key": bg["key"],
            "bg_css": bg["css"],
            "game_bg_key": game_bg["key"],
            "game_bg_title": game_bg["title"],
            "game_bg_url": game_bg_url,
            "game_bg_custom": bool(custom_bg),
            "rod_key": game.rod_view(user.get("rod_key"))["key"],
            "rod_title": game.rod_view(user.get("rod_key"))["title"],
            "last_seen": int(user.get("last_seen") or 0),
            "boost_win": self.db.item_qty(user["user_id"], "boost_win"),
            "boost_loss": self.db.item_qty(user["user_id"], "boost_loss"),
            "id": user["user_id"],
            "username": user["username"],
            "first_name": user["first_name"],
            "photo_url": user.get("photo_url") or "",
            "balance": user["balance"],
            "gmpoint": user.get("gmpoint") or 0,
            "games_played": user["games_played"],
            "games_won": user["games_won"],
            "total_wagered": user["total_wagered"],
            "total_won": user["total_won"],
            "best_multiplier": user["best_multiplier"],
            "xp": level["xp"],
            "level": level["level"],
            "level_title": level["title"],
            "level_into": level["into"],
            "level_need": level["need"],
            "level_percent": level["percent"],
            "level_next": level["next"],
            "duels_played": int(user.get("duels_played") or 0),
            "duels_won": int(user.get("duels_won") or 0),
            "daily_ready": cooldown_left == 0,
            "daily_in": cooldown_left,
            "daily_streak": int(user.get("daily_streak") or 0),
            "daily_amount": game.daily_bonus_for_streak(
                int(user.get("daily_streak") or 0) + 1),
            "daily_next_amount": game.daily_bonus_for_streak(
                int(user.get("daily_streak") or 0) + 2),
            "hourly_ready": hourly_left == 0,
            "hourly_in": hourly_left,
            "hourly_amount": game.HOURLY_BONUS,
            "spin_ready": spin_left == 0,
            "spin_in": spin_left,
            "spin_day": int(user.get("spin_day") or 1),
            "ref_code": f"ref_{user['user_id']}",
        }

    def _level_rows(self, rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            level = game.level_view(row.get("xp") or 0)
            result.append(self._decorate_row({
                **row,
                "level": level["level"],
                "level_title": level["title"],
            }))
        return result

    def _decorate_row(self, row: dict) -> dict:
        """Добавляет к строке топа оформление ника и аватар."""
        entry = dict(row)
        prefix = game.prefix_view(entry.get("prefix"))
        avatar = game.avatar_view(entry.get("avatar_key"))
        bg = game.background_view(entry.get("bg_key"))
        entry["prefix_title"] = prefix["title"] if prefix else ""
        entry["prefix_color"] = prefix["color"] if prefix else ""
        entry["prefix_color2"] = prefix["color2"] if prefix else ""
        entry["prefix_style"] = prefix["style"] if prefix else "solid"
        entry["avatar_icon"] = avatar["icon"]
        entry["avatar_url"] = ""
        if (entry.get("avatar_key") or "") == "custom":
            uid = int(entry.get("user_id") or 0)
            av_row = self.db.user_avatar(uid) if uid else None
            entry["avatar_url"] = (f"/api/profile/avatar/{uid}?v={int(av_row['updated_at'])}"
                                   if av_row else "")
        entry["bg_css"] = bg["css"]
        entry["last_seen"] = int(entry.get("last_seen") or 0)
        return entry

    def _top_rows(self, rows: list[dict]) -> list[dict]:
        return [self._decorate_row(row) for row in rows]

    async def state(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if awards.evaluate(self.db, user["user_id"]):
            user = self.db.user(user["user_id"])
        active = self.db.active_round(user["user_id"])
        payload = {
            "ok": True,
            "user": self._public_user(user),
            "achievements": self._achievements_view(user),
            "bot_username": config.bot_username,
            "chat_url": config.chat_url,
            "is_admin": self._is_staff(user),
            "is_superadmin": self._is_admin(user),
            "role": user.get("role") or "user",
            "account": ({"login": self.db.account(user["user_id"])["login"]}
                        if self.db.account(user["user_id"]) else None),
            "settings": self._public_settings(),
            "rank": self.db.rank(user["user_id"]),
            "referrals": self.db.referrals(user["user_id"]),
            "leaderboard": self._top_rows(self.db.leaderboard(10)),
            "leaderboard_level": self._level_rows(self.db.top_by_level(10)),
            "history": self.db.history(user["user_id"], 10),
            "fair": {
                "seed_hash": user["server_seed_hash"],
                "client_seed": user["client_seed"],
                "nonce": user["nonce"],
            },
            "quests": self._quests_view(user),
            "inventory": self._inventory_view(user),
            "invites": self._invites_view(user),
            "sponsors": self._sponsors_view(user),
            "deposits": self._deposits_view(user),
            "spin": self._spin_view(),
            "levels": self._levels_view(user),
            "games_hub": {
                "players": self.db.game_players(),
                "last": self.db.last_game(user["user_id"]),
            },
            "active_round": None,
        }
        if active:
            payload["active_round"] = self._round_view(active, user, reveal=False)
        active_bj = self.db.active_bj(user["user_id"])
        payload["active_bj"] = self._bj_view(active_bj) if active_bj else None
        payload["updates"] = self._updates_view()
        payload["transfers"] = self.db.transfers(user["user_id"], 10)
        payload["treasury"] = self.db.treasury()
        return self._json(payload)

    async def updates_list(self, request: web.Request) -> web.Response:
        return self._json({"ok": True, **self._updates_view()})

    @staticmethod
    def _updates_view() -> dict:
        return {
            "version": updates.VERSION,
            "title": updates.TITLE,
            "published": updates.PUBLISHED,
            "notes": list(updates.NOTES),
        }

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
            "auto_target": float(rnd.get("auto_target") or 0),
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
            auto_target = float(body.get("auto_target", 0) or 0)
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")

        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)

        settings = self._settings()
        if not self._game_enabled(settings, "mines"):
            return self._fail("«Сапёр» временно отключён")
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
        if auto_target:
            top = game.max_multiplier(mines)
            if not (1.05 <= auto_target <= top):
                return self._fail(f"Авто-кэшаут от 1.05 до {top:.2f}")
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
                             user["server_seed"], user["client_seed"], nonce,
                             auto_target)
        result = {
            "ok": True,
            "round": {
                "id": round_id,
                "bet": bet,
                "mines": mines,
                "opened": [],
                "multiplier": 1.0,
                "payout": 0,
                "auto_target": auto_target,
                "status": "active",
                "next_chance": game.next_chance(mines, 0),
                "max_multiplier": game.max_multiplier(mines),
                "ladder": game.ladder(mines, 0),
            },
            "balance": balance,
        }
        if self._is_admin(user):
            result["cheat"] = {
                "enabled": True,
                "game": "mines",
                "mine_positions": positions,
                "safe_cells": [i for i in range(game.CELLS) if i not in positions],
            }
        return self._json(result)

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
            self._finish(user, rnd["bet"], 0, 0)
            refund = self._insurance_refund(user, rnd["bet"])
            self._settle_referral(user["user_id"])
            resp = {
                "ok": True,
                "lost": True,
                "cell": cell,
                "mine_positions": rnd["mine_positions"],
                "multiplier": rnd["multiplier"],
                "refund": refund,
                "balance": self.db.user(user["user_id"])["balance"],
                "status": "lost",
            }
            if self._is_admin(user):
                resp["cheat"] = {
                    "enabled": True,
                    "game": "mines",
                    "mine_positions": rnd["mine_positions"],
                    "safe_cells": [i for i in range(game.CELLS)
                                   if i not in rnd["mine_positions"]],
                }
            return self._json(resp)

        opened = rnd["opened"] + [cell]
        mult = game.multiplier(rnd["mines"], len(opened))
        safe = game.CELLS - rnd["mines"]
        finished = len(opened) >= safe
        target = float(rnd.get("auto_target") or 0)
        auto = bool(target) and not finished and mult >= target
        payout = game.payout_for(rnd["bet"], mult) if (finished or auto) else 0
        if finished or auto:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "mines", payout)
            payout = self._gold_pick(user, payout)
        status = "won" if finished else ("cashed" if auto else "active")
        payout = self._prefix_bonus(user, payout)
        self.db.update_round(rnd["id"], opened, mult, status, payout)

        balance = self.db.user(user["user_id"])["balance"]
        if finished or auto:
            balance = self.db.add_balance(user["user_id"], payout)
            self._finish(user, rnd["bet"], payout, mult)
            self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "lost": False,
            "cell": cell,
            "opened": opened,
            "multiplier": mult,
            "payout": payout,
            "finished": finished or auto,
            "auto": auto,
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
        payout = self._gold_pick(user, payout)
        payout = self._prefix_bonus(user, payout)
        self.db.update_round(rnd["id"], rnd["opened"], mult, "cashed", payout)
        balance = self.db.add_balance(user["user_id"], payout)
        self._finish(user, rnd["bet"], payout, mult)
        self._settle_referral(user["user_id"])
        return self._json({
            "ok": True,
            "multiplier": mult,
            "payout": payout,
            "balance": balance,
            "mine_positions": rnd["mine_positions"],
            "status": "cashed",
        })

    def _finish(self, user: dict, bet: int, payout: int, mult: float) -> list[dict]:
        self.db.finish_stats(user["user_id"], bet, payout, mult)
        self._apply_boost(user, bet, payout)
        if payout > 0:
            self.db.referral_share(user["user_id"], payout, game.REF_WIN_SHARE)
        xp = game.XP_PER_GAME + (game.XP_PER_WIN if payout > 0 else 0)
        self.db.add_xp(user["user_id"], xp)
        earned = awards.evaluate(self.db, user["user_id"])
        self.db.claim_referral_bonus(user["user_id"])
        return earned

    def _apply_boost(self, user: dict, bet: int, payout: int) -> int:
        """Списывает заряд буста и начисляет бонус. Возвращает сумму бонуса."""
        uid = user["user_id"]
        if payout > 0:
            if not self.db.take_item(uid, "boost_win"):
                return 0
            extra = int(round(payout * game.BOOST_WIN_RATE))
        elif bet > 0:
            if not self.db.take_item(uid, "boost_loss"):
                return 0
            extra = int(round(bet * game.BOOST_LOSS_RATE))
        else:
            return 0
        if extra <= 0:
            return 0
        self.db.add_balance(uid, extra)
        return extra

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
        base = int(self._settings().get("daily_bonus", game.DAILY_BASE))
        doubled = self.db.take_item(user["user_id"], "double_daily")
        result = self.db.claim_daily_progressive(
            user["user_id"], now, game.DAILY_COOLDOWN, game.day_key(),
            base, game.DAILY_STEP, game.DAILY_STREAK_CAP, game.DAILY_MAX)
        if not result:
            return self._fail("Бонус ещё не готов", 429)
        bonus = int(result["amount"])
        if doubled:
            self.db.add_balance(user["user_id"], bonus)
            bonus *= 2
        streak = int(result["streak"])
        gmpoint_bonus = 2
        self.db.add_gmpoint(user["user_id"], gmpoint_bonus)
        earned = awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "amount": bonus, "doubled": doubled,
                           "streak": streak,
                           "next_amount": game.daily_bonus_for_streak(streak + 1),
                           "gmpoint": gmpoint_bonus,
                           "awards": earned, "balance": fresh["balance"],
                           "gmpoint_total": fresh["gmpoint"]})

    async def history(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, "items": self.db.history(user["user_id"], 30)})

    async def leaderboard(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        cached_at, cached = self._lb_cache
        if cached and time.time() - cached_at < 10:
            return self._json({"ok": True, **cached, "me": user["user_id"]})
        payload = {
            "by_balance": self._top_rows(self.db.leaderboard(20)),
            "by_multiplier": self._top_rows(self.db.top_multiplier(10)),
            "by_level": self._level_rows(self.db.top_by_level(20)),
        }
        self._lb_cache = (time.time(), payload)
        return self._json({"ok": True, **payload, "me": user["user_id"]})

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
    def _bet_error(self, user: dict, bet: int, game_key: str | None = None) -> str | None:
        if user.get("is_banned"):
            return "Аккаунт заблокирован"
        now = time.time()
        limit = float(__import__("os").environ.get("RATE_LIMIT_MIN", "1"))
        gap = (0.7 if game_key in ("dice", "wheel", "crash", "coinflip", "basket")
               else 0.25) * limit
        if gap > 0:
            last = self._last_action.get(user["user_id"], 0.0)
            if now - last < gap:
                return "Слишком быстро — подождите секунду"
            self._last_action[user["user_id"]] = now
        settings = self._settings()
        if game_key and not self._game_enabled(settings, game_key):
            return "Эта игра временно отключена"
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
        error = self._bet_error(user, bet, "dice")
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
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "dice", bet, win, payout,
                         {"roll": roll, "pick": pick, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
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
            **({"cheat": {"enabled": True, "game": "dice",
                          "correct": "even" if is_even else "odd",
                          "hint": f"Кость выпадет {roll} — {'чёт' if is_even else 'нечёт'}"}}
               if self._is_admin(user) else {}),
        })

    async def coinflip(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        pick = str(body.get("pick", "heads")).lower()
        if pick not in ("heads", "tails"):
            return self._fail("Выберите «орёл» или «решку»")
        error = self._bet_error(user, bet, "coinflip")
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        side = game.coinflip(user["server_seed"], user["client_seed"], nonce)
        win = side == pick
        multiplier = game.COINFLIP_MULTIPLIER if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "coinflip", payout)
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "coinflip", bet, win,
                         payout, {"side": side, "pick": pick, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "side": side,
            "pick": pick,
            "win": win,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "quests": self._quests_view(user),
        })

    # --- блэкджек --------------------------------------------------------
    def _bj_view(self, rnd: dict) -> dict:
        player = rnd["player"]
        dealer = rnd["dealer"]
        finished = rnd["status"] != "active"
        dealer_view = dealer if finished else dealer[:1]
        multiplier = game.bj_multiplier(player, dealer) if finished else 0.0
        return {
            "id": rnd["id"],
            "bet": rnd["bet"],
            "doubled": bool(rnd.get("doubled")),
            "player": player,
            "dealer": dealer_view,
            "player_value": game.bj_value(player),
            "dealer_value": game.bj_value(dealer_view),
            "dealer_hidden": not finished and len(dealer) > 1,
            "status": rnd["status"],
            "payout": rnd["payout"],
            "multiplier": multiplier,
            "blackjack": game.bj_blackjack(player),
        }

    def _bj_settle(self, user: dict, rnd: dict, player: list[dict],
                   dealer: list[dict], doubled: bool, status: str = "finished") -> tuple[int, float]:
        stake = rnd["bet"] * (2 if doubled else 1)
        multiplier = game.bj_multiplier(player, dealer) if status == "finished" else 0.0
        payout = int(math.floor(stake * multiplier)) if multiplier > 0 else 0
        if payout > 0:
            extra = 0
            relic = game.GAME_RELICS.get("blackjack")
            if relic and self.db.item_qty(user["user_id"], relic) > 0:
                extra += int(payout * game.RELIC_BONUS)
            if self.db.take_item(user["user_id"], "charm"):
                extra += int(payout * game.CHARM_BONUS)
            if extra > 0:
                payout += extra
                self.db.add_balance(user["user_id"], extra)
        payout = self._prefix_bonus(user, payout)
        self.db.add_balance(user["user_id"], payout)
        self.db.update_bj(rnd["id"], player, dealer, status, payout, doubled)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "blackjack", stake,
                         payout > 0, payout, {"status": status, "doubled": doubled})
        self._finish(user, stake, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])
        return payout, multiplier

    def _bj_payload(self, user: dict, rnd: dict, payout: int, multiplier: float) -> dict:
        balance = self.db.user(user["user_id"])["balance"]
        view = self._bj_view(rnd)
        view["payout"] = payout
        view["multiplier"] = multiplier
        return {
            "ok": True,
            "round": view,
            "balance": balance,
            "quests": self._quests_view(user),
        }

    async def bj_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        error = self._bet_error(user, bet, "blackjack")
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)
        if self.db.active_bj(user["user_id"]):
            return self._fail("Сначала завершите текущую партию в «21»")
        if self.db.active_round(user["user_id"]):
            return self._fail("Сначала завершите текущую игру в «Сапёре»")

        nonce = self.db.bump_nonce(user["user_id"])
        deck = game.bj_deck(user["server_seed"], user["client_seed"], nonce)
        player = [deck[0], deck[2]]
        dealer = [deck[1], deck[3]]
        round_id = uuid.uuid4().hex[:16]
        balance = self.db.add_balance(user["user_id"], -bet)
        self.db.create_bj(round_id, user["user_id"], bet, deck, player, dealer)
        rnd = {"id": round_id, "bet": bet, "doubled": False, "status": "active",
               "payout": 0, "player": player, "dealer": dealer}
        if game.bj_blackjack(player) or game.bj_blackjack(dealer):
            payout, multiplier = self._bj_settle(user, rnd, player, dealer, False)
            rnd["status"] = "finished"
            rnd["payout"] = payout
            payload = self._bj_payload(user, rnd, payout, multiplier)
            payload["instant"] = True
            return self._json(payload)
        payload = self._bj_payload(user, rnd, 0, 0.0)
        payload["balance"] = balance
        return self._json(payload)

    async def bj_hit(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        rnd = self.db.bj_round(str(body.get("id", "")))
        if not rnd or rnd["user_id"] != user["user_id"]:
            return self._fail("Партия не найдена", 404)
        if rnd["status"] != "active":
            return self._fail("Партия уже завершена")
        if rnd["doubled"]:
            return self._fail("После удвоения карты больше не берутся")

        player = list(rnd["player"])
        dealer = list(rnd["dealer"])
        index = len(player) + len(dealer)
        if index >= len(rnd["deck"]):
            return self._fail("Колода закончилась")
        player.append(rnd["deck"][index])

        if game.bj_value(player) > game.BJ_TARGET:
            payout, multiplier = self._bj_settle(user, rnd, player, dealer, False, "bust")
            rnd.update({"status": "bust", "player": player, "payout": payout})
            return self._json(self._bj_payload(user, rnd, payout, 0.0))

        self.db.update_bj(rnd["id"], player, dealer, "active", 0)
        rnd["player"] = player
        return self._json(self._bj_payload(user, rnd, 0, 0.0))

    async def bj_stand(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        rnd = self.db.bj_round(str(body.get("id", "")))
        if not rnd or rnd["user_id"] != user["user_id"]:
            return self._fail("Партия не найдена", 404)
        if rnd["status"] != "active":
            return self._fail("Партия уже завершена")

        player = list(rnd["player"])
        dealer = list(rnd["dealer"])
        index = len(player) + len(dealer)
        dealer = game.bj_dealer_play(rnd["deck"][index:], dealer)
        payout, multiplier = self._bj_settle(user, rnd, player, dealer, rnd["doubled"])
        rnd.update({"status": "finished", "player": player, "dealer": dealer,
                    "payout": payout})
        return self._json(self._bj_payload(user, rnd, payout, multiplier))

    async def bj_double(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        rnd = self.db.bj_round(str(body.get("id", "")))
        if not rnd or rnd["user_id"] != user["user_id"]:
            return self._fail("Партия не найдена", 404)
        if rnd["status"] != "active":
            return self._fail("Партия уже завершена")
        if len(rnd["player"]) != 2:
            return self._fail("Удвоение доступно только на первых двух картах")
        if user["balance"] < rnd["bet"]:
            return self._fail("Недостаточно средств для удвоения")

        self.db.add_balance(user["user_id"], -rnd["bet"])
        player = list(rnd["player"])
        dealer = list(rnd["dealer"])
        index = len(player) + len(dealer)
        if index >= len(rnd["deck"]):
            return self._fail("Колода закончилась")
        player.append(rnd["deck"][index])

        if game.bj_value(player) > game.BJ_TARGET:
            payout, multiplier = self._bj_settle(user, rnd, player, dealer, True, "bust")
            rnd.update({"status": "bust", "player": player, "doubled": True,
                        "payout": payout})
            return self._json(self._bj_payload(user, rnd, payout, 0.0))

        index = len(player) + len(dealer)
        dealer = game.bj_dealer_play(rnd["deck"][index:], dealer)
        payout, multiplier = self._bj_settle(user, rnd, player, dealer, True)
        rnd.update({"status": "finished", "player": player, "dealer": dealer,
                    "doubled": True, "payout": payout})
        return self._json(self._bj_payload(user, rnd, payout, multiplier))

    async def basket(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        error = self._bet_error(user, bet, "basket")
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        scored = game.basket_shot(user["server_seed"], user["client_seed"], nonce)
        multiplier = game.BASKET_MULTIPLIER if scored else 0.0
        payout = int(math.floor(bet * multiplier)) if scored else 0
        refund = 0
        if scored:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "basket", payout)
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "basket", bet, scored,
                         payout, {"scored": scored, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        return self._json({
            "ok": True,
            "scored": scored,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "quests": self._quests_view(user),
            **({"cheat": {"enabled": True, "game": "basket",
                          "correct": "scored" if scored else "miss",
                          "hint": f"Мяч {'попадёт в кольцо' if scored else 'не попадёт'}"}}
               if self._is_admin(user) else {}),
        })

    async def darts(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        pick = str(body.get("pick", "sector")).strip().lower()
        if not game.darts_pick(pick):
            return self._fail("Выбери: bull, sector или miss")
        error = self._bet_error(user, bet, "darts")
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        value = game.dart_throw(user["server_seed"], user["client_seed"], nonce)
        win = game.darts_lands(pick, value)
        multiplier = game.darts_multiplier(pick, value)
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = self._charm_bonus(user, payout)
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "darts", bet, win,
                         payout, {"value": value, "pick": pick, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
        self._settle_referral(user["user_id"])

        sector = next((item["key"] for item in game.DARTS_SECTORS
                       if value in item["values"]), "miss")
        return self._json({
            "ok": True,
            "value": value,
            "sector": sector,
            "pick": pick,
            "win": win,
            "multiplier": multiplier,
            "payout": payout,
            "refund": refund,
            "balance": self.db.user(user["user_id"])["balance"],
            "quests": self._quests_view(user),
            **({"cheat": {"enabled": True, "game": "darts",
                          "correct": sector,
                          "hint": f"Дротик попадёт в сектор «{sector}»"}}
               if self._is_admin(user) else {}),
        })

    async def transfer(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        try:
            amount = int(body.get("amount", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная сумма")
        target = str(body.get("to", "")).strip()
        if amount < 1:
            return self._fail("Сумма должна быть больше нуля")
        if amount > int(user["balance"]):
            return self._fail("Недостаточно средств")
        if not target:
            return self._fail("Укажите ID или @username получателя")

        recipient = None
        if target.startswith("@"):
            recipient = self.db.user_by_username(target)
        elif target.isdigit():
            recipient = self.db.user(int(target))
        if not recipient:
            recipient = self.db.user_by_username(target)
        if not recipient:
            return self._fail("Игрок не найден")
        if int(recipient["user_id"]) == int(user["user_id"]):
            return self._fail("Нельзя перевести самому себе")
        if recipient.get("is_banned"):
            return self._fail("Получатель заблокирован")

        self.db.make_transfer(uuid.uuid4().hex[:16], user["user_id"],
                              int(recipient["user_id"]), amount)
        balance = self.db.user(user["user_id"])["balance"]
        return self._json({
            "ok": True,
            "amount": amount,
            "to": {
                "id": int(recipient["user_id"]),
                "username": recipient.get("username") or "",
                "first_name": recipient.get("first_name") or "",
            },
            "balance": balance,
        })

    async def transfers(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, "items": self.db.transfers(user["user_id"], 20)})

    async def promo(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        code = str(body.get("code", "")).strip().upper()
        if not code:
            return self._fail("Введите промокод")
        status, amount = self.db.claim_promo(code, user["user_id"], int(time.time()))
        messages = {
            "not_found": "Такого промокода нет",
            "inactive": "Промокод больше не действует",
            "expired": "Срок действия промокода истёк",
            "already": "Вы уже активировали этот промокод",
            "exhausted": "Промокод закончился",
        }
        if status != "ok":
            return self._fail(messages.get(status, "Не удалось активировать"))
        balance = self.db.user(user["user_id"])["balance"]
        return self._json({"ok": True, "amount": amount, "balance": balance,
                           "quests": self._quests_view(user)})

    async def fish_catch(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        settings = self._settings()
        if not self._game_enabled(settings, "fishing"):
            return self._fail("Рыбалка временно отключена")
        now = time.time()
        lock_until = self._fish_lock.get(user["user_id"], 0.0)
        if lock_until > now:
            wait = int(math.ceil(lock_until - now))
            return self._fail(f"Рыба ушла — подождите {wait} с")
        pending = self._fish_pending.get(user["user_id"])
        if pending and pending["deadline"] > now:
            return self._fail("Рыба уже на крючке — успейте схватить")
        gap = float(__import__("os").environ.get("RATE_LIMIT_MIN", "1"))
        if gap > 0 and now - self._last_fish.get(user["user_id"], 0.0) < game.FISH_COOLDOWN:
            return self._fail("Рыба ещё не подошла — подождите")
        self._last_fish[user["user_id"]] = now
        nonce = self.db.bump_nonce(user["user_id"])
        rod = game.rod_view(user.get("rod_key"))
        fish = game.fish_catch(user["server_seed"], user["client_seed"], nonce, rod)
        cell = game.fish_cell(user["server_seed"], user["client_seed"], nonce)
        self._fish_pending[user["user_id"]] = {
            "fish": fish,
            "cell": cell,
            "deadline": now + game.FISH_GRAB_SECONDS,
            "rod": rod["title"],
        }
        return self._json({
            "ok": True,
            "cell": cell,
            "cells": game.FISH_CELLS,
            "seconds": game.FISH_GRAB_SECONDS,
            "lock_seconds": game.FISH_LOCK_SECONDS,
            "icon": fish["icon"],
            "rarity": fish["rarity"],
            "rarity_title": fish["rarity_title"],
            "rod": rod["title"],
            "balance": self.db.user(user["user_id"])["balance"],
        })

    async def fish_grab(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        try:
            cell = int(body.get("cell", -1))
        except (TypeError, ValueError):
            return self._fail("Некорректная клетка")
        pending = self._fish_pending.pop(user["user_id"], None)
        if not pending:
            return self._fail("Рыба уже уплыла")
        if time.time() > pending["deadline"]:
            self._fish_lock[user["user_id"]] = time.time() + game.FISH_LOCK_SECONDS
            return self._fail(
                f"Не успели — рыба ушла. Ловля заблокирована на "
                f"{game.FISH_LOCK_SECONDS} с")
        if cell != pending["cell"]:
            self._fish_lock[user["user_id"]] = time.time() + game.FISH_LOCK_SECONDS
            return self._fail(
                f"Мимо — рыба ушла. Ловля заблокирована на "
                f"{game.FISH_LOCK_SECONDS} с")
        fish = pending["fish"]
        fish_id = uuid.uuid4().hex[:16]
        self.db.add_fish(fish_id, user["user_id"], fish)
        return self._json({"ok": True, "id": fish_id, **fish,
                           "rod": pending["rod"],
                           "balance": self.db.user(user["user_id"])["balance"]})

    async def fish_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        items = self.db.fish_list(user["user_id"], 0)
        total = sum(int(item["price"]) for item in items)
        return self._json({"ok": True, "items": items, "total": total,
                           "balance": self.db.user(user["user_id"])["balance"]})

    async def fish_sell(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        if body.get("all"):
            total, count = self.db.sell_all_fish(user["user_id"])
            if count == 0:
                return self._fail("Сначала поймайте рыбу")
            return self._json({"ok": True, "sold": count, "amount": total,
                               "balance": self.db.user(user["user_id"])["balance"]})
        fish_id = str(body.get("id", "")).strip()
        if not fish_id:
            return self._fail("Не указана рыба")
        price = self.db.sell_fish(user["user_id"], fish_id)
        if price is None:
            return self._fail("Рыба не найдена или уже продана", 404)
        return self._json({"ok": True, "sold": 1, "amount": price,
                           "balance": self.db.user(user["user_id"])["balance"]})

    def _rods_view(self, user: dict) -> dict:
        uid = user["user_id"]
        active = game.rod_view(user.get("rod_key"))["key"]
        rods = []
        for rod in game.RODS:
            owned = (int(rod["price"]) == 0
                     or self.db.item_qty(uid, "rod_" + rod["key"]) > 0)
            rods.append({**rod, "owned": owned, "active": rod["key"] == active,
                         "icon_file": "rod_" + rod["key"] + ".jpg"})
        return {"rods": rods, "rod_key": active, "balance": user["balance"]}

    async def fish_rods(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        action = str(body.get("action", "list")).strip() or "list"
        if action == "list":
            return self._json({"ok": True, **self._rods_view(user)})
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        key = str(body.get("key", "")).strip()
        rod = game.ROD_BY_KEY.get(key)
        if not rod:
            return self._fail("Удочка не найдена", 404)
        item_key = "rod_" + key
        if action == "buy":
            if int(rod["price"]) == 0 or self.db.item_qty(user["user_id"], item_key) > 0:
                return self._fail("Эта удочка уже доступна")
            price = int(rod["price"])
            if int(user["balance"]) < price:
                return self._fail("Недостаточно mCoin")
            balance = self.db.add_balance(user["user_id"], -price)
            self.db.add_item(user["user_id"], item_key, 1)
            self.db.set_rod(user["user_id"], key)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "bought": rod["title"],
                               "balance": balance, **self._rods_view(fresh)})
        if action == "equip":
            owned = (int(rod["price"]) == 0
                     or self.db.item_qty(user["user_id"], item_key) > 0)
            if not owned:
                return self._fail("Сначала купи эту удочку")
            self.db.set_rod(user["user_id"], key)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "equipped": True,
                               **self._rods_view(fresh)})
        return self._fail("Неизвестное действие")

    async def wheel(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        try:
            bet = int(body.get("bet", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ставка")
        error = self._bet_error(user, bet, "wheel")
        if error:
            return self._fail(error, 403 if user.get("is_banned") else 400)

        nonce = self.db.bump_nonce(user["user_id"])
        index, multiplier = game.spin_wheel(user["server_seed"], user["client_seed"], nonce)
        payout = int(math.floor(bet * multiplier)) if multiplier > 0 else 0
        refund = 0
        if multiplier > 0:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "wheel", payout)
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "wheel", bet,
                         multiplier > 0, payout, {"segment": index, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
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
            **({"cheat": {"enabled": True, "game": "wheel",
                          "segment": index,
                          "multiplier": multiplier,
                          "hint": f"Остановится на сегменте {index} "
                                  f"(множитель {multiplier if multiplier > 0 else 0})"}}
               if self._is_admin(user) else {}),
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
                "currency": quest.get("currency") or "",
                "progress": progress,
                "ready": progress >= quest["target"] and quest["key"] not in claimed,
                "claimed": quest["key"] in claimed,
            })
        return items

    def _hour_quests_view(self, user: dict) -> list[dict]:
        hour = game.hour_key()
        stats = self.db.day_stats(user["user_id"], game.hour_start())
        claimed = self.db.hour_claimed_quests(user["user_id"], hour)
        items = []
        for quest in game.HOUR_QUESTS:
            progress = min(quest["target"], int(stats.get(quest["metric"], 0)))
            items.append({
                "key": quest["key"],
                "title": quest["title"],
                "target": quest["target"],
                "reward": quest["reward"],
                "currency": quest.get("currency") or "",
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
                           "items": self._quests_view(user),
                           "hour_items": self._hour_quests_view(user)})

    async def quest_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        quest = next((q for q in game.DAILY_QUESTS if q["key"] == key), None)
        is_hour = False
        if quest is None:
            quest = next((q for q in game.HOUR_QUESTS if q["key"] == key), None)
            is_hour = bool(quest)
        if not quest:
            return self._fail("Неизвестное задание", 404)
        if is_hour:
            stats = self.db.day_stats(user["user_id"], game.hour_start())
            if int(stats.get(quest["metric"], 0)) < quest["target"]:
                return self._fail("Задание ещё не выполнено")
            if not self.db.claim_hour_quest(user["user_id"], game.hour_key(), key):
                return self._fail("Награда уже получена")
        else:
            stats = self.db.day_stats(user["user_id"], game.day_start())
            if int(stats.get(quest["metric"], 0)) < quest["target"]:
                return self._fail("Задание ещё не выполнено")
            if not self.db.claim_quest(user["user_id"], game.day_key(), key):
                return self._fail("Награда уже получена")
        if quest.get("currency") == "gmpoint":
            self.db.add_gmpoint(user["user_id"], int(quest["reward"]))
            balance = self.db.user(user["user_id"])["balance"]
            gmpoint = self.db.user(user["user_id"])["gmpoint"]
        else:
            balance = self.db.add_balance(user["user_id"], quest["reward"])
            gmpoint = user.get("gmpoint") or 0
        return self._json({"ok": True, "reward": quest["reward"],
                           "balance": balance, "gmpoint": gmpoint,
                           "quests": self._quests_view(user),
                           "hour_items": self._hour_quests_view(user)})

    # --- уровни ----------------------------------------------------------
    def _levels_view(self, user: dict) -> dict:
        view = game.level_view(user.get("xp") or 0)
        claimed = self.db.level_claims(user["user_id"])
        pending = [lvl for lvl in range(2, view["level"] + 1) if lvl not in claimed]
        return {
            "level": view["level"],
            "title": view["title"],
            "pending": len(pending),
            "pending_levels": pending[-10:],
            "next": view["level"] + 1,
            "next_reward": game.level_reward(view["level"] + 1),
            "to_next": max(0, view["next"] - view["xp"]),
        }

    async def level_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        view = game.level_view(user.get("xp") or 0)
        claimed = self.db.level_claims(user["user_id"])
        got = []
        for lvl in range(2, view["level"] + 1):
            if lvl in claimed:
                continue
            reward = game.level_reward(lvl)
            if self.db.claim_level(user["user_id"], lvl, reward["coins"],
                                   reward["gmpoint"], reward["lootbox"],
                                   reward["prefix"]):
                got.append(reward)
        fresh = self.db.user(user["user_id"])
        return self._json({
            "ok": True,
            "claimed": got,
            "coins": sum(item["coins"] for item in got),
            "gmpoint": sum(item["gmpoint"] for item in got),
            "lootbox": sum(item["lootbox"] for item in got),
            "balance": fresh["balance"],
            "levels": self._levels_view(fresh),
        })

    # --- аккаунт (логин и пароль) ---------------------------------------
    async def auth_register(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("Откройте игру через Telegram", 401)
        body = await self._body(request)
        login = str(body.get("login", "")).strip()
        password = str(body.get("password", ""))
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", login):
            return self._fail("Логин: 3–32 символа, латиница, цифры и _")
        if len(password) < 6:
            return self._fail("Пароль не короче 6 символов")
        existing = self.db.account_by_login(login)
        if existing and int(existing["user_id"]) != int(user["user_id"]):
            return self._fail("Логин уже занят")
        had_account = bool(self.db.account(user["user_id"]))
        digest, salt = auth.hash_password(password)
        self.db.set_account(user["user_id"], login, digest, salt)
        bonus = 0
        if not had_account:
            bonus = int(game.REGISTER_BONUS)
            self.db.add_balance(user["user_id"], bonus)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "login": login, "bonus": bonus,
                           "balance": fresh["balance"] if fresh else 0})

    async def auth_login(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        login = str(body.get("login", "")).strip()
        password = str(body.get("password", ""))
        account = self.db.account_by_login(login)
        if not account or not auth.verify_password(
                password, account["password_hash"], account["password_salt"]):
            return self._fail("Неверный логин или пароль", 401)
        target = self.db.user(account["user_id"])
        if not target:
            return self._fail("Игрок не найден", 404)
        if target.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        remember = bool(body.get("remember", True))
        token = auth.new_token()
        expires = int(time.time()) + (90 * 86400 if remember else 86400)
        self.db.set_account_token(target["user_id"], auth.token_hash(token), expires)
        return self._json({
            "ok": True,
            "token": token,
            "expires": expires,
            "login": account["login"],
        })

    async def auth_logout(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.clear_account_token(user["user_id"])
        return self._json({"ok": True})

    # --- магазин ---------------------------------------------------------
    def _inventory_view(self, user: dict) -> dict:
        inv = self.db.inventory(user["user_id"])
        keys = {item["key"] for item in game.SHOP_ITEMS}
        keys.update({"insurance", "double_daily", "charm"})
        return {key: int(inv.get(key, 0)) for key in sorted(keys)}

    def _inventory_sections(self, user: dict) -> dict:
        uid = user["user_id"]
        inv = self.db.inventory(uid)
        titles = {item["key"]: item["title"] for item in game.SHOP_ITEMS}
        icons = {item["key"]: item.get("icon", "") for item in game.SHOP_ITEMS}

        def make_items(keys) -> list[dict]:
            result = []
            for key in keys:
                qty = int(inv.get(key, 0))
                if qty <= 0:
                    continue
                entry = {"key": key, "title": titles.get(key, key),
                         "icon": icons.get(key, ""), "qty": qty}
                refund = game.sell_refund_price(key)
                if refund > 0:
                    entry["sell"] = refund
                if key == "lootbox":
                    entry["use"] = "open"
                result.append(entry)
            return result

        consumables = make_items(("insurance", "double_daily", "charm",
                                  "boost_win", "boost_loss", "lootbox"))
        relics = make_items(("relic_mines", "relic_dice", "relic_wheel",
                             "relic_crash", "gold_pick", "theme_neon",
                             "theme_gold"))
        prefixes = []
        for key in sorted(self.db.user_prefixes(uid)):
            view = game.prefix_view(key)
            if view:
                prefixes.append({"key": "prefix_" + key, "title": view["title"],
                                 "icon": "🎩", "qty": 1})
        avatars = [item for item in game.AVATARS
                   if int(item["price"]) == 0
                   or self.db.item_qty(
                       uid, game.cosmetic_item_key("avatar", item["key"])) > 0]
        backgrounds = [item for item in game.BACKGROUNDS
                       if int(item["price"]) == 0
                       or self.db.item_qty(
                           uid, game.cosmetic_item_key("background",
                                                       item["key"])) > 0]
        game_bgs = [item for item in game.GAME_BACKGROUNDS
                    if int(item["price"]) == 0
                    or self.db.item_qty(uid, "gbg_" + item["key"]) > 0]
        cosmetics = [
            {"key": "avatars", "title": "Аватарки", "icon": "🦊",
             "qty": len(avatars)},
            {"key": "backgrounds", "title": "Фоны профиля", "icon": "🎨",
             "qty": len(backgrounds)},
            {"key": "game_bg", "title": "Фоны игры", "icon": "🏞",
             "qty": len(game_bgs) + (1 if self.db.user_background(uid) else 0)},
        ]
        rods = [{"key": "rod_" + rod["key"], "title": rod["title"],
                 "icon": "🎣", "qty": 1}
                for rod in game.RODS
                if int(rod["price"]) == 0
                or self.db.item_qty(uid, "rod_" + rod["key"]) > 0]
        fish = self.db.fish_list(uid, 0)
        fishing = rods + [
            {"key": "fish", "title": "Улов в садке", "icon": "🐟",
             "qty": len(fish)},
            {"key": "fish_value", "title": "Стоимость улова", "icon": "◈",
             "qty": sum(int(item["price"]) for item in fish)},
        ]
        return {
            "sections": [
                {"key": "consumables", "title": "Расходники",
                 "items": consumables},
                {"key": "relics", "title": "Реликвии", "items": relics},
                {"key": "prefixes", "title": "Префиксы", "items": prefixes},
                {"key": "cosmetics", "title": "Косметика",
                 "items": cosmetics},
                {"key": "fishing", "title": "Рыболовное",
                 "items": fishing},
            ],
            "inventory": self._inventory_view(user),
        }

    async def inventory(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, **self._inventory_sections(user)})
    def _cosmetics_view(self, user: dict) -> dict:
        uid = user["user_id"]
        avatar_key = user.get("avatar_key") or "letter"
        bg_key = user.get("bg_key") or "default"
        avatars = []
        for item in game.AVATARS:
            owned = (int(item["price"]) == 0
                     or self.db.item_qty(uid, game.cosmetic_item_key("avatar", item["key"])) > 0)
            avatars.append({**item, "owned": owned, "active": item["key"] == avatar_key})
        custom_av = self.db.user_avatar(uid)
        avatars.append({
            "key": "custom",
            "title": "Своё фото",
            "icon": "📷",
            "price": 0,
            "owned": bool(custom_av),
            "active": avatar_key == "custom",
            "url": (f"/api/profile/avatar/{uid}?v={int(custom_av['updated_at'])}"
                    if custom_av else ""),
        })
        backgrounds = []
        for item in game.BACKGROUNDS:
            owned = (int(item["price"]) == 0
                     or self.db.item_qty(uid, game.cosmetic_item_key("background",
                                                                    item["key"])) > 0)
            backgrounds.append({**item, "owned": owned, "active": item["key"] == bg_key})
        game_bg_key = user.get("game_bg_key") or ""
        custom_bg = self.db.user_background(uid)
        game_backgrounds = []
        for item in game.GAME_BACKGROUNDS:
            owned = (int(item["price"]) == 0
                     or self.db.item_qty(uid, "gbg_" + item["key"]) > 0)
            game_backgrounds.append({
                **item,
                "owned": owned,
                "active": (game_bg_key or "default") == item["key"],
                "url": "/static/" + item["file"] if item["file"] else "",
            })
        game_backgrounds.append({
            "key": game.CUSTOM_BG_KEY,
            "title": "Своё фото",
            "price": 0,
            "file": "",
            "owned": bool(custom_bg),
            "active": game_bg_key == game.CUSTOM_BG_KEY,
            "url": (f"/api/profile/background/{uid}?v={int(custom_bg['updated_at'])}"
                    if custom_bg else ""),
        })
        return {"avatars": avatars, "backgrounds": backgrounds,
                "game_backgrounds": game_backgrounds,
                "avatar_key": avatar_key, "bg_key": bg_key,
                "game_bg_key": game_bg_key,
                "balance": user["balance"]}

    async def profile_cosmetics(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        action = str(body.get("action", "list")).strip() or "list"
        kind = str(body.get("kind", "avatar")).strip()
        key = str(body.get("key", "")).strip()
        if action == "list":
            return self._json({"ok": True, **self._cosmetics_view(user)})
        if kind == "gamebg":
            if user.get("is_banned"):
                return self._fail("Аккаунт заблокирован", 403)
            if key == game.CUSTOM_BG_KEY:
                if not self.db.user_background(user["user_id"]):
                    return self._fail("Своё фото ещё не загружено")
                if action != "equip":
                    return self._fail("Своё фото загружается отдельно")
                self.db.set_game_background(user["user_id"], game.CUSTOM_BG_KEY)
                fresh = self.db.user(user["user_id"])
                return self._json({"ok": True, "equipped": True,
                                   "user": self._public_user(fresh),
                                   **self._cosmetics_view(fresh)})
            item = next((entry for entry in game.GAME_BACKGROUNDS
                         if entry["key"] == key), None)
            if not item:
                return self._fail("Фон не найден", 404)
            item_key = "gbg_" + key
            if action == "buy":
                if int(item["price"]) == 0 or self.db.item_qty(
                        user["user_id"], item_key) > 0:
                    return self._fail("Этот фон уже доступен")
                price = int(item["price"])
                if int(user["balance"]) < price:
                    return self._fail("Недостаточно mCoin")
                balance = self.db.add_balance(user["user_id"], -price)
                self.db.add_item(user["user_id"], item_key, 1)
                self.db.set_game_background(user["user_id"], key)
                fresh = self.db.user(user["user_id"])
                return self._json({"ok": True, "balance": balance,
                                   "bought": item["title"], "equipped": True,
                                   "user": self._public_user(fresh),
                                   **self._cosmetics_view(fresh)})
            if action == "equip":
                if not (int(item["price"]) == 0
                        or self.db.item_qty(user["user_id"], item_key) > 0):
                    return self._fail("Сначала купи этот фон")
                self.db.set_game_background(user["user_id"], key)
                fresh = self.db.user(user["user_id"])
                return self._json({"ok": True, "equipped": True,
                                   "user": self._public_user(fresh),
                                   **self._cosmetics_view(fresh)})
            return self._fail("Неизвестное действие")
        if kind not in ("avatar", "background"):
            return self._fail("Неизвестный вид оформления")
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        if kind == "avatar" and key == "custom":
            if action == "buy":
                return self._fail("Своё фото загружается отдельно")
            if not self.db.user_avatar(user["user_id"]):
                return self._fail("Своё фото ещё не загружено")
            self.db.set_custom_avatar_key(user["user_id"])
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "equipped": True,
                               "user": self._public_user(fresh),
                               **self._cosmetics_view(fresh)})
        catalog = game.AVATARS if kind == "avatar" else game.BACKGROUNDS
        item = next((entry for entry in catalog if entry["key"] == key), None)
        if not item:
            return self._fail("Оформление не найдено", 404)
        item_key = game.cosmetic_item_key(kind, key)
        if action == "buy":
            if int(item["price"]) == 0 or self.db.item_qty(user["user_id"], item_key) > 0:
                return self._fail("Это оформление уже доступно")
            price = int(item["price"])
            if int(user["balance"]) < price:
                return self._fail("Недостаточно mCoin")
            balance = self.db.add_balance(user["user_id"], -price)
            self.db.add_item(user["user_id"], item_key, 1)
            self.db.set_cosmetic(user["user_id"], kind, key)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "balance": balance, "bought": item["title"],
                               "equipped": True, "user": self._public_user(fresh),
                               **self._cosmetics_view(fresh)})
        if action == "equip":
            if not (int(item["price"]) == 0
                    or self.db.item_qty(user["user_id"], item_key) > 0):
                return self._fail("Сначала купи это оформление")
            self.db.set_cosmetic(user["user_id"], kind, key)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "equipped": True,
                               "user": self._public_user(fresh),
                               **self._cosmetics_view(fresh)})
        return self._fail("Неизвестное действие")

    async def prefix_equip(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", "")).strip()
        if key:
            prefix = game.PREFIX_BY_KEY.get(key)
            if not prefix:
                return self._fail("Префикс не найден", 404)
            if prefix.get("currency") == "role" and \
                    (user.get("role") or "user") != prefix.get("role"):
                return self._fail("Этот префикс доступен только с этой ролью", 403)
            if not self.db.has_prefix(user["user_id"], key):
                return self._fail("Префикс не куплен")
        if not self.db.equip_prefix(user["user_id"], key):
            return self._fail("Не удалось надеть префикс")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "prefix": key, "user": self._public_user(fresh)})

    async def upload_background(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        raw = str(body.get("image", ""))
        match = re.match(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", raw, re.S)
        if not match:
            return self._fail("Нужно фото в формате JPEG, PNG или WEBP")
        mime, payload = match.group(1), match.group(2)
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError):
            return self._fail("Не удалось прочитать изображение")
        if len(data) < 1000:
            return self._fail("Изображение слишком маленькое")
        if len(data) > game.CUSTOM_BG_MAX_BYTES:
            return self._fail("Файл слишком большой — до 400 КБ")
        self.db.set_user_background(user["user_id"], mime,
                                    base64.b64encode(data).decode("ascii"))
        self.db.set_game_background(user["user_id"], game.CUSTOM_BG_KEY)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "uploaded": True,
                           "user": self._public_user(fresh),
                           **self._cosmetics_view(fresh)})

    async def serve_background(self, request: web.Request) -> web.StreamResponse:
        try:
            user_id = int(request.match_info.get("user_id", "0"))
        except ValueError:
            raise web.HTTPNotFound()
        row = self.db.user_background(user_id)
        if not row:
            raise web.HTTPNotFound()
        try:
            data = base64.b64decode(row["data"])
        except (ValueError, TypeError):
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type=row["mime"],
                            headers={"Cache-Control": "public, max-age=300"})

    async def upload_avatar(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        raw = str(body.get("image", ""))
        match = re.match(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$", raw, re.S)
        if not match:
            return self._fail("Нужно фото в формате JPEG, PNG или WEBP")
        mime, payload = match.group(1), match.group(2)
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError):
            return self._fail("Не удалось прочитать изображение")
        if len(data) < 800:
            return self._fail("Изображение слишком маленькое")
        if len(data) > game.CUSTOM_BG_MAX_BYTES:
            return self._fail("Файл слишком большой — до 400 КБ")
        self.db.set_user_avatar(user["user_id"], mime,
                                base64.b64encode(data).decode("ascii"))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "uploaded": True,
                           "user": self._public_user(fresh),
                           **self._cosmetics_view(fresh)})

    async def serve_avatar(self, request: web.Request) -> web.StreamResponse:
        try:
            user_id = int(request.match_info.get("user_id", "0"))
        except ValueError:
            raise web.HTTPNotFound()
        row = self.db.user_avatar(user_id)
        if not row:
            raise web.HTTPNotFound()
        try:
            data = base64.b64decode(row["data"])
        except (ValueError, TypeError):
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type=row["mime"],
                            headers={"Cache-Control": "public, max-age=300"})

    def _insurance_refund(self, user: dict, bet: int) -> int:
        if not self.db.take_item(user["user_id"], "insurance"):
            return 0
        refund = min(int(bet * game.INSURANCE_REFUND), game.INSURANCE_CAP)
        if refund > 0:
            self.db.add_balance(user["user_id"], refund)
        return refund

    def _prefix_bonus(self, user: dict, payout: int) -> int:
        rate = game.prefix_bonus(user.get("prefix"))
        if rate <= 0 or payout <= 0:
            return payout
        return int(round(payout * (1 + rate)))

    def _charm_bonus(self, user: dict, payout: int) -> int:
        if payout <= 0:
            return payout
        if not self.db.take_item(user["user_id"], "charm"):
            return payout
        extra = int(payout * game.CHARM_BONUS)
        if extra <= 0:
            return payout
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
        return payout + bonus

    def _gold_pick(self, user: dict, payout: int) -> int:
        if payout <= 0:
            return payout
        if self.db.item_qty(user["user_id"], "gold_pick") <= 0:
            return payout
        bonus = int(payout * game.GOLD_PICK_BONUS)
        if bonus <= 0:
            return payout
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
        error = self._bet_error(user, bet, "crash")
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
            payout = self._prefix_bonus(user, payout)
        else:
            refund = self._insurance_refund(user, bet)

        self.db.add_balance(user["user_id"], payout - bet)
        self.db.add_play(uuid.uuid4().hex[:16], user["user_id"], "crash", bet, win, payout,
                         {"point": point, "target": target, "nonce": nonce})
        self._finish(user, bet, payout, multiplier or 1.0)
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
            **({"cheat": {"enabled": True, "game": "crash",
                          "point": point,
                          "hint": f"Ракета улетит на {point}× "
                                  f"({'выше' if win else 'ниже'}) цели {target}×"}}
               if self._is_admin(user) else {}),
        })

    async def shop(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        inv = self.db.inventory(user["user_id"])
        items = []
        for item in game.SHOP_ITEMS:
            entry = dict(item)
            charges = int(inv.get(item["key"], 0))
            entry["qty"] = charges
            entry["owned"] = (charges > 0
                              and item["key"] not in game.CONSUMABLE_KEYS)
            items.append(entry)
        bundles = []
        for bundle in game.SHOP_BUNDLES:
            entry = dict(bundle)
            entry["owned"] = all(inv.get(key, 0) > 0 for key in bundle["items"])
            bundles.append(entry)
        donate = []
        for item in game.DONATE_ITEMS:
            entry = dict(item)
            entry["qty"] = inv.get(item["key"], 0)
            donate.append(entry)
        owned_prefixes = self.db.user_prefixes(user["user_id"])
        level = game.level_view(user.get("xp") or 0)["level"]
        prefixes = []
        for prefix in game.PREFIXES:
            entry = dict(prefix)
            entry["owned"] = prefix["key"] in owned_prefixes
            entry["active"] = (user.get("prefix") or "") == prefix["key"]
            if prefix.get("currency") == "role":
                entry["available"] = (user.get("role") or "user") == prefix.get("role")
            else:
                entry["available"] = (
                    prefix["currency"] == "level"
                    and level >= int(prefix["level"])
                ) or (prefix["currency"] != "level"
                      and level >= int(prefix["level"]))
            prefixes.append(entry)
        return self._json({
            "ok": True,
            "balance": user["balance"],
            "gmpoint": user.get("gmpoint") or 0,
            "inventory": self._inventory_view(user),
            "items": items,
            "bundles": bundles,
            "donate": donate,
            "prefixes": prefixes,
        })

    async def shop_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        prefix = next((p for p in game.PREFIXES if p["key"] == key), None)
        if prefix:
            if prefix["currency"] == "role":
                if (user.get("role") or "user") != prefix.get("role"):
                    return self._fail("Этот префикс доступен только с этой ролью")
                self.db.add_prefix(user["user_id"], key)
                self.db.set_prefix(user["user_id"], key)
                fresh = self.db.user(user["user_id"])
                return self._json({
                    "ok": True,
                    "balance": fresh["balance"],
                    "gmpoint": fresh["gmpoint"],
                    "bought": f"префикс «{prefix['title']}»",
                    "prefix": key,
                    "inventory": self._inventory_view(fresh),
                })
            if prefix["currency"] == "level":
                return self._fail("Этот префикс выдаётся за уровень")
            if self.db.has_prefix(user["user_id"], key):
                return self._fail("Префикс уже куплен")
            price = int(prefix["price"])
            if prefix["currency"] == "gmpoint":
                if not self.db.spend_gmpoint(user["user_id"], price):
                    return self._fail("Недостаточно GMPOINT")
            else:
                if user["balance"] < price:
                    return self._fail("Недостаточно mCoin")
                self.db.add_balance(user["user_id"], -price)
            self.db.add_prefix(user["user_id"], key)
            self.db.set_prefix(user["user_id"], key)
            fresh = self.db.user(user["user_id"])
            return self._json({
                "ok": True,
                "balance": fresh["balance"],
                "gmpoint": fresh["gmpoint"],
                "bought": f"префикс «{prefix['title']}»",
                "prefix": key,
                "inventory": self._inventory_view(fresh),
            })

        donate = next((d for d in game.DONATE_ITEMS if d["key"] == key), None)
        if donate:
            price = int(donate["price"])
            unique_keys = {"relic_mines", "relic_dice", "relic_wheel",
                           "relic_crash", "gold_pick", "theme_neon", "theme_gold"}
            owned_any = any(
                key in unique_keys and self.db.item_qty(user["user_id"], key) > 0
                for key in donate["items"])
            if owned_any:
                return self._fail("Один из предметов набора у тебя уже есть")
            if not self.db.spend_gmpoint(user["user_id"], price):
                return self._fail("Недостаточно GMPOINT")
            for item_key, qty in donate["items"].items():
                if item_key == "charm":
                    qty *= game.CHARM_CHARGES
                self.db.add_item(user["user_id"], item_key, qty)
            fresh = self.db.user(user["user_id"])
            return self._json({
                "ok": True,
                "balance": fresh["balance"],
                "gmpoint": fresh["gmpoint"],
                "bought": donate["title"],
                "inventory": self._inventory_view(fresh),
            })

        entry = next((item for item in game.SHOP_ITEMS if item["key"] == key), None)
        grant = {key: int(entry.get("charges") or 1)} if entry else None
        if entry is None:
            bundle = next((b for b in game.SHOP_BUNDLES if b["key"] == key), None)
            if not bundle:
                return self._fail("Товар не найден", 404)
            entry = bundle
            grant = dict(bundle["items"])
        price = int(entry["price"])
        unique = {"relic_mines", "relic_dice", "relic_wheel", "relic_crash",
                  "theme_neon", "theme_gold", "gold_pick"}
        for item_key in (grant or {}):
            if item_key in unique and self.db.item_qty(user["user_id"], item_key) > 0:
                return self._fail("Этот предмет уже куплен")
        if user["balance"] < price:
            return self._fail("Недостаточно mCoin")
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

    async def shop_use(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        if key != "lootbox":
            return self._fail("Этот предмет нельзя открыть")
        if not self.db.take_item(user["user_id"], "lootbox"):
            return self._fail("Кейса удачи нет")
        nonce = self.db.bump_nonce(user["user_id"])
        reward = game.open_lootbox(user["server_seed"], user["client_seed"], nonce)
        if reward["kind"] == "coins":
            self.db.add_balance(user["user_id"], int(reward["amount"]))
            title = f"+{reward['amount']} mCoin"
        else:
            qty = int(reward.get("qty", 1))
            self.db.add_item(user["user_id"], reward["item"], qty)
            item = next((i for i in game.SHOP_ITEMS if i["key"] == reward["item"]),
                        None)
            title = f"{(item['title'] if item else reward['item'])} ×{qty}"
        awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({
            "ok": True,
            "reward": reward,
            "title": title,
            "balance": fresh["balance"],
            "inventory": self._inventory_view(fresh),
        })

    async def inventory_sell(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        try:
            qty = max(1, int(body.get("qty", 1)))
        except (TypeError, ValueError):
            qty = 1
        if not self.db.take_item(user["user_id"], key, qty):
            return self._fail("Предмета нет в инвентаре")
        price = int(game.sell_refund_price(key))
        if price <= 0:
            self.db.add_item(user["user_id"], key, qty)
            return self._fail("Этот предмет нельзя продать")
        total = price * qty
        self.db.add_balance(user["user_id"], total)
        fresh = self.db.user(user["user_id"])
        return self._json({
            "ok": True,
            "sold": key,
            "qty": qty,
            "total": total,
            "balance": fresh["balance"],
            "inventory": self._inventory_view(fresh),
            "sections": self._inventory_sections(fresh),
        })

    async def inventory_use(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        key = str(body.get("key", ""))
        try:
            qty = max(1, int(body.get("qty", 1)))
        except (TypeError, ValueError):
            qty = 1
        if key != "lootbox":
            return self._fail("Этот предмет нельзя использовать напрямую")
        if self.db.item_qty(user["user_id"], "lootbox") < qty:
            return self._fail("Не хватает кейсов удачи")
        total_coins = 0
        rewards: dict[str, int] = {}
        for _ in range(qty):
            self.db.take_item(user["user_id"], "lootbox", 1)
            nonce = self.db.bump_nonce(user["user_id"])
            reward = game.open_lootbox(
                user["server_seed"], user["client_seed"], nonce)
            if reward["kind"] == "coins":
                total_coins += int(reward["amount"])
            else:
                rq = int(reward.get("qty", 1))
                rewards[reward["item"]] = rewards.get(reward["item"], 0) + rq
        if total_coins > 0:
            self.db.add_balance(user["user_id"], total_coins)
        for item_key, rq in rewards.items():
            self.db.add_item(user["user_id"], item_key, rq)
        parts = []
        if total_coins > 0:
            parts.append(f"+{total_coins} mCoin")
        for item_key, rq in rewards.items():
            item = next((i for i in game.SHOP_ITEMS if i["key"] == item_key), None)
            parts.append(f"{(item['title'] if item else item_key)} ×{rq}")
        title = ", ".join(parts) if parts else "ничего"
        awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({
            "ok": True,
            "count": qty,
            "title": f"Открыто {qty}: {title}",
            "balance": fresh["balance"],
            "sections": self._inventory_sections(fresh),
        })

    # --- admin -----------------------------------------------------------
    @staticmethod
    async def _body(request: web.Request) -> dict:
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    async def hourly(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        amount = self.db.claim_hourly(user["user_id"], int(time.time()),
                                      game.HOURLY_COOLDOWN,
                                      int(self._settings().get("hourly_bonus",
                                                                 game.HOURLY_BONUS)))
        if amount is None:
            return self._fail("Бонус ещё не готов", 429)
        earned = awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "amount": amount, "awards": earned,
                           "balance": fresh["balance"],
                           "user": self._public_user(fresh)})

    async def spin(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        now = int(time.time())
        if now - int(user.get("last_spin") or 0) < game.SPIN_COOLDOWN:
            return self._fail("Крутить можно раз в 12 часов", 429)
        nonce = self.db.bump_nonce(user["user_id"])
        index, prize = game.spin_daily(user["server_seed"], user["client_seed"], nonce)
        day = int(user.get("spin_day") or 1)
        next_day = day + 1 if day < game.SPIN_STREAK_DAYS else 1
        if prize["kind"] == "coins":
            self.db.add_balance(user["user_id"], prize["amount"])
        elif prize["kind"] == "gmpoint":
            self.db.add_gmpoint(user["user_id"], prize["amount"])
        else:
            qty = game.CHARM_CHARGES if prize["item"] == "charm" else 1
            self.db.add_item(user["user_id"], prize["item"], qty)
        self.db.mark_spin(user["user_id"], now, next_day)
        earned = awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "index": index, "prize": self._prize_view(prize),
                           "day": day, "next_day": next_day, "awards": earned,
                           "balance": fresh["balance"],
                           "user": self._public_user(fresh)})

    async def invite_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        try:
            step = int(body.get("step", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная ступень")
        reward = next((item["reward"] for item in game.REF_LADDER
                       if item["step"] == step), None)
        if reward is None:
            return self._fail("Некорректная ступень")
        refs = self.db.referrals(user["user_id"])
        if refs["total"] < step:
            return self._fail("Не хватает приглашённых")
        if not self.db.invite_claim(user["user_id"], step):
            return self._fail("Награда уже получена")
        self.db.add_balance(user["user_id"], reward)
        earned = awards.evaluate(self.db, user["user_id"])
        balance = self.db.user(user["user_id"])["balance"]
        return self._json({"ok": True, "step": step, "reward": reward,
                           "awards": earned, "balance": balance})

    async def _channel_member(self, channel: str, user_id: int) -> bool:
        if not config.bot_token:
            return False
        url = f"https://api.telegram.org/bot{config.bot_token}/getChatMember"
        params = {"chat_id": "@" + channel, "user_id": user_id}
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    data = await resp.json()
        except Exception:
            return False
        if not data.get("ok"):
            return False
        status = data.get("result", {}).get("status")
        return status in ("member", "administrator", "creator")

    async def sponsor_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        channel = str(body.get("channel", "")).lstrip("@").lower()
        if channel not in config.sponsor_channels:
            return self._fail("Неизвестный спонсор", 404)
        if not config.bot_token:
            return self._fail("Спонсоры пока недоступны")
        if not await self._channel_member(channel, user["user_id"]):
            return self._fail("Подписка не найдена")
        if not self.db.sponsor_claim(user["user_id"], channel):
            return self._fail("Награда уже получена")
        self.db.add_balance(user["user_id"], game.SPONSOR_REWARD)
        earned = awards.evaluate(self.db, user["user_id"])
        balance = self.db.user(user["user_id"])["balance"]
        return self._json({"ok": True, "channel": "@" + channel,
                           "reward": game.SPONSOR_REWARD, "awards": earned,
                           "balance": balance})

    async def deposit_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        try:
            amount = int(body.get("amount", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректная сумма")
        if not (game.DEPOSIT_MIN <= amount <= game.DEPOSIT_MAX):
            return self._fail(f"Сумма от {game.DEPOSIT_MIN} до {game.DEPOSIT_MAX}")
        if int(user["balance"]) < amount:
            return self._fail("Недостаточно средств")
        now = int(time.time())
        if str(body.get("kind", "fixed")) == "savings":
            savings = self.db.savings(user["user_id"])
            if savings:
                interest = game.savings_interest(
                    savings["amount"], savings["rate_bps"],
                    now - int(savings["started_at"]))
                if interest > 0:
                    self.db.add_balance(user["user_id"], interest)
                self.db.update_savings(savings["id"], savings["amount"] + amount, now)
                dep_id = savings["id"]
            else:
                dep_id = uuid.uuid4().hex[:12]
                self.db.create_deposit(dep_id, user["user_id"], "savings", amount,
                                       game.SAVINGS_RATE_BPS, now, None)
            self.db.add_balance(user["user_id"], -amount)
            earned = awards.evaluate(self.db, user["user_id"])
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "id": dep_id, "awards": earned,
                               "balance": fresh["balance"],
                               "deposits": self._deposits_view(fresh)})
        try:
            days = int(body.get("days", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректный срок")
        plan = next((p for p in game.DEPOSIT_PLANS if p["days"] == days), None)
        if not plan:
            return self._fail("Некорректный срок")
        dep_id = uuid.uuid4().hex[:12]
        self.db.add_balance(user["user_id"], -amount)
        self.db.create_deposit(dep_id, user["user_id"], "fixed", amount,
                               plan["rate_bps"], now, now + days * 86400)
        earned = awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "id": dep_id, "awards": earned,
                           "balance": fresh["balance"],
                           "deposits": self._deposits_view(fresh)})

    async def deposit_close(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        dep_id = str(body.get("id", ""))
        row = self.db.deposit(dep_id)
        if not row or row["user_id"] != user["user_id"] or row["status"] != "active":
            return self._fail("Депозит не найден", 404)
        now = int(time.time())
        if row["kind"] == "fixed":
            if now < int(row["ends_at"] or 0):
                return self._fail("Депозит ещё не закрылся")
            payout = row["amount"] + game.deposit_interest(row["amount"], row["rate_bps"])
        else:
            payout = row["amount"] + game.savings_interest(
                row["amount"], row["rate_bps"], now - int(row["started_at"]))
        if not self.db.close_deposit(dep_id, payout, now):
            return self._fail("Депозит уже закрыт")
        self.db.add_balance(user["user_id"], payout)
        earned = awards.evaluate(self.db, user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "payout": payout, "awards": earned,
                           "balance": fresh["balance"],
                           "deposits": self._deposits_view(fresh)})

    async def admin_overview(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        return self._json({
            "ok": True,
            "stats": self.db.admin_stats(),
            "games": self.db.admin_game_stats(),
            "economy": self.db.admin_economy(),
            "duels": self.db.admin_duels(8),
            "settings": self._public_settings(),
            "recent": self.db.admin_recent(12),
        })

    async def admin_users(self, request: web.Request) -> web.Response:
        admin, err = self._require_staff(request)
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
        admin, err = self._require_staff(request)
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
        admin, err = self._require_staff(request)
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

    @staticmethod
    def _catalog_keys(items) -> dict:
        out = {}
        for item in items:
            if isinstance(item, dict) and item.get("key"):
                out[item["key"]] = item.get("title") or item.get("name") or item["key"]
        return out

    def _grant_catalogs(self) -> dict:
        prefixes = self._catalog_keys(game.PREFIXES)
        for cp in self.db.custom_prefixes():
            prefixes[str(cp["key"])] = f"{cp['title']} · кастомный"
        return {
            "item": self._catalog_keys(game.SHOP_ITEMS),
            "prefix": prefixes,
            "avatar": self._catalog_keys(game.AVATARS),
            "background": self._catalog_keys(game.GAME_BACKGROUNDS),
            "rod": self._catalog_keys(game.RODS),
            "achievement": {key: (ach.get("title") or key)
                            for key, ach in game.ACHIEVEMENT_BY_KEY.items()},
        }

    async def admin_catalog(self, request: web.Request) -> web.Response:
        admin, err = self._require_staff(request)
        if err:
            return err
        catalogs = self._grant_catalogs()
        return self._json({
            "ok": True,
            "kinds": ["item", "prefix", "avatar", "background", "rod",
                      "achievement", "money", "gmpoint"],
            "catalog": {kind: [{"key": key, "title": title}
                               for key, title in items.items()]
                        for kind, items in catalogs.items()},
        })

    async def admin_grant(self, request: web.Request) -> web.Response:
        admin, err = self._require_staff(request)
        if err:
            return err
        body = await self._body(request)
        try:
            target = int(body.get("user_id", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректные данные")
        user = self.db.user(target)
        if not user:
            return self._fail("Игрок не найден", 404)
        kind = str(body.get("kind", "item") or "item").lower()
        key = str(body.get("item") or body.get("key") or "").strip()
        try:
            qty = int(body.get("qty", 1))
        except (TypeError, ValueError):
            return self._fail("Некорректное количество")

        if kind == "money":
            try:
                amount = int(body.get("amount", qty))
            except (TypeError, ValueError):
                return self._fail("Некорректная сумма")
            if amount == 0:
                return self._fail("Сумма не может быть нулём")
            amount = max(-1_000_000_000, min(1_000_000_000, amount))
            new_balance = max(0, int(user["balance"]) + amount)
            balance = self.db.admin_set_balance(target, new_balance)
            self.db.admin_log(admin["user_id"], target, "grant_money",
                              {"delta": amount})
            return self._json({"ok": True, "kind": kind, "amount": amount,
                               "balance": balance})

        if kind == "gmpoint":
            try:
                amount = int(body.get("amount", qty))
            except (TypeError, ValueError):
                return self._fail("Некорректная сумма")
            value = max(-1_000_000, min(1_000_000, amount))
            points = self.db.add_gmpoint(target, value) if value > 0 else \
                self.db.set_gmpoint(target, max(0, int(user.get("gmpoint") or 0) + value))
            self.db.admin_log(admin["user_id"], target, "grant_gmpoint",
                              {"delta": value})
            return self._json({"ok": True, "kind": kind, "amount": value,
                               "gmpoint": points})

        catalogs = self._grant_catalogs()
        catalog = catalogs.get(kind)
        if catalog is None:
            return self._fail("Неизвестный тип награды", 400)
        if key not in catalog:
            return self._fail(f"Неизвестный ключ: {key}", 404)

        qty = max(1, min(999, qty))
        if kind == "item":
            if key == "charm":
                qty *= game.CHARM_CHARGES
            total = self.db.add_item(target, key, qty)
        elif kind == "prefix":
            self.db.add_prefix(target, key)
            total = 1
        elif kind in ("avatar", "background"):
            if not self.db.set_cosmetic(target, kind, key):
                return self._fail("Не удалось выдать", 400)
            total = 1
        elif kind == "rod":
            self.db.set_rod(target, key)
            total = 1
        else:
            total = 1 if self.db.claim_achievement(target, key) else 1

        self.db.admin_log(admin["user_id"], target, "grant",
                          {"kind": kind, "item": key, "qty": qty})
        return self._json({
            "ok": True,
            "user_id": target,
            "kind": kind,
            "item": key,
            "title": catalog[key],
            "qty": total,
        })

    async def admin_role(self, request: web.Request) -> web.Response:
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
        role = str(body.get("role", "user")).strip().lower()
        if role not in ("user", "tester", "moderator", "admin", "owner"):
            return self._fail("Неизвестная роль")
        if role == "owner" and (admin.get("role") or "user") != "owner" \
                and admin["user_id"] not in config.admin_ids:
            return self._fail("Роль владельца может выдать только владелец")
        if target == admin["user_id"] and role not in ("admin", "owner"):
            return self._fail("Нельзя снять роль с самого себя")
        if target in config.admin_ids and role not in ("admin", "owner"):
            return self._fail("Этот игрок админ из настроек бота")
        self.db.admin_set_role(target, role)
        prefix_key = game.role_prefix(role)
        if prefix_key:
            self.db.add_prefix(target, prefix_key)
            self.db.set_prefix(target, prefix_key)
        self.db.admin_log(admin["user_id"], target, "role", {"role": role})
        return self._json({"ok": True, "user_id": target, "role": role})

    async def admin_gmpoint(self, request: web.Request) -> web.Response:
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
        if value == 0 or abs(value) > 100000:
            return self._fail("Сумма GMPOINT: от 1 до 100000")
        result = self.db.add_gmpoint(target, value)
        if result is None:
            return self._fail("Недостаточно GMPOINT у игрока")
        self.db.admin_log(admin["user_id"], target, "gmpoint", {"delta": value})
        return self._json({"ok": True, "user_id": target, "gmpoint": result})

    async def admin_custom_prefix(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        action = str(body.get("action", "list")).strip() or "list"
        if action == "list":
            items = [
                {"key": str(c["key"]), "title": str(c["title"]),
                 "color": str(c["color"]), "color2": str(c.get("color2") or ""),
                 "style": str(c["style"]), "bonus": float(c.get("bonus") or 0.0)}
                for c in self.db.custom_prefixes()
            ]
            return self._json({"ok": True, "items": items})
        if action == "delete":
            key = str(body.get("key", "")).strip()
            if not key or not key.startswith("custom_"):
                return self._fail("Некорректный ключ префикса")
            self.db.delete_custom_prefix(key)
            try:
                game.register_custom_prefixes(self.db.custom_prefixes())
            except Exception:
                pass
            return self._json({"ok": True, "deleted": key})
        if action == "create":
            title = str(body.get("title", "")).strip()
            color = str(body.get("color", "#ffd166")).strip()
            color2 = str(body.get("color2", "")).strip()
            style = str(body.get("style", "solid")).strip()
            try:
                bonus = float(body.get("bonus", 0))
            except (TypeError, ValueError):
                return self._fail("Бонус: число от 0 до 1")
            if not title or len(title) > 24:
                return self._fail("Название: 1–24 символа")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or \
               (color2 and not re.fullmatch(r"#[0-9a-fA-F]{6}", color2)):
                return self._fail("Цвет: HEX вида #RRGGBB")
            if style not in game.PREFIX_STYLES:
                return self._fail("Некорректный стиль")
            bonus = max(0.0, min(0.5, bonus))
            key = "custom_" + hashlib.sha1(
                (title + str(time.time())).encode()).hexdigest()[:8]
            self.db.upsert_custom_prefix(key, title, color, color2, style, bonus)
            try:
                game.register_custom_prefixes(self.db.custom_prefixes())
            except Exception:
                pass
            return self._json({"ok": True, "key": key, "title": title,
                               "color": color, "color2": color2,
                               "style": style, "bonus": bonus})
        return self._fail("Неизвестное действие")

    async def admin_promo_create(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        code = str(body.get("code", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{3,32}", code):
            return self._fail("Код: 3–32 символа, латиница, цифры, _ и -")
        try:
            amount = int(body.get("amount", 0))
            max_uses = int(body.get("max_uses", 0))
            days = int(body.get("days", 0))
        except (TypeError, ValueError):
            return self._fail("Некорректные числа")
        if amount < 1 or amount > 100000:
            return self._fail("Сумма GMPOINT: от 1 до 100000")
        max_uses = max(0, min(100000, max_uses))
        days = max(0, min(365, days))
        expires = int(time.time()) + days * 86400 if days else None
        if self.db.promo(code):
            return self._fail("Такой промокод уже есть", 409)
        self.db.create_promo(code, amount, max_uses, 0, 1, expires, "",
                             "gmpoint")
        self.db.admin_log(admin["user_id"], None, "promo_create",
                          {"code": code, "amount": amount})
        return self._json({"ok": True, "code": code, "amount": amount})

    async def admin_promo_list(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        return self._json({"ok": True, "items": self.db.promos(100)})

    async def admin_promo_delete(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err:
            return err
        body = await self._body(request)
        code = str(body.get("code", "")).strip().upper()
        if not self.db.delete_promo(code):
            return self._fail("Промокод не найден", 404)
        return self._json({"ok": True, "code": code})

    async def promo_redeem(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if user.get("is_banned"):
            return self._fail("Аккаунт заблокирован", 403)
        body = await self._body(request)
        code = str(body.get("code", "")).strip().upper()
        if not code:
            return self._fail("Введите промокод")
        status, amount = self.db.claim_promo(code, user["user_id"],
                                             int(time.time()))
        messages = {
            "not_found": "Промокод не найден",
            "inactive": "Промокод больше не действует",
            "expired": "Срок действия промокода истёк",
            "already": "Вы уже активировали этот промокод",
            "exhausted": "Лимит активаций исчерпан",
        }
        if status != "ok":
            return self._fail(messages.get(status, "Не удалось активировать"))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "amount": amount,
                           "gmpoint": fresh["gmpoint"],
                           "user": self._public_user(fresh)})

    async def admin_rounds(self, request: web.Request) -> web.Response:
        admin, err = self._require_staff(request)
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
                   "daily_bonus", "hourly_bonus", "chat_url", "maintenance",
                   "game_mines", "game_dice", "game_wheel", "game_crash",
                   "game_roulette", "game_slots", "game_coinflip", "game_blackjack",
                   "game_basket", "game_darts")
        updates: dict[str, int] = {}
        for key in allowed:
            if key not in body:
                continue
            if key == "chat_url":
                updates[key] = str(body[key]).strip()
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
        if merged.get("hourly_bonus", 0) < 0 or merged.get("hourly_bonus", 0) > 1_000_000:
            return self._fail("Некорректный часовой бонус")
        if merged.get("chat_url", "") and not str(merged["chat_url"]).startswith(("https://", "http://")):
            return self._fail("Ссылка на чат должна начинаться с http(s)://")
        if merged["maintenance"] not in (0, 1):
            return self._fail("Техработы: 0 или 1")
        for key in ("game_mines", "game_dice", "game_wheel", "game_crash",
                    "game_roulette", "game_slots", "game_coinflip", "game_blackjack",
                    "game_basket"):
            if merged.get(key, 1) not in (0, 1):
                return self._fail(f"Флаг игры {key}: только 0 или 1")

        saved = self.db.set_settings(updates)
        return self._json({"ok": True, "settings": saved})


def build_app(db: Database) -> web.Application:
    api = Api(db)
    try:
        game.register_custom_prefixes(db.custom_prefixes())
    except Exception:
        pass

    @web.middleware
    async def overload_guard(request: web.Request, handler):
        if api._inflight >= 300:
            return web.json_response(
                {"ok": False, "error": "Сервер перегружен — попробуйте через минуту"},
                status=503)
        api._inflight += 1
        try:
            return await handler(request)
        finally:
            api._inflight -= 1

    app = web.Application(client_max_size=1024 * 1024,
                          middlewares=[overload_guard])
    app["api"] = api

    app.router.add_post("/api/state", api.state)
    app.router.add_post("/api/auth/register", api.auth_register)
    app.router.add_post("/api/auth/login", api.auth_login)
    app.router.add_post("/api/auth/logout", api.auth_logout)
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
    app.router.add_post("/api/games/coinflip", api.coinflip)
    app.router.add_post("/api/games/basket", api.basket)
    app.router.add_post("/api/games/darts", api.darts)
    app.router.add_post("/api/fish/catch", api.fish_catch)
    app.router.add_post("/api/fish/grab", api.fish_grab)
    app.router.add_post("/api/fish/list", api.fish_list)
    app.router.add_post("/api/fish/sell", api.fish_sell)
    app.router.add_post("/api/fish/rods", api.fish_rods)
    app.router.add_post("/api/transfer", api.transfer)
    app.router.add_post("/api/transfers", api.transfers)
    app.router.add_post("/api/promo", api.promo)
    app.router.add_post("/api/updates", api.updates_list)
    app.router.add_post("/api/games/bj/start", api.bj_start)
    app.router.add_post("/api/games/bj/hit", api.bj_hit)
    app.router.add_post("/api/games/bj/stand", api.bj_stand)
    app.router.add_post("/api/games/bj/double", api.bj_double)
    app.router.add_post("/api/quests", api.quests)
    app.router.add_post("/api/quests/claim", api.quest_claim)
    app.router.add_post("/api/levels/claim", api.level_claim)
    app.router.add_post("/api/shop", api.shop)
    app.router.add_post("/api/inventory", api.inventory)
    app.router.add_post("/api/inventory/sell", api.inventory_sell)
    app.router.add_post("/api/inventory/use", api.inventory_use)
    app.router.add_post("/api/shop/buy", api.shop_buy)
    app.router.add_post("/api/shop/use", api.shop_use)
    app.router.add_post("/api/prefix/equip", api.prefix_equip)
    app.router.add_post("/api/profile/cosmetics", api.profile_cosmetics)
    app.router.add_post("/api/profile/background/upload", api.upload_background)
    app.router.add_post("/api/profile/avatar/upload", api.upload_avatar)
    app.router.add_get("/api/profile/background/{user_id}", api.serve_background)
    app.router.add_get("/api/profile/avatar/{user_id}", api.serve_avatar)
    app.router.add_post("/api/bonus/hourly", api.hourly)
    app.router.add_post("/api/spin", api.spin)
    app.router.add_post("/api/invites/claim", api.invite_claim)
    app.router.add_post("/api/sponsors/claim", api.sponsor_claim)
    app.router.add_post("/api/deposits/create", api.deposit_create)
    app.router.add_post("/api/deposits/close", api.deposit_close)
    app.router.add_post("/api/admin/overview", api.admin_overview)
    app.router.add_post("/api/admin/users", api.admin_users)
    app.router.add_post("/api/admin/balance", api.admin_balance)
    app.router.add_post("/api/admin/ban", api.admin_ban)
    app.router.add_post("/api/admin/grant", api.admin_grant)
    app.router.add_post("/api/admin/catalog", api.admin_catalog)
    app.router.add_post("/api/admin/role", api.admin_role)
    app.router.add_post("/api/admin/gmpoint", api.admin_gmpoint)
    app.router.add_post("/api/admin/custom-prefix", api.admin_custom_prefix)
    app.router.add_post("/api/admin/promo/create", api.admin_promo_create)
    app.router.add_post("/api/admin/promo/list", api.admin_promo_list)
    app.router.add_post("/api/admin/promo/delete", api.admin_promo_delete)
    app.router.add_post("/api/promo/redeem", api.promo_redeem)
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
