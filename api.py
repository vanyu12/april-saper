import random
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from datetime import datetime
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
            "max_bet": raw.get("max_bet", 100000000),
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
        out = []
        medals = ("🥇", "🥈", "🥉")
        for i, row in enumerate(rows):
            entry = self._decorate_row(row)
            entry["place"] = i + 1
            entry["medal"] = medals[i] if i < 3 else ""
            out.append(entry)
        return out

    def _maybe_weekly_rewards(self) -> None:
        """По понедельникам награждает топ-3 по балансу, множителю и уровню."""
        now = datetime.now()
        if now.weekday() != 0:
            return
        week = now.strftime("%G-W%V")
        settings = self.db.settings()
        if str(settings.get("weekly_reward_week") or "") == week:
            return
        # Подарки за место в топе: (gmpoint, mCoin).
        tiers = {1: (100, 50_000), 2: (60, 20_000), 3: (30, 10_000)}
        awarded = {}
        for rows in (self.db.leaderboard(3), self.db.top_multiplier(3),
                     self.db.top_by_level(3)):
            for place, row in enumerate(rows, start=1):
                uid = int(row["user_id"])
                gmp, coins = tiers.get(place, (0, 0))
                if gmp or coins:
                    awarded.setdefault(uid, [0, 0])
                    awarded[uid][0] += gmp
                    awarded[uid][1] += coins
        for uid, (gmp, coins) in awarded.items():
            if coins:
                self.db.add_balance(uid, coins)
            if gmp:
                self.db.add_gmpoint(uid, gmp)
        self.db.set_settings({"weekly_reward_week": week})

    async def state(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self._maybe_weekly_rewards()
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
        active = self.db.active_round(user["user_id"])
        if active:
            age = int(time.time()) - int(active.get("created_at") or 0)
            if age < game.ROUND_TTL:
                return self._fail("Сначала завершите текущую игру")
            refund = self.db.expire_round(active["id"])
            if refund:
                self.db.add_balance(user["user_id"], refund)
                user = self.db.user(user["user_id"]) or user
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
        capped = mult >= game.MINES_MAX_MULT
        finished = len(opened) >= safe or capped
        target = float(rnd.get("auto_target") or 0)
        auto = bool(target) and not finished and mult >= target
        payout = game.payout_for(rnd["bet"], mult) if (finished or auto) else 0
        if finished or auto:
            payout = self._charm_bonus(user, payout)
            payout = self._apply_relic(user, "mines", payout)
            payout = self._gold_pick(user, payout)
        status = "won" if len(opened) >= safe else ("cashed" if (auto or capped) else "active")
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
            "capped": capped,
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
        # Жёсткий потолок выигрыша за одну партию — защита от взрывного роста баланса.
        if payout > game.MAX_WIN:
            self.db.add_balance(user["user_id"], game.MAX_WIN - payout)
            payout = game.MAX_WIN
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
            "weekly": [{"place": 1, "gmpoint": 100, "coins": 50000},
                       {"place": 2, "gmpoint": 60, "coins": 20000},
                       {"place": 3, "gmpoint": 30, "coins": 10000}],
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
        gap = (0.35 if game_key in ("dice", "wheel", "crash", "coinflip", "basket")
               else 0.12) * limit
        if gap > 0:
            last = self._last_action.get(user["user_id"], 0.0)
            if now - last < gap:
                return "Слишком быстро — подождите немного"
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
        active_bj = self.db.active_bj(user["user_id"])
        if active_bj:
            age = int(time.time()) - int(active_bj.get("created_at") or 0)
            if age < game.BJ_TTL:
                return self._fail("Сначала завершите текущую партию в «21»")
            refund = self.db.expire_bj(active_bj["id"])
            if refund:
                self.db.add_balance(user["user_id"], refund)
                user = self.db.user(user["user_id"]) or user
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

        player = list(rnd["player"])
        dealer = list(rnd["dealer"])
        index = len(player) + len(dealer)
        if index >= len(rnd["deck"]):
            return self._fail("Колода закончилась")
        self.db.add_balance(user["user_id"], -rnd["bet"])
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
        if amount > game.TRANSFER_MAX_PER_OP:
            return self._fail(f"Максимум за один перевод: {game.TRANSFER_MAX_PER_OP} mCoin")
        sent = self.db.daily_transfer_sent(user["user_id"])
        if sent + amount > game.TRANSFER_DAILY_LIMIT:
            return self._fail(
                f"Суточный лимит переводов: {game.TRANSFER_DAILY_LIMIT} mCoin "
                f"(сегодня уже переведено {sent})")
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
        fresh = self.db.user(user["user_id"])
        promo = self.db.promo(code) or {}
        currency = str(promo.get("currency") or "mcoin")
        return self._json({"ok": True, "amount": amount, "balance": balance,
                           "gmpoint": fresh.get("gmpoint") or 0,
                           "currency": currency,
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

    async def profile_stats(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        by_game = self.db.user_game_stats(user["user_id"])
        total_rounds = sum(item["rounds"] for item in by_game)
        total_wagered = sum(item["wagered"] for item in by_game)
        total_paid = sum(item["paid"] for item in by_game)
        total_wins = sum(item["wins"] for item in by_game)
        return self._json({
            "ok": True,
            "by_game": by_game,
            "summary": {
                "rounds": total_rounds,
                "wagered": total_wagered,
                "paid": total_paid,
                "wins": total_wins,
                "winrate": round((total_wins / total_rounds) * 100, 1) if total_rounds else 0.0,
                "rtp": round((total_paid / total_wagered) * 100, 1) if total_wagered else 0.0,
            },
        })

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
                   "game_basket", "game_darts", "game_fishing")
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
        if merged["max_bet"] > 100_000_000:
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

    # --- кланы -----------------------------------------------------------
    async def clans(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        top = self.db.top_clans(50)
        view = []
        for c in top:
            view.append({
                "id": c["id"], "name": c["name"], "tag": c["tag"],
                "level": c["level"], "xp": c["xp"], "members": c["members"],
                "description": c["description"], "logo": c["logo"],
                "owner_id": c["owner_id"],
            })
        my = self.db.user_clan(user["user_id"])
        return self._json({"ok": True, "clans": view,
                           "my": self._clan_view(my) if my else None})

    def _clan_view(self, c: dict) -> dict:
        members = self.db.clan_members(c["id"])
        return {
            "id": c["id"], "name": c["name"], "tag": c["tag"],
            "level": c["level"], "xp": c["xp"],
            "members": [{
                "user_id": m["user_id"], "username": m.get("username"),
                "first_name": m.get("first_name"), "role": m["role"],
                "balance": m.get("balance", 0), "xp": m.get("xp", 0),
            } for m in members],
            "description": c["description"], "logo": c["logo"],
            "owner_id": c["owner_id"], "my_role": c.get("my_role", ""),
            "created_at": c["created_at"],
        }

    async def clan_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        name = str(body.get("name") or "").strip()
        tag = str(body.get("tag") or "").strip()
        description = str(body.get("description") or "").strip()
        if len(name) < 2 or len(name) > 20:
            return self._fail("Название клана: 2–20 символов")
        if len(tag) < 2 or len(tag) > 5:
            return self._fail("Тег клана: 2–5 символов")
        if self.db.clan_by_name(name):
            return self._fail("Клан с таким названием уже есть")
        if self.db.user_clan(user["user_id"]):
            return self._fail("Вы уже состоите в клане")
        clan_id = str(uuid.uuid4())
        if not self.db.create_clan(clan_id, name, tag.upper(), user["user_id"],
                                   description):
            return self._fail("Не удалось создать клан")
        return self._json({"ok": True, "clan_id": clan_id})

    async def clan_join(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        clan_id = str(body.get("clan_id") or "")
        clan = self.db.clan(clan_id)
        if not clan:
            return self._fail("Клан не найден")
        if self.db.user_clan(user["user_id"]):
            return self._fail("Вы уже состоите в клане")
        if self.db.clan_request_by_user(clan_id, user["user_id"]):
            return self._fail("Заявка уже отправлена")
        if not self.db.clan_request(clan_id, user["user_id"]):
            return self._fail("Не удалось отправить заявку")
        self.db.notify(clan["owner_id"], "clan_request",
                       f"Новая заявка в «{clan['name']}»",
                       f"@{user.get('username') or 'игрок'} хочет вступить в клан")
        return self._json({"ok": True})

    async def clan_leave(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my:
            return self._fail("Вы не в клане")
        if my["my_role"] == "owner":
            return self._fail("Владелец не может выйти — передайте лидерство или распустите клан")
        self.db.remove_clan_member(my["id"], user["user_id"])
        return self._json({"ok": True})

    async def clan_kick(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my:
            return self._fail("Вы не в клане")
        if my["my_role"] not in ("owner", "officer"):
            return self._fail("Недостаточно прав")
        body = await self._body(request)
        target_id = int(body.get("user_id") or 0)
        target = self.db.user(target_id)
        if not target:
            return self._fail("Игрок не найден")
        if target_id == user["user_id"]:
            return self._fail("Нельзя кикнуть себя")
        self.db.remove_clan_member(my["id"], target_id)
        return self._json({"ok": True})

    async def clan_promote(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] != "owner":
            return self._fail("Только владелец может менять роли")
        body = await self._body(request)
        target_id = int(body.get("user_id") or 0)
        role = str(body.get("role") or "member")
        if role not in ("owner", "officer", "member"):
            return self._fail("Некорректная роль")
        if role == "owner":
            self.db.set_clan_role(my["id"], user["user_id"], "officer")
            self.db.set_clan_role(my["id"], target_id, "owner")
            self.db.add_clan_xp(my["id"], 5)
        else:
            self.db.set_clan_role(my["id"], target_id, role)
        return self._json({"ok": True})

    async def clan_update(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] != "owner":
            return self._fail("Только владелец может менять клан")
        body = await self._body(request)
        description = str(body.get("description") or "").strip()
        logo = str(body.get("logo") or "").strip()
        self.db.update_clan(my["id"], description, logo)
        return self._json({"ok": True})

    async def clan_requests(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] not in ("owner", "officer"):
            return self._fail("Недостаточно прав")
        return self._json({"ok": True,
                           "requests": self.db.clan_requests(my["id"])})

    async def clan_accept(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] not in ("owner", "officer"):
            return self._fail("Недостаточно прав")
        body = await self._body(request)
        target_id = int(body.get("user_id") or 0)
        if self.db.user_clan(target_id):
            self.db.remove_clan_request(my["id"], target_id)
            return self._fail("Игрок уже в другом клане")
        if not self.db.add_clan_member(my["id"], target_id):
            self.db.remove_clan_request(my["id"], target_id)
            return self._fail("Не удалось принять")
        self.db.remove_clan_request(my["id"], target_id)
        self.db.add_clan_xp(my["id"], 10)
        self.db.notify(target_id, "clan", "Вас приняли в клан",
                       f"Клан «{my['name']}» принял вашу заявку")
        return self._json({"ok": True})

    async def clan_decline(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] not in ("owner", "officer"):
            return self._fail("Недостаточно прав")
        body = await self._body(request)
        self.db.remove_clan_request(my["id"], int(body.get("user_id") or 0))
        return self._json({"ok": True})

    async def clan_invite(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] not in ("owner", "officer"):
            return self._fail("Недостаточно прав")
        body = await self._body(request)
        target_id = int(body.get("user_id") or 0)
        target = self.db.user(target_id)
        if not target:
            return self._fail("Игрок не найден")
        self.db.clan_invite(my["id"], target_id)
        self.db.notify(target_id, "clan", "Приглашение в клан",
                       f"Клан «{my['name']}» приглашает вас")
        return self._json({"ok": True})

    async def clan_accept_invite(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        clan_id = str(body.get("clan_id") or "")
        if self.db.user_clan(user["user_id"]):
            return self._fail("Вы уже в клане")
        if not self.db.add_clan_member(clan_id, user["user_id"]):
            return self._fail("Не удалось вступить")
        self.db.remove_clan_invite(clan_id, user["user_id"])
        self.db.add_clan_xp(clan_id, 10)
        clan = self.db.clan(clan_id)
        if clan:
            self.db.notify(clan["owner_id"], "clan",
                           "Новый участник",
                           f"@{user.get('username') or 'игрок'} вступил в клан")
        return self._json({"ok": True})

    async def clan_decline_invite(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        self.db.remove_clan_invite(str(body.get("clan_id") or ""),
                                   user["user_id"])
        return self._json({"ok": True})

    async def clan_msg(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my:
            return self._fail("Вы не в клане")
        body = await self._body(request)
        text = str(body.get("text") or "").strip()
        if not text or len(text) > 500:
            return self._fail("Сообщение: до 500 символов")
        self.db.clan_message(str(uuid.uuid4()), my["id"], user["user_id"], text)
        self.db.add_clan_xp(my["id"], 1)
        return self._json({"ok": True})

    async def clan_msgs(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my:
            return self._fail("Вы не в клане")
        msgs = self.db.clan_messages(my["id"], 50)
        view = [{
            "id": m["id"], "user_id": m["user_id"],
            "username": m.get("username"), "first_name": m.get("first_name"),
            "text": m["text"], "created_at": m["created_at"],
        } for m in msgs]
        return self._json({"ok": True, "messages": view})

    async def clan_disband(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] != "owner":
            return self._fail("Только владелец может распустить клан")
        self.db.delete_clan(my["id"])
        return self._json({"ok": True})

    # --- друзья ----------------------------------------------------------
    async def friends_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        friends = self.db.friends(user["user_id"])
        requests = self.db.friend_requests(user["user_id"])
        return self._json({"ok": True,
                           "friends": friends,
                           "requests": [{
                               "user_id": r["from_id"],
                               "username": r.get("username"),
                               "first_name": r.get("first_name"),
                               "created_at": r["created_at"],
                           } for r in requests]})

    async def friend_add(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        target_id = int(body.get("user_id") or 0)
        if target_id == user["user_id"]:
            return self._fail("Нельзя добавить себя")
        target = self.db.user(target_id)
        if not target:
            return self._fail("Игрок не найден")
        if self.db.are_friends(user["user_id"], target_id):
            return self._fail("Уже друзья")
        if self.db.has_friend_request(user["user_id"], target_id):
            return self._fail("Заявка уже отправлена")
        sent = self.db.has_friend_request(target_id, user["user_id"])
        if sent:
            self.db.add_friend(user["user_id"], target_id)
            self.db.remove_friend_request(target_id, user["user_id"])
            self.db.notify(target_id, "friend", "Теперь вы друзья",
                           f"@{user.get('username') or 'игрок'} принял вашу заявку")
            return self._json({"ok": True, "accepted": True})
        self.db.friend_request(user["user_id"], target_id)
        self.db.notify(target_id, "friend", "Заявка в друзья",
                       f"@{user.get('username') or 'игрок'} хочет дружить")
        return self._json({"ok": True})

    async def friend_accept(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        from_id = int(body.get("user_id") or 0)
        if not self.db.has_friend_request(from_id, user["user_id"]):
            return self._fail("Заявка не найдена")
        self.db.add_friend(from_id, user["user_id"])
        self.db.remove_friend_request(from_id, user["user_id"])
        self.db.notify(from_id, "friend", "Заявка принята",
                       f"@{user.get('username') or 'игрок'} принял вашу заявку")
        return self._json({"ok": True})

    async def friend_decline(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        self.db.remove_friend_request(int(body.get("user_id") or 0),
                                      user["user_id"])
        return self._json({"ok": True})

    async def friend_remove(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        self.db.remove_friend(user["user_id"], int(body.get("user_id") or 0))
        return self._json({"ok": True})

    # --- маркетплейс -----------------------------------------------------
    def _inventory_view(self, user: dict) -> dict:
        inv = self.db.inventory(user["user_id"])
        view = {}
        for key, qty in inv.items():
            item = next((i for i in game.SHOP_ITEMS if i["key"] == key), None)
            view[key] = {
                "key": key,
                "title": item["title"] if item else key,
                "qty": qty,
            }
        return view

    async def market_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        lots = self.db.market_lots("active", 50)
        view = [{
            "id": l["id"], "seller_id": l["seller_id"],
            "seller_name": l.get("seller_name"), "item_type": l["item_type"],
            "item": l["item"], "qty": l["qty"], "price": l["price"],
            "currency": l["currency"], "created_at": l["created_at"],
        } for l in lots]
        history = self.db.market_history(15)
        return self._json({"ok": True, "lots": view,
                           "history": [{
                               "item": h["item"], "qty": h["qty"],
                               "price": h["price"], "currency": h["currency"],
                               "created_at": h["created_at"],
                               "buyer_id": h["buyer_id"],
                           } for h in history]})

    async def market_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        item = str(body.get("item") or "").strip()
        qty = max(1, min(999, int(body.get("qty") or 1)))
        price = int(body.get("price") or 0)
        if not item:
            return self._fail("Укажите предмет")
        if price < 10:
            return self._fail("Минимальная цена — 10")
        if price > 100_000_000:
            return self._fail("Цена слишком большая")
        if self.db.item_qty(user["user_id"], item) < qty:
            return self._fail("Недостаточно предметов")
        if not self.db.take_item(user["user_id"], item, qty):
            return self._fail("Не удалось изъять предмет")
        lot_id = str(uuid.uuid4())
        self.db.create_market_lot(lot_id, user["user_id"], "item", item, qty,
                                  price, "mcoin")
        return self._json({"ok": True, "lot_id": lot_id})

    async def market_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        lot_id = str(body.get("lot_id") or "")
        lot = self.db.market_lot(lot_id)
        if not lot or lot["status"] != "active":
            return self._fail("Лот не найден")
        if int(lot["seller_id"]) == user["user_id"]:
            return self._fail("Нельзя купить свой лот")
        price = int(lot["price"])
        if user["balance"] < price:
            return self._fail("Недостаточно mCoin")
        if not self.db.close_market_lot(lot_id, user["user_id"]):
            return self._fail("Лот уже продан")
        self.db.add_balance(user["user_id"], -price)
        self.db.add_balance(lot["seller_id"], price)
        self.db.add_item(user["user_id"], lot["item"], int(lot["qty"]))
        self.db.add_market_history(str(uuid.uuid4()), lot_id, lot["seller_id"],
                                   user["user_id"], lot["item_type"],
                                   lot["item"], int(lot["qty"]), price,
                                   lot["currency"])
        self.db.notify(lot["seller_id"], "market",
                       "Предмет продан на маркетплейсе",
                       f"{lot['item']} ×{lot['qty']} за {price} mCoin")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"],
                           "inventory": self._inventory_view(fresh)})

    async def market_cancel(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        lot_id = str(body.get("lot_id") or "")
        lot = self.db.market_lot(lot_id)
        if not lot or int(lot["seller_id"]) != user["user_id"]:
            return self._fail("Лот не найден")
        if not self.db.cancel_market_lot(lot_id, user["user_id"]):
            return self._fail("Не удалось отменить")
        self.db.add_item(user["user_id"], lot["item"], int(lot["qty"]))
        return self._json({"ok": True})

    # --- аукцион ---------------------------------------------------------
    async def auction_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.expire_auctions(int(time.time()))
        lots = self.db.auction_lots("active", 50)
        now = int(time.time())
        view = [{
            "id": l["id"], "seller_id": l["seller_id"],
            "seller_name": l.get("seller_name"), "item": l["item"],
            "qty": l["qty"], "start_price": l["start_price"],
            "current_bid": l["current_bid"], "bidder_id": l["bidder_id"],
            "min_step": l["min_step"], "ends_at": l["ends_at"],
            "seconds_left": max(0, int(l["ends_at"]) - now),
        } for l in lots]
        return self._json({"ok": True, "lots": view, "now": now})

    async def auction_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        item = str(body.get("item") or "").strip()
        qty = max(1, min(999, int(body.get("qty") or 1)))
        start_price = max(10, int(body.get("start_price") or 0))
        min_step = max(10, int(body.get("min_step") or 0))
        duration = max(60, min(86400 * 7, int(body.get("duration") or 3600)))
        if not item:
            return self._fail("Укажите предмет")
        if self.db.item_qty(user["user_id"], item) < qty:
            return self._fail("Недостаточно предметов")
        if not self.db.take_item(user["user_id"], item, qty):
            return self._fail("Не удалось изъять предмет")
        lot_id = str(uuid.uuid4())
        self.db.create_auction(lot_id, user["user_id"], "item", item, qty,
                               start_price, min_step,
                               int(time.time()) + duration)
        return self._json({"ok": True, "lot_id": lot_id})

    async def auction_bid(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        lot_id = str(body.get("lot_id") or "")
        amount = max(1, int(body.get("amount") or 0))
        ok, err = self.db.place_bid(lot_id, user["user_id"], amount)
        if not ok:
            hint = {"low_bid": "Ставка ниже минимальной",
                    "ended": "Аукцион завершён",
                    "self": "Нельзя ставить на свой лот",
                    "no_balance": "Недостаточно mCoin"}.get(err, "Не удалось")
            return self._fail(hint)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    async def market_my_lots(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        active = self.db._rows(
            """SELECT * FROM market_lots WHERE seller_id = ? AND status = 'active'
               ORDER BY created_at DESC""", (user["user_id"],))
        sold = self.db._rows(
            """SELECT * FROM market_lots WHERE seller_id = ? AND status = 'sold'
               ORDER BY sold_at DESC LIMIT 10""", (user["user_id"],))
        auctions = self.db._rows(
            """SELECT * FROM auction_lots WHERE seller_id = ? AND status = 'active'
               ORDER BY ends_at DESC""", (user["user_id"],))
        return self._json({
            "ok": True,
            "market": [{
                "id": l["id"], "item": l["item"], "qty": l["qty"],
                "price": l["price"], "status": l["status"],
                "created_at": l["created_at"], "sold_at": l.get("sold_at"),
                "buyer_id": l.get("buyer_id"),
            } for l in active + sold],
            "auctions": [{
                "id": a["id"], "item": a["item"], "qty": a["qty"],
                "current_bid": a["current_bid"], "start_price": a["start_price"],
                "ends_at": a["ends_at"], "bidder_id": a.get("bidder_id"),
            } for a in auctions],
        })

    # --- лиги и сезоны ---------------------------------------------------
    def _league_view(self, season: dict) -> dict:
        leagues = self.db.leagues(season["id"])
        now = int(time.time())
        return {
            "season_id": season["id"],
            "name": season["name"],
            "starts_at": season["starts_at"],
            "ends_at": season["ends_at"],
            "status": season["status"],
            "active": season["starts_at"] <= now <= int(season["ends_at"]),
            "leagues": [{
                "id": l["id"], "name": l["name"], "icon": l["icon"],
                "min_xp": l["min_xp"], "reward": l["reward"],
            } for l in leagues],
        }

    def _my_league(self, user: dict, season: dict) -> dict | None:
        xp = int(user.get("xp") or 0)
        leagues = self.db.leagues(season["id"])
        if not leagues:
            return None
        league = leagues[0]
        for l in leagues:
            if xp >= int(l["min_xp"]):
                league = l
        member = self.db.league_member(season["id"], user["user_id"])
        if not member:
            self.db.set_league_member(season["id"], user["user_id"],
                                      league["id"])
            member = self.db.league_member(season["id"], user["user_id"])
        return {
            "league": {
                "id": league["id"], "name": league["name"],
                "icon": league["icon"], "reward": league["reward"],
                "min_xp": league["min_xp"],
            },
            "points": int(member["points"] or 0) if member else 0,
            "next": next(({
                "id": nl["id"], "name": nl["name"], "icon": nl["icon"],
                "min_xp": nl["min_xp"], "reward": nl["reward"],
            } for nl in leagues if int(nl["min_xp"]) > int(league["min_xp"])),
                None),
        }

    async def leagues_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        season = self.db.current_season(now)
        if not season:
            season_id = "season_default"
            self.db.create_season(season_id, "Сезон 1", now - 86400,
                                  now + 30 * 86400)
            lg = self.db.leagues(season_id)
            if not lg:
                for key, name, icon, min_xp, reward in (
                        ("bronze", "Бронза", "🥉", 0, 5000),
                        ("silver", "Серебро", "🥈", 500, 15000),
                        ("gold", "Золото", "🥇", 1500, 40000),
                        ("plat", "Платина", "💎", 3000, 100000),
                        ("diamond", "Алмаз", "👑", 6000, 250000)):
                    self.db.create_league(str(uuid.uuid4()), season_id, name,
                                          icon, min_xp, reward)
            season = self.db.current_season(now)
            if not season:
                return self._fail("Нет активного сезона")
        season_view = self._league_view(season)
        me = self._my_league(user, season)
        tops = {}
        for lg in season_view["leagues"]:
            tops[lg["id"]] = self.db.league_top(lg["id"], 10)
        return self._json({"ok": True, "season": season_view, "me": me,
                           "tops": tops})

    async def league_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        season = self.db.current_season(now)
        if not season:
            return self._fail("Нет активного сезона")
        if self.db.league_reward_claimed(season["id"], user["user_id"]):
            return self._fail("Награда уже получена")
        me = self._my_league(user, season)
        if not me:
            return self._fail("Нет лиги")
        league = me["league"]
        if me["points"] < 100:
            return self._fail("Нужно больше очков лиги (минимум 100)")
        if not self.db.claim_league_reward(season["id"], user["user_id"],
                                           league["id"]):
            return self._fail("Награда уже получена")
        self.db.add_balance(user["user_id"], int(league["reward"]))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"],
                           "reward": league["reward"]})

    # --- достижения: детальный прогресс --------------------------------
    async def achievements_detail(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        claimed = self.db.user_achievements(user["user_id"])
        progress_map = self.db.achievement_progress(user["user_id"])
        stats = awards.metrics(self.db, user["user_id"])
        items = []
        for ach in game.ACHIEVEMENTS:
            live = stats.get(ach["metric"], 0)
            total = progress_map.get(ach["key"], 0) + live
            target = ach["target"]
            items.append({
                "key": ach["key"], "icon": ach["icon"],
                "title": ach["title"], "desc": ach["desc"],
                "reward": ach["reward"], "xp": ach["xp"],
                "target": target, "metric": ach["metric"],
                "progress": min(total, target),
                "total": total,
                "done": total >= target,
                "claimed": ach["key"] in claimed,
            })
        tot = sum(1 for i in items if i["claimed"])
        xp_gained = sum(i["xp"] for i in items if i["claimed"])
        return self._json({"ok": True, "achievements": items,
                           "summary": {"claimed": tot, "total": len(items),
                                       "xp": xp_gained}})

    async def achievement_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        key = str(body.get("key") or "")
        ach = game.ACHIEVEMENT_BY_KEY.get(key)
        if not ach:
            return self._fail("Достижение не найдено")
        if self.db.claim_achievement(user["user_id"], key):
            self.db.add_balance(user["user_id"], int(ach["reward"]))
            self.db.add_xp(user["user_id"], int(ach["xp"]))
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "balance": fresh["balance"],
                               "reward": ach["reward"], "xp": ach["xp"]})
        return self._fail("Уже получено")

    # --- автоигра --------------------------------------------------------
    async def auto_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        game_name = str(body.get("game") or "").strip()
        strategy = str(body.get("strategy") or "fixed").strip()
        bet = int(body.get("bet") or 0)
        rounds_max = max(1, min(1000, int(body.get("rounds_max") or 10)))
        target = float(body.get("target") or 0)
        if game_name not in ("mines", "crash", "dice"):
            return self._fail("Игра не поддерживает автоигру")
        min_bet = int(self._settings().get("min_bet", 10))
        max_bet = int(self._settings().get("max_bet", 100000))
        if bet < min_bet or bet > max_bet:
            return self._fail(f"Ставка от {min_bet} до {max_bet}")
        if strategy not in ("fixed", "martingale", "paroli"):
            return self._fail("Неизвестная стратегия")
        active = self.db.auto_rounds(user["user_id"])
        if any(r["status"] == "active" for r in active):
            return self._fail("Автоигра уже запущена")
        round_id = str(uuid.uuid4())
        self.db.create_auto_round(round_id, user["user_id"], game_name,
                                  strategy, bet, rounds_max, target)
        return self._json({"ok": True, "auto_id": round_id})

    async def auto_stop(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        auto_id = str(body.get("auto_id") or "")
        row = self.db.auto_round(auto_id)
        if not row or int(row["user_id"]) != user["user_id"]:
            return self._fail("Сессия не найдена")
        self.db.stop_auto_round(auto_id, finished=False)
        return self._json({"ok": True})

    async def auto_status(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        rows = self.db.auto_rounds(user["user_id"])
        active = [r for r in rows if r["status"] == "active"]
        done = [r for r in rows if r["status"] != "active"]
        view = [{
            "id": r["id"], "game": r["game"], "strategy": r["strategy"],
            "bet": r["bet"], "rounds_done": r["rounds_done"],
            "rounds_max": r["rounds_max"], "target": r["target"],
            "status": r["status"], "created_at": r["created_at"],
        } for r in rows]
        return self._json({"ok": True, "active": active, "done": done,
                           "items": view})

    # --- боты ------------------------------------------------------------
    async def bots_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.ensure_bots()
        bots = self.db.bot_profiles()
        return self._json({"ok": True, "bots": [{
            "id": b["id"], "username": b["username"],
            "first_name": b["first_name"], "avatar": b["avatar"],
            "level": b["level"], "balance": b["balance"],
            "risk": b["risk"],
        } for b in bots]})

    # --- турниры ---------------------------------------------------------
    async def tournaments_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        tours = self.db.tournaments()
        view = []
        for t in tours:
            players = self.db.tournament_players(t["id"], 10)
            joined = any(int(p["user_id"]) == user["user_id"] for p in players)
            view.append({
                "id": t["id"], "name": t["name"], "kind": t["kind"],
                "prize": t["prize"], "entry_fee": t["entry_fee"],
                "min_bet": t["min_bet"], "starts_at": t["starts_at"],
                "ends_at": t["ends_at"], "status": t["status"],
                "seconds_left": max(0, int(t["ends_at"]) - now),
                "players": len(players), "joined": joined,
            })
        return self._json({"ok": True, "tournaments": view, "now": now})

    async def tournament_join(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        tour_id = str(body.get("tour_id") or "")
        tour = self.db.tournament(tour_id)
        if not tour:
            return self._fail("Турнир не найден")
        now = int(time.time())
        if tour["status"] != "active" or int(tour["ends_at"]) < now:
            return self._fail("Турнир недоступен")
        fee = int(tour["entry_fee"])
        if fee and user["balance"] < fee:
            return self._fail("Недостаточно mCoin для входа")
        if self.db.join_tournament(tour_id, user["user_id"]):
            if fee:
                self.db.add_balance(user["user_id"], -fee)
                self.db.add_treasury(fee)
            return self._json({"ok": True})
        return self._fail("Вы уже участвуете")

    async def tournament_info(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        tour_id = str(body.get("tour_id") or "")
        tour = self.db.tournament(tour_id)
        if not tour:
            return self._fail("Турнир не найден")
        players = self.db.tournament_players(tour_id, 50)
        view = [{
            "user_id": p["user_id"], "username": p.get("username"),
            "first_name": p.get("first_name"), "score": p["score"],
            "best_bet": p["best_bet"], "joined_at": p["joined_at"],
        } for p in players]
        return self._json({"ok": True, "tournament": {
            "id": tour["id"], "name": tour["name"], "kind": tour["kind"],
            "prize": tour["prize"], "entry_fee": tour["entry_fee"],
            "min_bet": tour["min_bet"], "starts_at": tour["starts_at"],
            "ends_at": tour["ends_at"], "status": tour["status"],
        }, "players": view})

    # --- уведомления -----------------------------------------------------
    async def notifications_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        items = self.db.notifications(user["user_id"], 30)
        return self._json({"ok": True, "notifications": [{
            "id": n["id"], "kind": n["kind"], "title": n["title"],
            "text": n["text"], "is_read": n["is_read"],
            "created_at": n["created_at"], "meta": json.loads(n["meta"] or "{}"),
        } for n in items]})

    async def notifications_read(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.read_notifications(user["user_id"])
        return self._json({"ok": True})

    # --- клановые войны --------------------------------------------------
    async def wars_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.expire_wars(int(time.time()))
        wars = self.db.wars(30)
        view = []
        for w in wars:
            clan_a = self.db.clan(w["clan_a"])
            clan_b = self.db.clan(w["clan_b"])
            view.append({
                "id": w["id"],
                "clan_a": {"id": w["clan_a"],
                           "name": clan_a["name"] if clan_a else "?",
                           "tag": clan_a["tag"] if clan_a else "?",
                           "score": w["score_a"], "prize": w["prize_a"]},
                "clan_b": {"id": w["clan_b"],
                           "name": clan_b["name"] if clan_b else "?",
                           "tag": clan_b["tag"] if clan_b else "?",
                           "score": w["score_b"], "prize": w["prize_b"]},
                "ends_at": w["ends_at"],
                "seconds_left": max(0, int(w["ends_at"]) - int(time.time())),
                "bets": self.db.war_bets(w["id"]),
            })
        return self._json({"ok": True, "wars": view})

    async def war_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] != "owner":
            return self._fail("Только владелец клана может объявить войну")
        body = await self._body(request)
        target_id = str(body.get("clan_id") or "")
        prize = max(1000, min(1_000_000, int(body.get("prize") or 0)))
        target = self.db.clan(target_id)
        if not target:
            return self._fail("Клан не найден")
        if target_id == my["id"]:
            return self._fail("Нельзя воевать с собой")
        if self.db.active_war(my["id"]):
            return self._fail("Ваш клан уже в войне")
        if self.db.active_war(target_id):
            return self._fail("Клан-противник уже в войне")
        if user["balance"] < prize:
            return self._fail("Недостаточно mCoin для призового фонда")
        target_owner = self.db.user(int(target["owner_id"]))
        target_balance = int(target_owner["balance"]) if target_owner else 0
        if target_balance < prize:
            return self._fail("Клан-противник не может покрыть приз")
        self.db.add_balance(user["user_id"], -prize)
        self.db.add_balance(int(target["owner_id"]), -prize)
        self.db.add_treasury(prize * 2)
        now = int(time.time())
        war_id = str(uuid.uuid4())
        self.db.create_war(war_id, my["id"], target_id, prize, prize, now,
                           24 * 3600)
        self.db.notify(int(target["owner_id"]), "war",
                       "Война кланов!",
                       f"Клан «{my['name']}» объявил вашему клану войну "
                       f"с призом {prize} mCoin")
        return self._json({"ok": True, "war_id": war_id})

    async def war_bet(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        war_id = str(body.get("war_id") or "")
        side = str(body.get("side") or "")
        amount = int(body.get("amount") or 0)
        war = self.db.war(war_id)
        if not war or war["status"] != "active":
            return self._fail("Война не найдена или завершена")
        clan_id = war["clan_a"] if side == "a" else war["clan_b"]
        if side not in ("a", "b"):
            return self._fail("Выберите сторону")
        if amount < 100:
            return self._fail("Минимальная ставка — 100")
        if user["balance"] < amount:
            return self._fail("Недостаточно mCoin")
        if self.db.war_bet(war_id, user["user_id"], clan_id, amount):
            self.db.add_balance(user["user_id"], -amount)
            self.db.add_treasury(amount)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "balance": fresh["balance"]})
        return self._fail("Вы уже сделали ставку")

    # --- клановые рейды --------------------------------------------------
    async def raids_list(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.expire_raids(int(time.time()))
        my = self.db.user_clan(user["user_id"])
        raids = []
        if my:
            raid = self.db.active_raid(my["id"])
            if raid:
                raids.append(self._raid_view(raid))
        return self._json({"ok": True, "raids": raids})

    def _raid_view(self, raid: dict) -> dict:
        clan = self.db.clan(raid["clan_id"])
        return {
            "id": raid["id"],
            "clan_id": raid["clan_id"],
            "clan_name": clan["name"] if clan else "?",
            "boss": raid["boss"], "hp": raid["hp"], "max_hp": raid["max_hp"],
            "reward": raid["reward"],
            "seconds_left": max(0, int(raid["ends_at"]) - int(time.time())),
            "hits": self.db.raid_hits(raid["id"]),
        }

    async def raid_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my or my["my_role"] not in ("owner", "officer"):
            return self._fail("Нужна роль офицера или владельца")
        if self.db.active_raid(my["id"]):
            return self._fail("Рейд уже идёт")
        body = await self._body(request)
        boss_key = str(body.get("boss") or "slime")
        bosses = {
            "slime": {"name": "Слизень", "hp": 3000, "reward": 5000},
            "golem": {"name": "Каменный голем", "hp": 8000, "reward": 12000},
            "dragon": {"name": "Дракон", "hp": 20000, "reward": 30000},
        }
        boss = bosses.get(boss_key) or bosses["slime"]
        raid_id = str(uuid.uuid4())
        self.db.create_raid(raid_id, my["id"], boss["name"], boss["hp"],
                            boss["reward"], int(time.time()), 6 * 3600)
        return self._json({"ok": True, "raid_id": raid_id})

    async def raid_hit(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        my = self.db.user_clan(user["user_id"])
        if not my:
            return self._fail("Вы не в клане")
        body = await self._body(request)
        raid_id = str(body.get("raid_id") or "")
        raid = self.db.raid(raid_id)
        if not raid or raid["status"] != "active":
            return self._fail("Рейд не найден или завершён")
        if raid["clan_id"] != my["id"]:
            return self._fail("Это не ваш рейд")
        if self._last_action.get(user["user_id"], 0) > time.time() - 1:
            return self._fail("Подождите секунду")
        self._last_action[user["user_id"]] = time.time()
        damage = 200 + int(user.get("balance", 0) // 10000)
        damage = min(2000, damage)
        if int(user.get("xp") or 0) > 1000:
            damage += 100
        hit_id = str(uuid.uuid4())
        self.db.raid_hit(hit_id, raid_id, user["user_id"], damage)
        fresh_raid = self.db.raid(raid_id)
        self.db.add_clan_xp(my["id"], 5)
        killed = fresh_raid and int(fresh_raid["hp"]) <= 0
        if killed:
            self.db.close_raid(raid_id, True)
            total = int(raid["reward"])
            hits = self.db.raid_hits(raid_id)
            if hits:
                share = max(1, total // len(hits))
                for h in hits:
                    self.db.add_balance(int(h["user_id"]), share)
                    self.db.notify(int(h["user_id"]), "raid",
                                   "Рейд завершён!",
                                   f"Ваша награда: {share} mCoin")
            self.db.notify(int(raid["clan_id"]), "raid",
                           "Босс повержен!", "Клан получил награду")
        return self._json({"ok": True, "damage": damage,
                           "killed": killed,
                           "hp_left": int(fresh_raid["hp"]) if fresh_raid else 0,
                           "raid": self._raid_view(fresh_raid) if fresh_raid else None})

    # --- кредиты ---------------------------------------------------------
    async def loans_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        items = []
        for loan in self.db.loans(user["user_id"]):
            items.append({
                "id": loan["id"], "amount": loan["amount"],
                "rate_bps": loan["rate_bps"], "term_days": loan["term_days"],
                "take_at": loan["take_at"], "due_at": loan["due_at"],
                "owed": self.db.loan_owed(loan, now),
                "status": loan["status"],
            })
        plans = game.LOAN_PLANS if hasattr(game, "LOAN_PLANS") else [
            {"days": 3, "rate_bps": 500},
            {"days": 7, "rate_bps": 400},
            {"days": 14, "rate_bps": 300},
        ]
        return self._json({"ok": True, "loans": items, "plans": plans})

    async def loan_take(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        amount = int(body.get("amount") or 0)
        term_days = int(body.get("term_days") or 7)
        if amount < 1000 or amount > 500_000:
            return self._fail("Сумма от 1 000 до 500 000")
        active = self.db.loans(user["user_id"])
        if len(active) >= 2:
            return self._fail("Максимум 2 активных кредита")
        total_active = sum(int(a["amount"]) for a in active)
        if total_active + amount > 500_000:
            return self._fail("Слишком много долгов")
        rate_bps = max(200, min(800, 800 - amount // 20000))
        loan_id = str(uuid.uuid4())
        self.db.create_loan(loan_id, user["user_id"], amount, rate_bps,
                            term_days, int(time.time()))
        self.db.add_balance(user["user_id"], amount)
        self.db.add_xp(user["user_id"], 5)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    async def loan_pay(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        loan_id = str(body.get("loan_id") or "")
        amount = int(body.get("amount") or 0)
        ok, paid = self.db.loan_pay(loan_id, user["user_id"], amount,
                                    int(time.time()))
        if not ok:
            return self._fail("Не удалось погасить кредит")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "paid": paid,
                           "balance": fresh["balance"]})

    # --- стрики ----------------------------------------------------------
    async def streaks_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        today = time.strftime("%Y-%m-%d")
        last = self.db.last_streak(user["user_id"])
        current = 0
        if last:
            last_day = last["day"]
            yesterday = time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - 86400))
            current = int(last["streak"]) if last_day in (today, yesterday) else 0
        claimed_today = bool(self.db.streak_today(user["user_id"], today))
        rewards = [1000, 1500, 2500, 4000, 6000, 9000, 15000]
        return self._json({"ok": True, "streak": current,
                           "claimed_today": claimed_today, "rewards": rewards})

    async def streak_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        today = time.strftime("%Y-%m-%d")
        if self.db.streak_today(user["user_id"], today):
            return self._fail("Сегодня уже забирали")
        last = self.db.last_streak(user["user_id"])
        streak = 0
        if last:
            yesterday = time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - 86400))
            streak = int(last["streak"]) if last["day"] == yesterday else 0
        streak += 1
        rewards = [1000, 1500, 2500, 4000, 6000, 9000, 15000]
        reward = rewards[min(streak - 1, len(rewards) - 1)]
        self.db.set_streak(user["user_id"], today, streak,
                           {"day": streak, "reward": reward})
        self.db.add_balance(user["user_id"], reward)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "streak": streak, "reward": reward,
                           "balance": fresh["balance"]})

    # --- рыбалка: уровни -------------------------------------------------
    async def fishing_level(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        level = self.db.fish_level(user["user_id"])
        need = 200 * level["level"] * level["level"]
        level["need"] = need
        return self._json({"ok": True, "level": level})

    # --- крафт -----------------------------------------------------------
    async def craft_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.ensure_recipes()
        now = int(time.time())
        recipes = self.db.recipes()
        jobs = []
        for job in self.db.craft_jobs(user["user_id"]):
            if job["status"] == "crafting" and int(job["ends_at"]) <= now:
                self.db.finish_craft(job["id"])
            jobs.append({
                "id": job["id"], "recipe_id": job["recipe_id"],
                "ends_at": job["ends_at"], "status": job["status"],
                "seconds_left": max(0, int(job["ends_at"]) - now),
            })
        inv = self.db.inventory(user["user_id"])
        view = []
        for r in recipes:
            ready = all(inv.get(k, 0) >= int(v) for k, v in r["inputs"].items())
            view.append({
                "id": r["id"], "output": r["output_key"],
                "output_qty": r["output_qty"], "inputs": r["inputs"],
                "cooldown": r["cooldown_s"], "ready": ready,
            })
        return self._json({"ok": True, "recipes": view, "jobs": jobs,
                           "inventory": inv})

    async def craft_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        recipe_id = str(body.get("recipe_id") or "")
        recipe = self.db.recipe(recipe_id)
        if not recipe:
            return self._fail("Рецепт не найден")
        inv = self.db.inventory(user["user_id"])
        for key, qty in recipe["inputs"].items():
            if inv.get(key, 0) < int(qty):
                return self._fail("Недостаточно материалов")
        for key, qty in recipe["inputs"].items():
            self.db.take_item(user["user_id"], key, int(qty))
        job_id = str(uuid.uuid4())
        now = int(time.time())
        self.db.start_craft(job_id, user["user_id"], recipe_id, now,
                            int(recipe["cooldown_s"]))
        return self._json({"ok": True, "job_id": job_id})

    async def craft_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        job_id = str(body.get("job_id") or "")
        result = self.db.claim_craft(job_id, user["user_id"])
        if not result:
            return self._fail("Не готово или не найдено")
        return self._json({"ok": True, "output": result["output"],
                           "qty": result["qty"]})

    # --- сундуки миссий --------------------------------------------------
    async def chests_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        chests = [
            {"key": "daily", "title": "Сундук дня", "cooldown": 6 * 3600},
            {"key": "weekly", "title": "Недельный сундук", "cooldown": 7 * 86400},
        ]
        view = []
        for c in chests:
            state = self.db.chest_state(user["user_id"], c["key"])
            ready = not state or now >= int(state["next_at"])
            view.append({
                "key": c["key"], "title": c["title"], "ready": ready,
                "next_in": max(0, int(state["next_at"]) - now) if state else 0,
            })
        return self._json({"ok": True, "chests": view})

    async def chest_open(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        key = str(body.get("key") or "")
        cooldowns = {"daily": 6 * 3600, "weekly": 7 * 86400}
        if key not in cooldowns:
            return self._fail("Сундук не найден")
        now = int(time.time())
        state = self.db.chest_state(user["user_id"], key)
        if state and now < int(state["next_at"]):
            return self._fail("Сундук ещё не готов")
        reward = random.randint(300, 1200)
        extra = {}
        roll = random.random()
        if roll < 0.15:
            extra["gmpoint"] = 50
            self.db.add_gmpoint(user["user_id"], 50)
        if roll < 0.05:
            extra["lootbox"] = 1
            self.db.add_item(user["user_id"], "lootbox", 1)
        self.db.add_balance(user["user_id"], reward)
        self.db.chest_open(user["user_id"], key, cooldowns[key])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": reward, "extra": extra,
                           "balance": fresh["balance"]})

    # --- корабли ---------------------------------------------------------
    async def ships_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        ships = game.SHIPS if hasattr(game, "SHIPS") else [
            {"key": "raft", "title": "Плот", "cost": 0},
            {"key": "boat", "title": "Лодка", "cost": 20000,
             "xp": 300},
            {"key": "schooner", "title": "Шхуна", "cost": 80000,
             "xp": 1000},
            {"key": "galleon", "title": "Галеон", "cost": 250000,
             "xp": 3000},
        ]
        owned = self.db.user_ships(user["user_id"])
        view = []
        for s in ships:
            owned_flag = s["key"] in owned or int(s.get("cost") or 0) == 0
            view.append({
                "key": s["key"], "title": s["title"], "cost": s["cost"],
                "xp": s.get("xp", 0), "owned": owned_flag,
                "xp_now": int(user.get("xp") or 0),
            })
        return self._json({"ok": True, "ships": view})

    async def ship_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        key = str(body.get("key") or "")
        ships = game.SHIPS if hasattr(game, "SHIPS") else []
        ship = next((s for s in ships if s["key"] == key), None)
        if not ship:
            return self._fail("Корабль не найден")
        if ship["key"] in self.db.user_ships(user["user_id"]):
            return self._fail("Уже куплен")
        cost = int(ship.get("cost") or 0)
        if int(user.get("xp") or 0) < int(ship.get("xp") or 0):
            return self._fail("Недостаточно уровня")
        if user["balance"] < cost:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -cost)
        self.db.unlock_ship(user["user_id"], key)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    # --- награды турниров ------------------------------------------------
    async def tournament_rewards_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        tour_id = str(body.get("tour_id") or "")
        rewards = self.db.tournament_rewards(tour_id)
        if not rewards:
            return self._json({"ok": True, "rewards": []})
        my_place = None
        players = self.db.tournament_players(tour_id, 50)
        for i, p in enumerate(players):
            if int(p["user_id"]) == user["user_id"]:
                my_place = i + 1
                break
        claimed = self.db.tournament_claimed(tour_id, user["user_id"])
        return self._json({"ok": True, "rewards": [{
            "place": r["place"], "reward": r["reward"],
        } for r in rewards], "my_place": my_place, "claimed": claimed})

    async def tournament_reward_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        tour_id = str(body.get("tour_id") or "")
        if self.db.tournament_claimed(tour_id, user["user_id"]) is not None:
            return self._fail("Награда уже получена")
        players = self.db.tournament_players(tour_id, 50)
        my_place = None
        for i, p in enumerate(players):
            if int(p["user_id"]) == user["user_id"]:
                my_place = i + 1
                break
        if not my_place:
            return self._fail("Вы не участвовали")
        reward_row = max(
            (r for r in self.db.tournament_rewards(tour_id)
             if int(r["place"]) >= my_place),
            key=lambda r: int(r["place"]), default=None)
        if not reward_row:
            return self._fail("Без награды")
        if not self.db.claim_tournament_reward(tour_id, user["user_id"],
                                               int(reward_row["place"])):
            return self._fail("Награда уже получена")
        self.db.add_balance(user["user_id"], int(reward_row["reward"]))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": reward_row["reward"],
                           "balance": fresh["balance"]})

    # --- поиск игроков ---------------------------------------------------
    async def user_search(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        query = str(body.get("query") or "").strip()
        if len(query) < 2:
            return self._json({"ok": True, "users": []})
        rows = self.db.search_users(query, 20)
        return self._json({"ok": True, "users": [{
            "user_id": u["user_id"], "username": u.get("username"),
            "first_name": u.get("first_name"), "balance": u.get("balance", 0),
            "xp": u.get("xp", 0), "last_seen": u.get("last_seen", 0),
            "is_friend": self.db.are_friends(user["user_id"], u["user_id"]),
        } for u in rows]})

    # --- престиж --------------------------------------------------------
    async def prestige_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        data = self.db.prestige(user["user_id"])
        level = game.level_view(data["level_xp"])
        can = level["level"] >= 50 and data["prestige"] < 10
        cost = 100000 * (data["prestige"] + 1)
        bonus = 0.05 * data["prestige"]
        return self._json({"ok": True, "prestige": data, "can": can,
                           "cost": cost, "bonus": bonus,
                           "level": level["level"]})

    async def prestige_do(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        data = self.db.prestige(user["user_id"])
        if data["prestige"] >= 10:
            return self._fail("Максимальный престиж")
        level = game.level_view(data["level_xp"])
        if level["level"] < 50:
            return self._fail("Нужен 50-й уровень")
        cost = 100000 * (data["prestige"] + 1)
        if data["balance"] < cost:
            return self._fail(f"Нужно {cost} mCoin")
        best = game.level_view(data["level_xp"])["level"] / 50.0
        self.db.set_prestige(user["user_id"], data["prestige"] + 1, 0,
                             max(data["best"], best))
        self.db.add_balance(user["user_id"], -cost)
        self.db.reset_xp(user["user_id"])
        fresh = self.db.user(user["user_id"])
        self.db.notify(user["user_id"], "prestige",
                       f"Престиж {data['prestige'] + 1}!",
                       f"+{int(5 * (data['prestige'] + 1))}% к выплатам навсегда")
        return self._json({"ok": True, "prestige": data["prestige"] + 1,
                           "balance": fresh["balance"]})

    # --- заказы ---------------------------------------------------------
    async def orders_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        rows = self.db.orders(user["user_id"])
        view = []
        for o in rows:
            if int(o["expires_at"]) < now:
                continue
            done = int(o["progress"]) >= int(o["target"])
            view.append({
                "id": o["id"], "kind": o["kind"], "target": o["target"],
                "progress": o["progress"], "done": done,
                "reward": o["reward"], "expires_at": o["expires_at"],
                "seconds_left": max(0, int(o["expires_at"]) - now),
            })
        return self._json({"ok": True, "orders": view})

    async def order_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        order_id = str(body.get("order_id") or "")
        order = self.db.finish_order(order_id, user["user_id"])
        if not order:
            return self._fail("Заказ не найден или ещё не готов")
        self.db.add_balance(user["user_id"], int(order["reward"]))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": order["reward"],
                           "balance": fresh["balance"]})

    # --- жетоны и обменный пункт ----------------------------------------
    async def tokens_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        balance = self.db.tokens(user["user_id"])
        history = self.db.token_history(user["user_id"])
        rates = {"gmpoint": 10, "lootbox": 300, "item_insurance": 25,
                 "item_charm": 50}
        return self._json({
            "ok": True, "tokens": balance, "history": history,
            "rates": rates,
            "exchange": [
                {"kind": "gmpoint", "title": "10 GMPOINT", "cost": 20,
                 "get": "gmpoint"},
                {"kind": "lootbox", "title": "Кейс удачи", "cost": 600,
                 "get": "item"},
                {"kind": "insurance", "title": "Страховка", "cost": 120,
                 "get": "item"},
                {"kind": "charm", "title": "Талисман", "cost": 200,
                 "get": "item"},
            ],
        })

    async def tokens_exchange(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        kind = str(body.get("kind") or "")
        costs = {"gmpoint": 20, "lootbox": 600, "insurance": 120,
                 "charm": 200}
        if kind not in costs:
            return self._fail("Неизвестный обмен")
        cost = costs[kind]
        if not self.db.spend_tokens(user["user_id"], cost):
            return self._fail("Недостаточно жетонов")
        result = ""
        if kind == "gmpoint":
            self.db.add_gmpoint(user["user_id"], 10)
            result = "+10 GMPOINT"
        elif kind == "lootbox":
            self.db.add_item(user["user_id"], "lootbox", 1)
            result = "кейс удачи"
        elif kind == "insurance":
            self.db.add_item(user["user_id"], "insurance", 1)
            result = "страховка"
        elif kind == "charm":
            self.db.add_item(user["user_id"], "charm", 1)
            result = "талисман"
        self.db.token_log(user["user_id"], -cost, f"Обмен: {kind}")
        fresh_tokens = self.db.tokens(user["user_id"])
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "tokens": fresh_tokens,
                           "balance": fresh["balance"], "result": result})

    # --- карточки -------------------------------------------------------
    async def cards_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        album = self.db.card_album()
        if not album:
            for set_key, cards in game.CARD_ALBUM.items():
                for i, c in enumerate(cards):
                    self.db._exec(
                        """INSERT INTO card_album (card, set_key, number, title,
                               rarity) VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT (card) DO NOTHING""",
                        (c["key"], set_key, i + 1, c["title"],
                         c.get("rarity", "common")))
            album = self.db.card_album()
        owned = self.db.cards(user["user_id"])
        progress = self.db.card_progress(user["user_id"])
        view = [{
            "card": c["card"], "set_key": c["set_key"],
            "title": c["title"], "rarity": c["rarity"],
            "owned": int(owned.get(c["card"], 0)),
        } for c in album]
        return self._json({"ok": True, "cards": view, "progress": progress})

    async def card_unpack(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        album = self.db.card_album()
        if not album:
            return self._fail("Альбом пуст")
        body = await self._body(request)
        qty = max(1, min(10, int(body.get("qty") or 1)))
        cost = qty * 150
        if user["balance"] < cost:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -cost)
        total = []
        for i in range(qty):
            roll = random.random()
            rarity = "common" if roll < 0.7 else ("rare" if roll < 0.9 else "epic")
            pool = [c for c in album if c["rarity"] == rarity]
            if not pool:
                pool = album
            card = random.choice(pool)
            self.db.add_card(user["user_id"], card["card"])
            total.append(card["card"])
        self.db.token_log(user["user_id"], 0, "Открытие карточек")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "cards": total,
                           "balance": fresh["balance"]})

    # --- энергия --------------------------------------------------------
    async def energy_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        st = self.db.energy(user["user_id"])
        return self._json({"ok": True, "energy": st})

    async def energy_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        amount = max(10, min(100, int(body.get("amount") or 10)))
        price = amount * 50
        if user["balance"] < price:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -price)
        self.db.add_energy(user["user_id"], amount)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"],
                           "energy": self.db.energy(user["user_id"])})

    # --- арена ----------------------------------------------------------
    async def arena_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        rating = self.db.arena_rating(user["user_id"])
        stats = self.db.arena_stats(user["user_id"])
        calendar = self.db.arena_calendar(user["user_id"])
        return self._json({"ok": True, "rating": rating, "stats": stats,
                           "matches": calendar["matches"]})

    async def arena_fight(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        bet = max(100, min(100000, int(body.get("bet") or 0)))
        if user["balance"] < bet:
            return self._fail("Недостаточно mCoin")
        if self._last_action.get(user["user_id"], 0) > time.time() - 2:
            return self._fail("Подождите пару секунд")
        self._last_action[user["user_id"]] = time.time()
        my_rating = self.db.arena_rating(user["user_id"])
        roll = random.random()
        win_chance = 0.5 + (my_rating - 1200) / 4000
        win_chance = max(0.35, min(0.65, win_chance))
        won = roll < win_chance
        payout = int(bet * (1.9 if won else 0))
        self.db.add_balance(user["user_id"], payout - bet)
        result = "win" if won else "lose"
        self.db.add_arena_match(str(uuid.uuid4()), user["user_id"],
                                "Соперник Арены", bet, result, payout)
        if won:
            self.db.update_arena_rating(user["user_id"], 15)
            self.db.add_duel_stats(user["user_id"], True)
        else:
            self.db.update_arena_rating(user["user_id"], -10)
            self.db.add_duel_stats(user["user_id"], False)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "won": won, "payout": payout,
                           "rating": self.db.arena_rating(user["user_id"]),
                           "balance": fresh["balance"]})

    # --- бинго ----------------------------------------------------------
    async def bingo_new(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if self.db.active_bingo(user["user_id"]):
            return self._fail("Есть незавершённая игра")
        body = await self._body(request)
        bet = max(50, min(20000, int(body.get("bet") or 0)))
        if user["balance"] < bet:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -bet)
        nums = random.sample(range(1, 26), 9)
        game_id = str(uuid.uuid4())
        self.db.create_bingo(game_id, user["user_id"], bet, nums)
        return self._json({"ok": True, "game_id": game_id, "board": nums,
                           "bet": bet})

    async def bingo_mark(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        game_id = str(body.get("game_id") or "")
        number = int(body.get("number") or 0)
        game = self.db.bingo_game(game_id)
        if not game or int(game["user_id"]) != user["user_id"]:
            return self._fail("Игра не найдена")
        if game["status"] != "active":
            return self._fail("Игра завершена")
        board = game["board"]
        marks = list(game["marks"])
        if number not in board:
            return self._fail("Число не на поле")
        if number in game["numbers"]:
            return self._fail("Уже отмечено")
        idx = board.index(number)
        marks[idx] = 1
        lines = 0
        for r in range(3):
            if all(marks[r * 3 + c] for c in range(3)):
                lines += 1
        for c in range(3):
            if all(marks[r * 3 + c] for r in range(3)):
                lines += 1
        if all(marks[i * 3 + i] for i in range(3)):
            lines += 1
        if all(marks[i * 3 + (2 - i)] for i in range(3)):
            lines += 1
        payout = 0
        status = "active"
        if lines >= 2:
            payout = int(game["bet"]) * 6
            self.db.add_balance(user["user_id"], payout)
            status = "won"
        elif lines == 1:
            self.db.add_balance(user["user_id"], int(game["bet"]) * 2)
        self.db.bingo_mark(game_id, number, marks)
        if status != "active":
            self.db.bingo_finish(game_id, status, payout)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "lines": lines, "status": status,
                           "payout": payout, "balance": fresh["balance"],
                           "marks": marks, "numbers": game["numbers"] + [number]})

    # --- энциклопедия ----------------------------------------------------
    async def encyclopedia(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        fish = []
        if hasattr(game, "FISH_ENGLISH"):
            fish = game.FISH_ENGLISH
        games_data = []
        if hasattr(game, "GAME_ENCYCLOPEDIA"):
            games_data = game.GAME_ENCYCLOPEDIA
        items_data = []
        if hasattr(game, "ITEM_ENCYCLOPEDIA"):
            items_data = game.ITEM_ENCYCLOPEDIA
        return self._json({"ok": True, "fish": fish, "games": games_data,
                           "items": items_data})

    # --- живые ставки ---------------------------------------------------
    async def live_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        sessions = self.db.live_sessions(10)
        view = []
        for s in sessions:
            bets = self.db.live_bets(s["id"])
            total = sum(int(b["bet"]) for b in bets)
            view.append({
                "id": s["id"], "game": s["game"], "host_id": s["host_id"],
                "bet": s["bet"], "total_bets": total,
                "bets_count": len(bets),
                "created_at": s["created_at"],
            })
        return self._json({"ok": True, "sessions": view})

    async def live_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        game_name = str(body.get("game") or "mines")
        if game_name not in ("mines", "dice"):
            return self._fail("Сейчас доступны только Сапёр и Кости")
        bet = max(100, min(100000, int(body.get("bet") or 0)))
        if user["balance"] < bet:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -bet)
        session_id = str(uuid.uuid4())
        self.db.create_live_session(session_id, game_name, user["user_id"], bet)
        return self._json({"ok": True, "session_id": session_id})

    async def live_bet(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        session_id = str(body.get("session_id") or "")
        amount = int(body.get("amount") or 0)
        session = self.db.live_session(session_id)
        if not session or session["status"] != "active":
            return self._fail("Сессия не найдена")
        if amount < 100:
            return self._fail("Минимальная ставка 100")
        if user["balance"] < amount:
            return self._fail("Недостаточно mCoin")
        odds = 2.0
        self.db.place_live_bet(str(uuid.uuid4()), user["user_id"], session_id,
                               session["game"], amount, odds)
        self.db.add_balance(user["user_id"], -amount)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"],
                           "odds": odds})

    async def live_finish(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        session_id = str(body.get("session_id") or "")
        session = self.db.live_session(session_id)
        if not session or session["status"] != "active":
            return self._fail("Сессия не найдена")
        if int(session["host_id"]) != user["user_id"]:
            return self._fail("Только создатель может завершить сессию")
        outcome = float(body.get("outcome") or 2.0)
        self.db.finish_live_session(session_id, outcome)
        self.db.settle_live_bets(session_id, outcome)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "outcome": outcome,
                           "balance": fresh["balance"]})

    # --- сезонные события -----------------------------------------------
    async def events_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        self.db.ensure_events()
        events = self.db.active_events(now)
        view = []
        for e in events:
            if self.db.event_claimed(e["id"], user["user_id"]):
                continue
            view.append({
                "id": e["id"], "key": e["key"], "title": e["title"],
                "desc": e["desc_text"], "prize": e["prize"],
                "seconds_left": max(0, int(e["ends_at"]) - now),
                "claimed": self.db.event_claimed(e["id"], user["user_id"]),
            })
        return self._json({"ok": True, "events": view})

    async def event_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        event_id = str(body.get("event_id") or "")
        row = self.db._row(
            "SELECT * FROM season_events WHERE id = ?", (event_id,))
        if not row:
            return self._fail("Событие не найдено")
        if self.db.event_claimed(event_id, user["user_id"]):
            return self._fail("Уже получено")
        if not self.db.claim_event(event_id, user["user_id"]):
            return self._fail("Уже получено")
        self.db.add_balance(user["user_id"], int(row["prize"]))
        self.db.add_tokens(user["user_id"], max(1, int(row["prize"]) // 100))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "prize": row["prize"],
                           "balance": fresh["balance"]})

    # --- ресторан -------------------------------------------------------
    def _restaurant_dishes(self) -> list[dict]:
        return [
            {"key": "soup", "title": "Уха", "fish": "fish_cheap",
             "needed": 3, "reward": 900, "cook_time": 60},
            {"key": "grill", "title": "Рыба на гриле", "fish": "fish_common",
             "needed": 3, "reward": 1500, "cook_time": 90},
            {"key": "sushi", "title": "Суши-набор", "fish": "fish_rare",
             "needed": 2, "reward": 2200, "cook_time": 120},
            {"key": "royal", "title": "Королевский ужин", "fish": "fish_epic",
             "needed": 1, "reward": 4000, "cook_time": 180},
        ]

    async def restaurant_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        kinds = set()
        for fish in self.db.fish_list(user["user_id"], 0):
            kinds.add(fish["species"])
        dishes = []
        for d in self._restaurant_dishes():
            fishes = [f for f in self.db.fish_list(user["user_id"], 0)
                      if f["species"] in kinds]
            fishes = [f for f in fishes if f["species"] == d.get("species")
                      or d.get("fish") == "fish_cheap" and f["species"] in
                      ("sprat", "herring")]
            if d["fish"] == "fish_common":
                fishes = [f for f in self.db.fish_list(user["user_id"], 0)
                          if f["species"] in ("carp", "perch", "koi")]
            elif d["fish"] == "fish_rare":
                fishes = [f for f in self.db.fish_list(user["user_id"], 0)
                          if f["species"] in ("pike", "salmon")]
            elif d["fish"] == "fish_epic":
                fishes = [f for f in self.db.fish_list(user["user_id"], 0)
                          if f["species"] in ("sturgeon", "catfish")]
            dishes.append({
                "key": d["key"], "title": d["title"], "needed": d["needed"],
                "reward": d["reward"], "cook_time": d["cook_time"],
                "available": len(fishes),
            })
        orders = self.db.restaurant_orders(user["user_id"])
        now = int(time.time())
        return self._json({"ok": True, "dishes": dishes, "orders": [{
            "id": o["id"], "dish": o["dish"], "reward": o["reward"],
            "seconds_left": max(0, int(o["ready_at"]) - now),
            "status": o["status"],
        } for o in orders]})

    async def restaurant_cook(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        dish_key = str(body.get("dish") or "")
        dish = next((d for d in self._restaurant_dishes()
                     if d["key"] == dish_key), None)
        if not dish:
            return self._fail("Блюдо не найдено")
        fish = None
        if dish["fish"] == "fish_cheap":
            fish = next((f for f in self.db.fish_list(user["user_id"], 0)
                         if f["species"] in ("sprat", "herring")), None)
        elif dish["fish"] == "fish_common":
            fish = next((f for f in self.db.fish_list(user["user_id"], 0)
                         if f["species"] in ("carp", "perch", "koi")), None)
        elif dish["fish"] == "fish_rare":
            fish = next((f for f in self.db.fish_list(user["user_id"], 0)
                         if f["species"] in ("pike", "salmon")), None)
        else:
            fish = next((f for f in self.db.fish_list(user["user_id"], 0)
                         if f["species"] in ("sturgeon", "catfish")), None)
        if not fish:
            return self._fail("Нет подходящей рыбы")
        self.db.sell_fish(user["user_id"], fish["id"])
        order_id = str(uuid.uuid4())
        self.db.create_restaurant_order(order_id, user["user_id"],
                                        dish["title"], fish["species"], 1,
                                        dish["reward"], int(time.time()),
                                        dish["cook_time"])
        return self._json({"ok": True, "order_id": order_id})

    async def restaurant_take(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        order_id = str(body.get("order_id") or "")
        order = self.db.finish_restaurant_order(order_id, user["user_id"])
        if not order:
            return self._fail("Блюдо ещё готовится")
        self.db.add_balance(user["user_id"], int(order["reward"]))
        self.db.add_xp(user["user_id"], 10)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": order["reward"],
                           "balance": fresh["balance"]})

    # --- медали ---------------------------------------------------------
    async def medals_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        owned = self.db.medals(user["user_id"])
        medals = game.MEDALS if hasattr(game, "MEDALS") else []
        return self._json({"ok": True, "medals": [{
            "key": m["key"], "title": m["title"], "icon": m["icon"],
            "desc": m["desc"], "owned": m["key"] in owned,
        } for m in medals]})

    # --- цели дня -------------------------------------------------------
    async def goals_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        day = time.strftime("%Y-%m-%d")
        self.db.ensure_daily_goals(user["user_id"], day)
        goals = self.db.daily_goals(user["user_id"], day)
        return self._json({"ok": True, "goals": [{
            "kind": g["kind"], "target": g["target"],
            "progress": g["progress"], "reward": g["reward"],
            "claimed": g["claimed"], "done": int(g["progress"]) >= int(g["target"]),
        } for g in goals]})

    async def goal_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        kind = str(body.get("kind") or "")
        day = time.strftime("%Y-%m-%d")
        goal = self.db.claim_daily_goal(user["user_id"], day, kind)
        if not goal:
            return self._fail("Цель ещё не выполнена")
        self.db.add_balance(user["user_id"], int(goal["reward"]))
        self.db.add_tokens(user["user_id"], max(1, int(goal["reward"]) // 200))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": goal["reward"],
                           "balance": fresh["balance"]})

    # --- титул лидера ---------------------------------------------------
    async def leader_title_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, "title": self.db.leader_title(user["user_id"])})

    # --- данж-экспедиции ------------------------------------------------
    async def dungeon_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        run = self.db.active_dungeon(user["user_id"])
        best = self.db.dungeon_best(user["user_id"])
        return self._json({"ok": True,
                           "run": self._dungeon_run_view(run) if run else None,
                           "best": best})

    def _dungeon_run_view(self, run: dict) -> dict:
        return {
            "id": run["id"], "dungeon": run["dungeon"],
            "level": run["level"], "hp": run["hp"], "max_hp": run["max_hp"],
            "gold": run["gold"], "kills": run["kills"],
            "created_at": run["created_at"],
        }

    async def dungeon_start(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if self.db.active_dungeon(user["user_id"]):
            return self._fail("Есть активная экспедиция")
        body = await self._body(request)
        dungeon = str(body.get("dungeon") or "cave")
        if dungeon not in ("cave", "forest", "tower"):
            return self._fail("Неизвестный данж")
        run_id = str(uuid.uuid4())
        self.db.create_dungeon(run_id, user["user_id"], dungeon, 1)
        return self._json({"ok": True, "run_id": run_id})

    async def dungeon_fight(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        run_id = str(body.get("run_id") or "")
        run = self.db.dungeon_run(run_id)
        if not run or int(run["user_id"]) != user["user_id"]:
            return self._fail("Экспедиция не найдена")
        if run["status"] != "active":
            return self._fail("Экспедиция завершена")
        monster_hp = 30 + int(run["level"]) * 20
        damage = 25 + min(25, int(user.get("xp") or 0) // 200)
        monster_hp -= damage
        if monster_hp <= 0:
            gold = 80 * int(run["level"]) + random.randint(0, 60)
            kills = int(run["kills"]) + 1
            next_level = int(run["level"]) + 1
            self.db.dungeon_fight(run_id, int(run["hp"]), int(run["gold"]) + gold, kills)
            fresh_run = self.db.dungeon_run(run_id)
            return self._json({"ok": True, "killed": True, "gold": gold,
                               "level": next_level, "run": self._dungeon_run_view(fresh_run)})
        enemy_damage = 8 + int(run["level"]) * 3
        hp = int(run["hp"]) - enemy_damage
        self.db.dungeon_fight(run_id, max(0, hp), int(run["gold"]), int(run["kills"]))
        if hp <= 0:
            self.db.finish_dungeon(run_id, "dead")
            self.db.add_balance(user["user_id"], int(run["gold"]) // 2)
            fresh = self.db.user(user["user_id"])
            return self._json({"ok": True, "dead": True, "gold_saved": int(run["gold"]) // 2,
                               "balance": fresh["balance"]})
        return self._json({"ok": True, "damage_taken": enemy_damage,
                           "run": self._dungeon_run_view(self.db.dungeon_run(run_id))})

    async def dungeon_leave(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        run_id = str(body.get("run_id") or "")
        run = self.db.dungeon_run(run_id)
        if not run or int(run["user_id"]) != user["user_id"]:
            return self._fail("Экспедиция не найдена")
        self.db.finish_dungeon(run_id, "left")
        self.db.add_balance(user["user_id"], int(run["gold"]))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "gold": run["gold"],
                           "balance": fresh["balance"]})

    # --- подарки --------------------------------------------------------
    async def gifts_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        gifts = self.db.gifts_to(user["user_id"])
        view = []
        for g in gifts:
            sender = self.db.user(int(g["from_id"]))
            view.append({
                "id": g["id"], "from_id": g["from_id"],
                "from_name": sender["first_name"] if sender else "?",
                "gift": g["gift"], "note": g["note"],
                "created_at": g["created_at"],
            })
        return self._json({"ok": True, "gifts": view})

    async def gift_send(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        to_id = int(body.get("user_id") or 0)
        gift = str(body.get("gift") or "")
        note = str(body.get("note") or "").strip()
        if to_id == user["user_id"]:
            return self._fail("Нельзя подарить себе")
        target = self.db.user(to_id)
        if not target:
            return self._fail("Игрок не найден")
        if not self.db.are_friends(user["user_id"], to_id):
            return self._fail("Отправлять подарки можно только друзьям")
        gift_costs = {"charm": 80, "insurance": 60, "lootbox": 250,
                      "double_daily": 120}
        if gift not in gift_costs:
            return self._fail("Неизвестный подарок")
        cost = gift_costs[gift]
        if user["balance"] < cost:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -cost)
        self.db.send_gift(str(uuid.uuid4()), user["user_id"], to_id, gift, note)
        self.db.notify(to_id, "gift", "Вам подарок!",
                       f"@{user.get('username') or 'друг'} подарил вам подарок")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    async def gift_accept(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        gift_id = str(body.get("gift_id") or "")
        gift = self.db.gift(gift_id)
        if not gift or int(gift["to_id"]) != user["user_id"]:
            return self._fail("Подарок не найден")
        if not self.db.accept_gift(gift_id, user["user_id"]):
            return self._fail("Подарок уже принят")
        self.db.add_item(user["user_id"], gift["gift"], 1)
        self.db.notify(int(gift["from_id"]), "gift", "Подарок принят",
                       f"@{user.get('username') or 'друг'} принял ваш подарок")
        return self._json({"ok": True, "gift": gift["gift"]})

    # --- PvP-комнаты ----------------------------------------------------
    async def pvp_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.expire_pvp(int(time.time()), 3600)
        active = self.db.pvp_active_room(user["user_id"])
        rooms = self.db.pvp_rooms()
        view = []
        for r in rooms:
            owner = self.db.user(int(r["owner_id"]))
            view.append({
                "id": r["id"], "owner_id": r["owner_id"],
                "owner_name": owner["first_name"] if owner else "?",
                "game": r["game"], "bet": r["bet"],
                "created_at": r["created_at"],
            })
        return self._json({"ok": True, "rooms": view,
                           "active": self._pvp_view(active) if active else None})

    def _pvp_view(self, room: dict) -> dict:
        return {
            "id": room["id"], "game": room["game"], "bet": room["bet"],
            "status": room["status"], "owner_id": room["owner_id"],
            "guest_id": room.get("guest_id"),
            "owner_roll": room.get("owner_roll"),
            "guest_roll": room.get("guest_roll"),
            "winner_id": room.get("winner_id"),
            "created_at": room["created_at"],
        }

    async def pvp_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if self.db.pvp_active_room(user["user_id"]):
            return self._fail("У вас уже есть комната")
        body = await self._body(request)
        game_name = str(body.get("game") or "dice")
        if game_name not in ("dice", "coinflip", "crash"):
            return self._fail("Игра недоступна для PvP")
        bet = max(100, min(100000, int(body.get("bet") or 0)))
        if user["balance"] < bet:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -bet)
        room_id = str(uuid.uuid4())
        self.db.create_pvp_room(room_id, user["user_id"], game_name, bet)
        return self._json({"ok": True, "room_id": room_id})

    async def pvp_join(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        if self.db.pvp_active_room(user["user_id"]):
            return self._fail("У вас уже есть комната")
        body = await self._body(request)
        room_id = str(body.get("room_id") or "")
        room = self.db.pvp_room(room_id)
        if not room or room["status"] != "waiting":
            return self._fail("Комната не найдена")
        if int(room["owner_id"]) == user["user_id"]:
            return self._fail("Это ваша комната")
        bet = int(room["bet"])
        if user["balance"] < bet:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -bet)
        guest_roll = random.randint(1, 100)
        owner_roll = random.randint(1, 100)
        self.db.pvp_join(room_id, user["user_id"], guest_roll)
        self.db.pvp_room_owner_roll(room_id, owner_roll)
        winner = user["user_id"] if guest_roll >= owner_roll else int(room["owner_id"])
        self.db.pvp_finish(room_id, winner, int(time.time()))
        self.db.add_balance(winner, bet * 2)
        winner_user = self.db.user(winner)
        if winner_user:
            self.db.notify(winner, "pvp", "Победа в PvP!",
                           f"+{bet * 2} mCoin")
        loser = int(room["owner_id"]) if winner == user["user_id"] else user["user_id"]
        self.db.notify(loser, "pvp", "Поражение в PvP",
                       f"Комната {room['game']} закрыта")
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "winner": winner,
                           "owner_roll": owner_roll, "guest_roll": guest_roll,
                           "bet": bet, "balance": fresh["balance"]})

    # --- рабочие (пассивный доход) --------------------------------------
    async def workers_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        recipes = self.db.worker_recipes()
        mine = self.db.worker(user["user_id"])
        now = int(time.time())
        view = []
        for r in recipes:
            view.append({
                "worker": r["worker"], "cost": r["cost"],
                "income": r["income"], "period": r["period"],
                "hired": bool(mine and mine["worker"] == r["worker"]),
            })
        pending = 0
        if mine:
            recipe = next((r for r in recipes if r["worker"] == mine["worker"]),
                          None)
            if recipe:
                cycles = (now - int(mine["last_pay"])) // int(recipe["period"])
                pending = max(0, cycles) * int(recipe["income"])
        return self._json({"ok": True, "recipes": view,
                           "hired": mine["worker"] if mine else "",
                           "pending": pending,
                           "total_earned": int(mine["total_earned"] or 0)
                           if mine else 0})

    async def worker_hire(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        worker = str(body.get("worker") or "")
        recipe = next((r for r in self.db.worker_recipes()
                       if r["worker"] == worker), None)
        if not recipe:
            return self._fail("Рабочий не найден")
        if self.db.worker(user["user_id"]):
            return self._fail("У вас уже есть рабочий")
        cost = int(recipe["cost"])
        if user["balance"] < cost:
            return self._fail("Недостаточно mCoin")
        self.db.add_balance(user["user_id"], -cost)
        self.db.hire_worker(user["user_id"], worker)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    async def worker_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        earned = self.db.collect_worker(user["user_id"])
        if not earned:
            return self._fail("Ещё не накопилось")
        self.db.add_balance(user["user_id"], earned)
        self.db.add_xp(user["user_id"], max(1, earned // 100))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "earned": earned,
                           "balance": fresh["balance"]})

    # --- ферма ----------------------------------------------------------
    async def farm_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        plots = self.db.farm_plots(user["user_id"])
        layout = self.db.farm_layout(user["user_id"])
        view = []
        for plot in plots:
            view.append({
                "plot": plot["plot"], "crop": plot["crop"],
                "ready": bool(plot["crop"]) and not int(plot["collected"])
                and int(plot["ready_at"]) <= now,
                "seconds_left": max(0, int(plot["ready_at"]) - now)
                if plot["crop"] and not int(plot["collected"]) else 0,
                "collected": int(plot["collected"]),
            })
        crops = [
            {"key": "wheat", "title": "Пшеница", "grow": 300, "reward": 120},
            {"key": "carrot", "title": "Морковь", "grow": 600, "reward": 220},
            {"key": "pumpkin", "title": "Тыква", "grow": 1800, "reward": 700},
            {"key": "golden", "title": "Золотой клевер", "grow": 5400,
             "reward": 2500},
        ]
        return self._json({"ok": True, "plots": view, "layout": layout,
                           "crops": crops})

    async def farm_plant(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        plot = int(body.get("plot") or 0)
        crop_key = str(body.get("crop") or "")
        crop = next((c for c in [
            {"key": "wheat", "grow": 300, "reward": 120},
            {"key": "carrot", "grow": 600, "reward": 220},
            {"key": "pumpkin", "grow": 1800, "reward": 700},
            {"key": "golden", "grow": 5400, "reward": 2500},
        ] if c["key"] == crop_key), None)
        if not crop:
            return self._fail("Культура не найдена")
        row = self.db.farm_plot(user["user_id"], plot)
        if row and not int(row["collected"]):
            return self._fail("Грядка занята")
        if not self.db.plant_crop(user["user_id"], plot, crop_key,
                                  int(time.time()), int(crop["grow"])):
            return self._fail("Не удалось посадить")
        return self._json({"ok": True})

    async def farm_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        plot = int(body.get("plot") or 0)
        row = self.db.collect_crop(user["user_id"], plot)
        if not row:
            return self._fail("Ещё не выросло")
        reward = 0
        for c in [
                {"key": "wheat", "grow": 300, "reward": 120},
                {"key": "carrot", "grow": 600, "reward": 220},
                {"key": "pumpkin", "grow": 1800, "reward": 700},
                {"key": "golden", "grow": 5400, "reward": 2500}]:
            if c["key"] == row["crop"]:
                reward = c["reward"]
                break
        self.db.add_balance(user["user_id"], reward)
        self.db.add_tokens(user["user_id"], max(1, reward // 50))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "reward": reward,
                           "balance": fresh["balance"]})

    # --- battle pass ----------------------------------------------------
    async def battlepass_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        config = self.db.bp_config()
        bp = self.db.bp_get(user["user_id"])
        levels = config["levels"]
        return self._json({"ok": True, "season": config["season"],
                           "ends_at": config["ends_at"], "bp": bp,
                           "levels": levels})

    async def battlepass_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        cost = 50000
        if user["balance"] < cost:
            return self._fail("Недостаточно mCoin")
        if not self.db.bp_buy_premium(user["user_id"], cost):
            return self._fail("Премиум уже куплен")
        self.db.add_balance(user["user_id"], -cost)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "balance": fresh["balance"]})

    async def battlepass_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        level = int(body.get("level") or 0)
        premium = bool(body.get("premium"))
        config = self.db.bp_config()
        levels = config["levels"]
        reward_row = next((l for l in levels if int(l["level"]) == level), None)
        if not reward_row:
            return self._fail("Уровень не найден")
        answer = "premium" if premium else "free"
        amount = int(reward_row.get(answer) or 0)
        if premium and not self.db.bp_get(user["user_id"])["premium"]:
            return self._fail("Нет премиума")
        if not self.db.bp_claim_reward(user["user_id"], level, premium):
            return self._fail("Награда уже получена")
        if amount:
            self.db.add_balance(user["user_id"], amount)
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "amount": amount,
                           "balance": fresh["balance"]})

    # --- детальная статистика -------------------------------------------
    async def analytics_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        now = int(time.time())
        day_start = now - now % 86400
        rows = self.db._rows(
            "SELECT game, COUNT(*) AS n, COALESCE(SUM(bet), 0) AS wagered, "
            "COALESCE(SUM(CASE WHEN win = 1 THEN payout ELSE 0 END), 0) AS won "
            "FROM plays WHERE user_id = ? AND created_at >= ? "
            "GROUP BY game ORDER BY n DESC",
            (user["user_id"], day_start - 6 * 86400))
        by_game = []
        for r in rows:
            wins = self.db._row(
                "SELECT COUNT(*) AS w FROM plays WHERE user_id = ? "
                "AND game = ? AND win = 1 AND created_at >= ?",
                (user["user_id"], r["game"], day_start - 6 * 86400))
            by_game.append({
                "game": r["game"], "rounds": int(r["n"]),
                "wagered": int(r["wagered"]), "won": int(r["won"]),
                "wins": int(wins["w"]) if wins else 0,
            })
        daily = []
        for offset in range(6, -1, -1):
            start = day_start - offset * 86400
            row = self.db._row(
                "SELECT COUNT(*) AS n, COALESCE(SUM(bet), 0) AS wagered, "
                "COALESCE(SUM(CASE WHEN win = 1 THEN payout ELSE 0 END), 0) AS won "
                "FROM plays WHERE user_id = ? AND created_at >= ? "
                "AND created_at < ?",
                (user["user_id"], start, start + 86400))
            daily.append({
                "day": time.strftime("%d.%m", time.localtime(start)),
                "rounds": int(row["n"] or 0),
                "wagered": int(row["wagered"] or 0),
                "won": int(row["won"] or 0),
            })
        rank = self.db.rank(user["user_id"])
        level = game.level_view(user.get("xp") or 0)
        return self._json({
            "ok": True,
            "by_game": by_game,
            "daily": daily,
            "overview": {
                "rank": rank, "level": level["level"],
                "title": level["title"], "prestige": int(user.get("prestige") or 0),
                "best_multiplier": user.get("best_multiplier", 1.0),
                "games_played": user.get("games_played", 0),
                "total_wagered": user.get("total_wagered", 0),
                "total_won": user.get("total_won", 0),
            },
        })

    # --- календарь наград -----------------------------------------------
    async def calendar_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        claimed = self.db.calendar_claimed(user["user_id"])
        rewards = []
        for day in range(1, 31):
            rewards.append({
                "day": day,
                "reward": 200 + day * 150,
                "claimed": day in claimed,
            })
        return self._json({"ok": True, "rewards": rewards,
                           "claimed": sorted(claimed)})

    async def calendar_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        day = int(body.get("day") or 0)
        if day < 1 or day > 30:
            return self._fail("Некорректный день")
        claimed = self.db.calendar_claimed(user["user_id"])
        allowed = max(claimed, default=0) + 1
        if day in claimed:
            return self._fail("Уже получено")
        if day != allowed:
            return self._fail(f"Откройте день {allowed} первым")
        if not self.db.calendar_claim_day(user["user_id"], day):
            return self._fail("Уже получено")
        reward = 200 + day * 150
        self.db.add_balance(user["user_id"], reward)
        self.db.add_tokens(user["user_id"], max(1, day // 10))
        fresh = self.db.user(user["user_id"])
        return self._json({"ok": True, "day": day, "reward": reward,
                           "balance": fresh["balance"]})

    # --- новости --------------------------------------------------------
    async def news_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        self.db.ensure_news()
        items = self.db.news_items(20)
        read = self.db.news_read_ids(user["user_id"])
        view = []
        for n in items:
            view.append({
                "id": n["id"], "title": n["title"], "body": n["body"],
                "icon": n["icon"], "created_at": n["created_at"],
                "read": n["id"] in read,
            })
        return self._json({"ok": True, "news": view,
                           "unread": sum(1 for v in view if not v["read"])})

    async def news_read(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await self._body(request)
        news_id = str(body.get("news_id") or "")
        self.db.mark_news_read(user["user_id"], news_id)
        return self._json({"ok": True})

    # --- партнёрская программа v2 ---------------------------------------
    async def partners_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        stats = self.db.ref_stats(user["user_id"])
        levels = self.db.ref_levels()
        return self._json({"ok": True, "stats": {
            "children": stats["children"], "active": stats["active"],
            "level": stats["level"], "title": stats["title"],
            "bonus": stats["bonus"],
        }, "levels": [{
            "level": l["level"], "title": l["title"],
            "bonus": float(l["reward_bonus"]),
            "min_children": l["min_children"],
        } for l in levels]})

    async def partners_link(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        link = f"https://t.me/{config.bot_username or 'saperbot'}?start=ref_{user['user_id']}"
        return self._json({"ok": True, "link": link})

    # ==================== ЭКОНОМИКА V2 ====================

    async def economy_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        summary = self.db.economy_summary(user["user_id"])
        rates = self.db.currency_rates()
        stock_data = self.db.stock_symbols()
        trends = self.db.stock_trends()
        portfolio = self.db.stock_portfolio(user["user_id"])
        deposits = self.db.active_deposits(user["user_id"])
        log = self.db.economy_log(user["user_id"], 20)
        return self._json({
            "ok": True,
            "account": {
                "cash": summary["cash_balance"],
                "bank": summary["bank_balance"],
                "credits": summary["credits"],
                "gems": summary["gems"],
                "energy": summary["energy"],
                "energy_max": summary["energy_max"],
            },
            "wealth": summary["total_wealth"],
            "stock_value": summary["stock_value"],
            "deposit_value": summary["deposit_value"],
            "rates": rates,
            "stocks": stock_data,
            "trends": trends,
            "portfolio": portfolio,
            "deposits": deposits,
            "log": log,
        })

    async def economy_deposit(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        plan_id = str(body.get("plan_id", ""))
        amount = int(body.get("amount", 0))
        plans = {
            "starter": (500, 3.0, 3),
            "econom": (2000, 5.0, 7),
            "growth": (5000, 7.5, 14),
            "premium": (10000, 10.0, 30),
        }
        if plan_id not in plans:
            return self._fail("bad_plan")
        principal, interest, term = plans[plan_id]
        if amount < principal:
            return self._fail("too_small")
        if self.db.economy_balance(user["user_id"], "gold") < amount:
            return self._fail("no_funds")
        self.db.economy_transfer(user["user_id"], "gold", -amount, "deposit_open")
        self.db.open_deposit(user["user_id"], plan_id, amount, interest, term)
        return self._json({"ok": True, "plan": {
            "plan_id": plan_id, "principal": amount, "interest_pct": interest,
            "term_days": term, "started_at": int(time.time()),
        }})

    async def economy_deposit_close(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        plan_id = str(body.get("plan_id", ""))
        plan = self.db.close_deposit(user["user_id"], plan_id)
        if not plan:
            return self._fail("no_plan")
        elapsed_days = max(0, (int(time.time()) - int(plan["started_at"])) // 86400)
        full = elapsed_days >= int(plan["term_days"])
        interest = int(int(plan["principal"]) * float(plan["interest_pct"]) / 100.0)
        if not full:
            interest = int(interest * min(1.0, elapsed_days / max(1, int(plan["term_days"]))))
        payout = int(plan["principal"]) + interest
        self.db.economy_transfer(user["user_id"], "gold", payout, "deposit_close")
        return self._json({"ok": True, "payout": payout, "interest": interest,
                           "full": full})

    async def economy_exchange(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        from_cur = str(body.get("from", ""))
        to_cur = str(body.get("to", ""))
        amount = int(body.get("amount", 0))
        if amount <= 0 or from_cur == to_cur:
            return self._fail("bad_exchange")
        rates = self.db.currency_rates()
        if from_cur not in rates or to_cur not in rates:
            return self._fail("bad_currency")
        from_rate = float(rates[from_cur]["rate"])
        to_rate = float(rates[to_cur]["rate"])
        if self.db.economy_balance(user["user_id"], from_cur) < amount:
            return self._fail("no_funds")
        converted = int(amount * from_rate / to_rate)
        if converted <= 0:
            return self._fail("too_small")
        self.db.economy_transfer(user["user_id"], from_cur, -amount, "exchange_out")
        self.db.economy_transfer(user["user_id"], to_cur, converted, "exchange_in")
        return self._json({"ok": True, "converted": converted})

    async def economy_stock_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        symbol = str(body.get("symbol", "")).upper()
        shares = int(body.get("shares", 0))
        ok = self.db.stock_buy(user["user_id"], symbol, shares)
        if not ok:
            return self._fail("trade_failed")
        portfolio = self.db.stock_portfolio(user["user_id"])
        balance = self.db.economy_balance(user["user_id"], "gold")
        return self._json({"ok": True, "portfolio": portfolio, "balance": balance})

    async def economy_stock_sell(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        symbol = str(body.get("symbol", "")).upper()
        shares = int(body.get("shares", 0))
        ok = self.db.stock_sell(user["user_id"], symbol, shares)
        if not ok:
            return self._fail("trade_failed")
        portfolio = self.db.stock_portfolio(user["user_id"])
        balance = self.db.economy_balance(user["user_id"], "gold")
        return self._json({"ok": True, "portfolio": portfolio, "balance": balance})

    # ==================== ГИЛЬДИИ-ЗДАНИЯ ====================

    def _require_clan(self, user_id: int) -> dict | None:
        clan = self.db.user_clan(user_id)
        return clan

    async def guild_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self.db.user_clan(user["user_id"])
        if not clan:
            return self._json({"ok": True, "clan": None})
        res = self.db.guild_resources(clan["id"])
        production = self.db.guild_production(clan["id"])
        buildings = self.db.guild_buildings(clan["id"])
        power = self.db.guild_power(clan["id"])
        tax_history = self.db.guild_tax_history(clan["id"], 15)
        return self._json({
            "ok": True,
            "clan": {
                "id": clan["id"], "name": clan["name"], "tag": clan["tag"],
                "xp": clan["xp"], "level": clan["level"],
                "members": self.db.clan_count(clan["id"]),
                "member_limit": self.db.guild_member_limit(clan["id"]),
                "power": power,
            },
            "resources": res,
            "production": production,
            "buildings": buildings,
            "tax_history": tax_history,
        })

    async def guild_upgrade(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        building = str(body.get("building", ""))
        result = self.db.guild_upgrade(clan["id"], building)
        if not result:
            return self._fail("bad_building")
        if result.get("error") == "max_level":
            return self._fail("max_level")
        if result.get("error") == "no_resources":
            return self._fail("no_resources")
        return self._json({"ok": True, "level": result["level"],
                           "cost": result["cost"],
                           "resources": self.db.guild_resources(clan["id"])})

    async def guild_donate(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        resource = str(body.get("resource", ""))
        amount = int(body.get("amount", 0))
        if amount <= 0:
            return self._fail("bad_amount")
        if resource not in ("wood", "stone", "iron", "food"):
            return self._fail("bad_resource")
        cost_gold = int(amount * 2)
        if self.db.economy_balance(user["user_id"], "gold") < cost_gold:
            return self._fail("no_funds")
        self.db.economy_transfer(user["user_id"], "gold", -cost_gold, "guild_donate")
        self.db.guild_add_resource(clan["id"], resource, amount)
        self.db.add_clan_xp(clan["id"], amount // 10)
        return self._json({"ok": True, "resources": self.db.guild_resources(clan["id"])})

    async def guild_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        production = self.db.guild_production(clan["id"])
        return self._json({"ok": True, "production": production})

    async def guild_war_bonus(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        barracks = self.db.guild_building_level(clan["id"], "barracks")
        return self._json({"ok": True, "war_bonus_pct": barracks * 6,
                           "barracks_level": barracks})

    # ==================== ГЛОБАЛЬНАЯ КАРТА ====================

    async def map_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        provinces = self.db.provinces()
        stats = self.db.map_stats()
        clan = self.db.user_clan(user["user_id"])
        my_provinces = []
        if clan:
            my_provinces = [p for p in provinces if p["owner_clan"] == clan["id"]]
        return self._json({
            "ok": True,
            "provinces": provinces,
            "stats": stats,
            "my_clan": clan["id"] if clan else None,
            "my_provinces": my_provinces,
        })

    async def map_claim(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        province_id = str(body.get("province_id", ""))
        result = self.db.map_claim(province_id, clan["id"], user["user_id"])
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, "cost": result["cost"],
                           "province": self.db.province(province_id)})

    async def map_attack(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        province_id = str(body.get("province_id", ""))
        force = int(body.get("force", 100))
        result = self.db.map_attack(province_id, clan["id"], user["user_id"], force)
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, **result})

    async def map_capture(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        province_id = str(body.get("province_id", ""))
        result = self.db.map_capture(province_id, clan["id"], user["user_id"])
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, "cost": result["cost"],
                           "province": self.db.province(province_id)})

    async def map_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        clan = self._require_clan(user["user_id"])
        if not clan:
            return self._fail("no_clan")
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        province_id = str(body.get("province_id", ""))
        result = self.db.map_collect(province_id, clan["id"])
        if result.get("error") == "not_owner":
            return self._fail("not_owner")
        if result.get("error") == "too_soon":
            return self._fail("too_soon")
        return self._json({"ok": True, **result,
                           "resources": self.db.guild_resources(clan["id"])})

    async def map_events(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        province_id = str(body.get("province_id", ""))
        events = self.db.map_events(province_id, 10)
        return self._json({"ok": True, "events": events})

    # ==================== ТУРНИРНЫЙ СЕЗОН ====================

    async def tournament_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        seasons = self.db.tournament_seasons()
        my = self.db.tournament_my(user["user_id"])
        out = []
        for s in seasons:
            sid = s["season_id"]
            participants = self.db.tournament_participants(sid)
            matches = self.db.tournament_matches(sid)
            prizes = self.db._rows(
                "SELECT * FROM tournament_prizes WHERE season_id = ? ORDER BY place",
                (sid,))
            my_p = next((p for p in participants if p["user_id"] == user["user_id"]), None)
            out.append({
                "season": s,
                "participants": participants,
                "matches": matches,
                "prizes": prizes,
                "my_participant": my_p,
            })
        return self._json({"ok": True, "seasons": out, "my_seasons": my})

    async def tournament_qualify(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        season_id = str(body.get("season_id", ""))
        score = float(body.get("score", 0))
        season = self.db.tournament_season(season_id)
        if not season:
            return self._fail("no_season")
        if season["status"] != "qualify":
            return self._fail("not_qualify_phase")
        self.db.tournament_qualify(season_id, user["user_id"], score)
        return self._json({"ok": True, "score": score})

    async def tournament_play(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        match_id = str(body.get("match_id", ""))
        score = float(body.get("score", 0))
        result = self.db.tournament_play(match_id, user["user_id"], score)
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, **result})

    async def tournament_prizes(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        season_id = str(body.get("season_id", ""))
        prizes = self.db._rows(
            "SELECT * FROM tournament_prizes WHERE season_id = ? ORDER BY place",
            (season_id,))
        return self._json({"ok": True, "prizes": prizes})

    # ==================== КОЛЛЕКЦИОННЫЕ НАБОРЫ ====================

    async def card_market_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        cards = self.db.cards(user["user_id"])
        duplicates = self.db.card_duplicates(user["user_id"])
        dust = self.db.card_dust(user["user_id"])
        progress = self.db.card_progress(user["user_id"])
        album = self.db.card_album()
        offers = self.db.card_market_offers(limit=30)
        my_offers = self.db.card_market_offers(user["user_id"], limit=10)
        return self._json({
            "ok": True,
            "cards": cards, "duplicates": duplicates, "dust": dust,
            "progress": progress, "album": album,
            "offers": offers, "my_offers": my_offers,
        })

    async def card_dismantle(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        card = str(body.get("card", ""))
        qty = int(body.get("qty", 1))
        gain = self.db.card_dismantle(user["user_id"], card, qty)
        if gain <= 0:
            return self._fail("no_duplicates")
        return self._json({"ok": True, "gain": gain,
                           "tokens": self.db.tokens(user["user_id"])})

    async def card_offer_create(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        card = str(body.get("card", ""))
        price = int(body.get("price", 0))
        if price <= 0:
            return self._fail("bad_price")
        import uuid
        offer_id = uuid.uuid4().hex[:12]
        ok = self.db.card_offer_create(offer_id, user["user_id"], card, price, 1)
        if not ok:
            return self._fail("no_card")
        return self._json({"ok": True, "offer_id": offer_id,
                           "cards": self.db.cards(user["user_id"])})

    async def card_offer_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        offer_id = str(body.get("offer_id", ""))
        ok = self.db.card_offer_buy(offer_id, user["user_id"])
        if not ok:
            return self._fail("buy_failed")
        return self._json({"ok": True,
                           "cards": self.db.cards(user["user_id"]),
                           "tokens": self.db.tokens(user["user_id"])})

    async def card_offer_cancel(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        offer_id = str(body.get("offer_id", ""))
        ok = self.db.card_offer_cancel(offer_id, user["user_id"])
        if not ok:
            return self._fail("cancel_failed")
        return self._json({"ok": True,
                           "cards": self.db.cards(user["user_id"])})

    # ==================== УЛИЦА (Mirage-style) ====================

    async def street_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        stats = self.db.user(user["user_id"])
        exp = int(stats["xp"]) if stats else 0
        properties = self.db.street_properties(user["user_id"])
        income = self.db.street_income(user["user_id"])
        jobs = self.db.street_jobs()
        my_job = self.db.street_my_job(user["user_id"])
        jackpot = self.db.jackpot()
        my_tickets = self.db.jackpot_my_tickets(user["user_id"])
        return self._json({
            "ok": True,
            "exp": exp,
            "properties": properties,
            "income": income,
            "jobs": jobs,
            "my_job": my_job,
            "jackpot": {
                "pool": jackpot["pool"],
                "last_winner": jackpot["last_winner"],
                "last_win_amt": jackpot["last_win_amt"],
                "next_draw": jackpot["next_draw"],
            },
            "my_tickets": my_tickets,
            "cash": self.db.economy_balance(user["user_id"], "gold"),
        })

    async def street_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        prop_type = str(body.get("prop_type", ""))
        result = self.db.street_buy(user["user_id"], prop_type)
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, "level": result["level"],
                           "cost": result["cost"],
                           "income": self.db.street_income(user["user_id"]),
                           "cash": self.db.economy_balance(user["user_id"], "gold")})

    async def street_job_apply(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        job_key = str(body.get("job_key", ""))
        stats = self.db.user(user["user_id"])
        exp = int(stats["xp"]) if stats else 0
        result = self.db.street_apply_job(user["user_id"], job_key, exp)
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, "job": job_key})

    async def street_job_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        result = self.db.street_collect_job(user["user_id"])
        if result.get("error") == "cooldown":
            return self._json({"ok": False, "error": "cooldown",
                               "wait": result["wait"]})
        if result.get("error"):
            return self._fail(result["error"])
        return self._json({"ok": True, "reward": result["reward"],
                           "job": result["job"],
                           "cash": self.db.economy_balance(user["user_id"], "gold")})

    async def jackpot_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        jackpot = self.db.jackpot()
        return self._json({
            "ok": True,
            "pool": jackpot["pool"],
            "last_winner": jackpot["last_winner"],
            "last_win_amt": jackpot["last_win_amt"],
            "last_win_at": jackpot["last_win_at"],
            "next_draw": jackpot["next_draw"],
            "my_tickets": self.db.jackpot_my_tickets(user["user_id"]),
            "cash": self.db.economy_balance(user["user_id"], "gold"),
        })

    async def jackpot_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        amount = int(body.get("amount", 0))
        result = self.db.jackpot_add(user["user_id"], amount)
        if "error" in result:
            return self._fail(result["error"])
        return self._json({"ok": True, "ticket": result["ticket"],
                           "pool": self.db.jackpot()["pool"],
                           "cash": self.db.economy_balance(user["user_id"], "gold")})

    async def jackpot_draw(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        result = self.db.jackpot_draw()
        return self._json({"ok": True, **result})

    # ==================== ПИТОМЦЫ ====================

    async def pet_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True, **self.db.pet_state(user["user_id"])})

    async def pet_buy(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await request.json()
        pet_type = str(body.get("pet_type") or "").strip().lower()
        pet = self.db.pet_buy(user["user_id"], pet_type)
        if not pet:
            return self._json({"ok": False, "error": "bad_pet_type"})
        return self._json({"ok": True, **self.db.pet_state(user["user_id"])})

    async def pet_feed(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        pet = self.db.pet_feed(user["user_id"])
        if not pet:
            return self._json({"ok": False, "error": "cannot_feed"})
        return self._json({"ok": True, **self.db.pet_state(user["user_id"])})

    async def pet_collect(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True,
                           **self.db.pet_collect(user["user_id"])})

    async def pet_play(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        result = self.db.pet_play(user["user_id"])
        if not result.get("ok") and result.get("error") == "cooldown":
            return self._json({"ok": False, "error": "cooldown",
                               "cooldown_left": result.get("cooldown_left")})
        return self._json(result)

    async def pet_top(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True,
                           "top": self.db.pet_top(10)})

    async def club_history(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        return self._json({"ok": True,
                           "history": self.db.club_history(6)})

    # ==================== ШАХМАТНЫЙ КЛУБ ====================

    async def club_view(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        state = self.db.club_season_state(user["user_id"])
        return self._json({"ok": True, **state})

    def _club_resolve_season(self, season_id: int) -> int | None:
        if season_id in (None, 0):
            return int(self.db.club_active_season()["id"])
        s = self.db.club_season(season_id)
        return int(s["id"]) if s else None

    async def club_join(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await request.json()
        try:
            season_id = int(body.get("season_id", 0))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "bad_season_id"})
        sid = self._club_resolve_season(season_id)
        if not sid:
            return self._json({"ok": False, "error": "season_not_found"})
        s = self.db.club_season(sid)
        if not s or s["status"] != "open":
            return self._json({"ok": False, "error": "season_not_open"})
        if self.db.club_active_entries_count(user["user_id"]) >= self.db.CLUB_MAX_ACTIVE:
            return self._json({"ok": False, "error": "active_limit"})
        entry = self.db.club_join(user["user_id"], sid)
        if not entry:
            return self._json({"ok": False, "error": "not_enough"})
        return self._json({"ok": True, "entry": entry,
                           "balance": self.db.economy_balance(
                               user["user_id"], "gold")})

    async def club_boss_result(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await request.json()
        try:
            season_id = int(body.get("season_id", 0))
            round_no = int(body.get("round", 0))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "bad_params"})
        if round_no < 1 or round_no > self.db.CLUB_LEVELS:
            return self._json({"ok": False, "error": "bad_round"})
        sid = self._club_resolve_season(season_id)
        if not sid:
            return self._json({"ok": False, "error": "season_not_found"})
        s = self.db.club_season(sid)
        if not s or s["status"] != "open":
            return self._json({"ok": False, "error": "season_not_open"})
        entry = self.db.club_entry(sid, user["user_id"])
        if not entry:
            return self._json({"ok": False, "error": "not_joined"})
        my_round = int(entry["finished_round"])
        if round_no != my_round + 1:
            return self._json({"ok": False, "error": "bad_round_order"})
        reward = self.db.CLUB_BOSS_REWARDS[round_no - 1]
        week_won = self.db.club_week_won(user["user_id"])
        if week_won + reward > self.db.CLUB_WEEK_LIMIT:
            return self._json({"ok": False, "error": "week_limit"})
        self.db.economy_transfer(user["user_id"], "gold", reward, "club_boss")
        prog = self.db.club_update_progress(sid, user["user_id"], reward)
        self.db.club_win_log(user["user_id"], sid, reward)
        return self._json({"ok": True, "reward": reward, "progress": prog,
                           "balance": self.db.economy_balance(
                               user["user_id"], "gold")})

    async def club_playoff(self, request: web.Request) -> web.Response:
        user = self._auth(request)
        if not user:
            return self._fail("unauthorized", 401)
        body = await request.json()
        try:
            season_id = int(body.get("season_id", 0))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "bad_season_id"})
        sid = self._club_resolve_season(season_id)
        if not sid:
            return self._json({"ok": False, "error": "season_not_found"})
        s = self.db.club_season(sid)
        if not s:
            return self._json({"ok": False, "error": "season_not_found"})
        if s["status"] == "open":
            return self._json({"ok": False, "error": "season_open"})
        top = [dict(r) for r in self.db.club_top_entries(sid, 8)]
        for t in top:
            t["nick"] = self.db.club_username(int(t["user_id"]))
        if s["status"] == "finished":
            return self._json({"ok": True, "top": top,
                               "winner": s["winner_id"]})
        if not top:
            self.db.club_set_season_status(sid, "finished", None)
            return self._json({"ok": True, "top": [], "winner": None,
                               "season_status": "finished"})
        winner_id = int(top[0]["user_id"])
        self.db.economy_transfer(winner_id, "gold",
                                 self.db.CLUB_PLAYOFF_NET, "club_playoff")
        self.db.club_win_log(winner_id, sid, self.db.CLUB_PLAYOFF_NET)
        self.db.club_set_season_status(sid, "finished", winner_id)
        return self._json({"ok": True, "top": top, "winner": winner_id,
                           "prize": self.db.CLUB_PLAYOFF_NET,
                           "season_status": "finished"})

    # ==================== АДМИН-ЭКОНОМИКА ====================

    async def admin_economy_view(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        return self._json({"ok": True, "economy": self.db.admin_economy(),
                           "bans": self.db.admin_action_bans()})

    async def admin_emit(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        user_id = int(body.get("user_id", 0))
        amount = int(body.get("amount", 0))
        currency = str(body.get("currency", "gold"))
        reason = str(body.get("reason", "admin"))
        if user_id <= 0 or amount == 0:
            return self._fail("bad_args")
        new_balance = self.db.admin_emit(user_id, amount, currency, reason)
        self.db.admin_log(int(admin["user_id"]), user_id,
                          f"emit {currency} {amount} ({reason})")
        return self._json({"ok": True, "user_id": user_id,
                           "currency": currency, "balance": new_balance})

    async def admin_set_rate(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        currency = str(body.get("currency", ""))
        rate = float(body.get("rate", 0))
        if not currency or rate <= 0:
            return self._fail("bad_args")
        self.db.admin_set_rate(currency, rate)
        self.db.admin_log(int(admin["user_id"]), None,
                          f"rate {currency} = {rate}")
        return self._json({"ok": True, "rates": self.db.currency_rates()})

    async def admin_set_commission(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        tax_key = str(body.get("tax_key", ""))
        rate = float(body.get("rate", 0))
        if tax_key not in ("trade", "guild_market", "premium", "withdraw"):
            return self._fail("bad_key")
        self.db.admin_set_commission(tax_key, rate)
        self.db.admin_log(int(admin["user_id"]), None,
                          f"commission {tax_key} = {rate}%")
        return self._json({"ok": True, "taxes": {t: self.db.tax_rate(t)
                          for t in ("trade", "guild_market", "premium", "withdraw")}})

    async def admin_inflation(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        pct = float(body.get("pct", 0))
        if not (0 < pct <= 100):
            return self._fail("bad_args")
        changed = self.db.admin_inflation(pct)
        self.db.admin_log(int(admin["user_id"]), None,
                          f"inflation {pct}%")
        return self._json({"ok": True, "changed": changed,
                           "rates": self.db.currency_rates()})

    async def admin_grant_tokens(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        user_id = int(body.get("user_id", 0))
        amount = int(body.get("amount", 0))
        reason = str(body.get("reason", "admin"))
        if user_id <= 0 or amount <= 0:
            return self._fail("bad_args")
        new_tokens = self.db.admin_grant_tokens(user_id, amount, reason)
        self.db.admin_log(int(admin["user_id"]), user_id,
                          f"grant tokens {amount} ({reason})")
        return self._json({"ok": True, "user_id": user_id,
                           "tokens": new_tokens})

    async def admin_action_ban(self, request: web.Request) -> web.Response:
        admin, err = self._require_admin(request)
        if err is not None:
            return err
        try:
            body = await request.json()
        except Exception:
            return self._fail("bad_request")
        user_id = int(body.get("user_id", 0))
        action = body.get("action")
        if user_id <= 0:
            return self._fail("bad_args")
        if action is None or not str(action):
            self.db.admin_action_ban(user_id)
        else:
            self.db.admin_action_ban(user_id, str(action))
        self.db.admin_log(int(admin["user_id"]), user_id,
                          f"action_ban {action}")
        return self._json({"ok": True, "bans": self.db.admin_action_bans()})


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
    app.router.add_post("/api/profile/stats", api.profile_stats)
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
    app.router.add_post("/api/clans", api.clans)
    app.router.add_post("/api/clans/create", api.clan_create)
    app.router.add_post("/api/clans/join", api.clan_join)
    app.router.add_post("/api/clans/leave", api.clan_leave)
    app.router.add_post("/api/clans/kick", api.clan_kick)
    app.router.add_post("/api/clans/promote", api.clan_promote)
    app.router.add_post("/api/clans/update", api.clan_update)
    app.router.add_post("/api/clans/requests", api.clan_requests)
    app.router.add_post("/api/clans/accept", api.clan_accept)
    app.router.add_post("/api/clans/decline", api.clan_decline)
    app.router.add_post("/api/clans/invite", api.clan_invite)
    app.router.add_post("/api/clans/accept-invite", api.clan_accept_invite)
    app.router.add_post("/api/clans/decline-invite", api.clan_decline_invite)
    app.router.add_post("/api/clans/msg", api.clan_msg)
    app.router.add_post("/api/clans/messages", api.clan_msgs)
    app.router.add_post("/api/clans/disband", api.clan_disband)
    app.router.add_post("/api/friends", api.friends_list)
    app.router.add_post("/api/friends/add", api.friend_add)
    app.router.add_post("/api/friends/accept", api.friend_accept)
    app.router.add_post("/api/friends/decline", api.friend_decline)
    app.router.add_post("/api/friends/remove", api.friend_remove)
    app.router.add_post("/api/market", api.market_list)
    app.router.add_post("/api/market/create", api.market_create)
    app.router.add_post("/api/market/buy", api.market_buy)
    app.router.add_post("/api/market/cancel", api.market_cancel)
    app.router.add_post("/api/market/my", api.market_my_lots)
    app.router.add_post("/api/auction", api.auction_list)
    app.router.add_post("/api/auction/create", api.auction_create)
    app.router.add_post("/api/auction/bid", api.auction_bid)
    app.router.add_post("/api/leagues", api.leagues_view)
    app.router.add_post("/api/leagues/claim", api.league_claim)
    app.router.add_post("/api/achievements", api.achievements_detail)
    app.router.add_post("/api/achievements/claim", api.achievement_claim)
    app.router.add_post("/api/auto/start", api.auto_start)
    app.router.add_post("/api/auto/stop", api.auto_stop)
    app.router.add_post("/api/auto/status", api.auto_status)
    app.router.add_post("/api/bots", api.bots_list)
    app.router.add_post("/api/tournaments", api.tournaments_list)
    app.router.add_post("/api/tournaments/join", api.tournament_join)
    app.router.add_post("/api/tournaments/info", api.tournament_info)
    app.router.add_post("/api/notifications", api.notifications_list)
    app.router.add_post("/api/notifications/read", api.notifications_read)
    app.router.add_post("/api/wars", api.wars_list)
    app.router.add_post("/api/wars/start", api.war_start)
    app.router.add_post("/api/wars/bet", api.war_bet)
    app.router.add_post("/api/raids", api.raids_list)
    app.router.add_post("/api/raids/start", api.raid_start)
    app.router.add_post("/api/raids/hit", api.raid_hit)
    app.router.add_post("/api/loans", api.loans_view)
    app.router.add_post("/api/loans/take", api.loan_take)
    app.router.add_post("/api/loans/pay", api.loan_pay)
    app.router.add_post("/api/streaks", api.streaks_view)
    app.router.add_post("/api/streaks/claim", api.streak_claim)
    app.router.add_post("/api/fishing/level", api.fishing_level)
    app.router.add_post("/api/craft", api.craft_view)
    app.router.add_post("/api/craft/start", api.craft_start)
    app.router.add_post("/api/craft/claim", api.craft_claim)
    app.router.add_post("/api/chests", api.chests_view)
    app.router.add_post("/api/chests/open", api.chest_open)
    app.router.add_post("/api/ships", api.ships_view)
    app.router.add_post("/api/ships/buy", api.ship_buy)
    app.router.add_post("/api/tournaments/rewards", api.tournament_rewards_view)
    app.router.add_post("/api/tournaments/reward-claim", api.tournament_reward_claim)
    app.router.add_post("/api/users/search", api.user_search)
    app.router.add_post("/api/prestige", api.prestige_view)
    app.router.add_post("/api/prestige/do", api.prestige_do)
    app.router.add_post("/api/orders", api.orders_view)
    app.router.add_post("/api/orders/claim", api.order_claim)
    app.router.add_post("/api/tokens", api.tokens_view)
    app.router.add_post("/api/tokens/exchange", api.tokens_exchange)
    app.router.add_post("/api/cards", api.cards_view)
    app.router.add_post("/api/cards/unpack", api.card_unpack)
    app.router.add_post("/api/energy", api.energy_view)
    app.router.add_post("/api/energy/buy", api.energy_buy)
    app.router.add_post("/api/arena", api.arena_view)
    app.router.add_post("/api/arena/fight", api.arena_fight)
    app.router.add_post("/api/bingo/new", api.bingo_new)
    app.router.add_post("/api/bingo/mark", api.bingo_mark)
    app.router.add_post("/api/encyclopedia", api.encyclopedia)
    app.router.add_post("/api/live", api.live_view)
    app.router.add_post("/api/live/create", api.live_create)
    app.router.add_post("/api/live/bet", api.live_bet)
    app.router.add_post("/api/live/finish", api.live_finish)
    app.router.add_post("/api/events", api.events_view)
    app.router.add_post("/api/events/claim", api.event_claim)
    app.router.add_post("/api/restaurant", api.restaurant_view)
    app.router.add_post("/api/restaurant/cook", api.restaurant_cook)
    app.router.add_post("/api/restaurant/take", api.restaurant_take)
    app.router.add_post("/api/medals", api.medals_view)
    app.router.add_post("/api/goals", api.goals_view)
    app.router.add_post("/api/goals/claim", api.goal_claim)
    app.router.add_post("/api/leader-title", api.leader_title_view)
    app.router.add_post("/api/dungeon", api.dungeon_view)
    app.router.add_post("/api/dungeon/start", api.dungeon_start)
    app.router.add_post("/api/dungeon/fight", api.dungeon_fight)
    app.router.add_post("/api/dungeon/leave", api.dungeon_leave)
    app.router.add_post("/api/gifts", api.gifts_view)
    app.router.add_post("/api/gifts/send", api.gift_send)
    app.router.add_post("/api/gifts/accept", api.gift_accept)
    app.router.add_post("/api/pvp", api.pvp_view)
    app.router.add_post("/api/pvp/create", api.pvp_create)
    app.router.add_post("/api/pvp/join", api.pvp_join)
    app.router.add_post("/api/workers", api.workers_view)
    app.router.add_post("/api/workers/hire", api.worker_hire)
    app.router.add_post("/api/workers/collect", api.worker_collect)
    app.router.add_post("/api/farm", api.farm_view)
    app.router.add_post("/api/farm/plant", api.farm_plant)
    app.router.add_post("/api/farm/collect", api.farm_collect)
    app.router.add_post("/api/battlepass", api.battlepass_view)
    app.router.add_post("/api/battlepass/buy", api.battlepass_buy)
    app.router.add_post("/api/battlepass/claim", api.battlepass_claim)
    app.router.add_post("/api/analytics", api.analytics_view)
    app.router.add_post("/api/calendar", api.calendar_view)
    app.router.add_post("/api/calendar/claim", api.calendar_claim)
    app.router.add_post("/api/news", api.news_view)
    app.router.add_post("/api/news/read", api.news_read)
    app.router.add_post("/api/partners", api.partners_view)
    app.router.add_post("/api/partners/link", api.partners_link)
    app.router.add_post("/api/economy", api.economy_view)
    app.router.add_post("/api/economy/deposit", api.economy_deposit)
    app.router.add_post("/api/economy/deposit/close", api.economy_deposit_close)
    app.router.add_post("/api/economy/exchange", api.economy_exchange)
    app.router.add_post("/api/economy/stock/buy", api.economy_stock_buy)
    app.router.add_post("/api/economy/stock/sell", api.economy_stock_sell)
    app.router.add_post("/api/guild", api.guild_view)
    app.router.add_post("/api/guild/upgrade", api.guild_upgrade)
    app.router.add_post("/api/guild/donate", api.guild_donate)
    app.router.add_post("/api/guild/collect", api.guild_collect)
    app.router.add_post("/api/guild/war-bonus", api.guild_war_bonus)
    app.router.add_post("/api/map", api.map_view)
    app.router.add_post("/api/map/claim", api.map_claim)
    app.router.add_post("/api/map/attack", api.map_attack)
    app.router.add_post("/api/map/capture", api.map_capture)
    app.router.add_post("/api/map/collect", api.map_collect)
    app.router.add_post("/api/map/events", api.map_events)
    app.router.add_post("/api/tournament", api.tournament_view)
    app.router.add_post("/api/tournament/qualify", api.tournament_qualify)
    app.router.add_post("/api/tournament/play", api.tournament_play)
    app.router.add_post("/api/tournament/prizes", api.tournament_prizes)
    app.router.add_post("/api/cards/market", api.card_market_view)
    app.router.add_post("/api/cards/dismantle", api.card_dismantle)
    app.router.add_post("/api/cards/offer/create", api.card_offer_create)
    app.router.add_post("/api/cards/offer/buy", api.card_offer_buy)
    app.router.add_post("/api/cards/offer/cancel", api.card_offer_cancel)
    app.router.add_post("/api/street", api.street_view)
    app.router.add_post("/api/street/buy", api.street_buy)
    app.router.add_post("/api/street/job/apply", api.street_job_apply)
    app.router.add_post("/api/street/job/collect", api.street_job_collect)
    app.router.add_post("/api/jackpot", api.jackpot_view)
    app.router.add_post("/api/jackpot/buy", api.jackpot_buy)
    app.router.add_post("/api/jackpot/draw", api.jackpot_draw)
    app.router.add_post("/api/admin/economy", api.admin_economy_view)
    app.router.add_post("/api/admin/emit", api.admin_emit)
    app.router.add_post("/api/admin/rate", api.admin_set_rate)
    app.router.add_post("/api/admin/commission", api.admin_set_commission)
    app.router.add_post("/api/admin/inflation", api.admin_inflation)
    app.router.add_post("/api/admin/grant-tokens", api.admin_grant_tokens)
    app.router.add_post("/api/admin/action-ban", api.admin_action_ban)
    app.router.add_post("/api/club", api.club_view)
    app.router.add_post("/api/club/join", api.club_join)
    app.router.add_post("/api/club/boss-result", api.club_boss_result)
    app.router.add_post("/api/club/playoff", api.club_playoff)
    app.router.add_post("/api/pet", api.pet_view)
    app.router.add_post("/api/pet/buy", api.pet_buy)
    app.router.add_post("/api/pet/feed", api.pet_feed)
    app.router.add_post("/api/pet/collect", api.pet_collect)
    app.router.add_post("/api/pet/play", api.pet_play)
    app.router.add_post("/api/pet/top", api.pet_top)
    app.router.add_post("/api/club/history", api.club_history)

    here = __import__("os").path.dirname(__file__)
    web_dir = __import__("os").path.join(here, "web")
    if not __import__("os").path.isdir(web_dir):
        web_dir = here

    async def index(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(__import__("os").path.join(web_dir, "index.html"))

    app.router.add_get("/", index)
    app.router.add_static("/static/", web_dir, show_index=False)
    return app
