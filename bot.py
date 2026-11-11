import asyncio
import math
import time
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MenuButtonWebApp,
    WebAppInfo,
)

import awards
import game
import updates
from config import config
from db import Database

CELL_CLOSED = "▫️"
CELL_OPEN = "💎"
CELL_MINE = "💣"

DEPOSIT_AMOUNTS = (100, 500, 1000, 5000, 10000, 25000)
SAVINGS_AMOUNTS = (100, 500, 1000, 5000)
DICE_BETS = (100, 500, 1000)
CALLBACK_LIMIT = 64

WELCOME = (
    "💣 <b>Апрельский сапёр</b>\n\n"
    "Играть можно и в приложении, и прямо здесь — в чате.\n\n"
    "• /mines 100 5 — поле 5×5, ставка 100, пять мин\n"
    "• /dice 100 чёт — кости, выплата ×1,96\n"
    "• /basket 100 попадёт — бросок в кольцо, попадёт или промах\n"
    "• /spin — колесо дня раз в 12 часов\n"
    "• /bonus — часовой и ежедневный бонусы\n"
    "• /deposit — вклады под процент\n"
    "• /pay 100 @ник — перевод другому игроку\n"
    "• /promo КОД — активировать промокод\n\n"
    "На старте — 1000 mCoin. За друга, сыгравшего 5 партий, — 500 mCoin.\n"
    "Валюта mCoin виртуальная: реальные деньги не принимаются и не выводятся."
)


def app_url() -> str:
    return f"{config.public_url}/" if config.public_url else "https://example.com/"


def num(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def pct(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def left_text(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{secs} сек"


def date_text(timestamp: int) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(timestamp))


def webapp_button(text: str = "🎮 Открыть игру") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=app_url()))


def chat_button() -> InlineKeyboardButton | None:
    if not config.chat_url:
        return None
    return InlineKeyboardButton(text="💬 Чат игроков", url=config.chat_url)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button()],
        [InlineKeyboardButton(text="💣 Сапёр в чате", callback_data="menu:mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="menu:dice")],
        [InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonus"),
         InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:balance"),
         InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:ach")],
        [InlineKeyboardButton(text="🎁 Награды за уровень", callback_data="level:menu"),
         InlineKeyboardButton(text="🎯 Задания", callback_data="menu:tasks")],
        [InlineKeyboardButton(text="🏆 Топы", callback_data="top:menu"),
         InlineKeyboardButton(text="🎰 Игры", callback_data="menu:games")],
        [InlineKeyboardButton(text="⚔️ Дуэли", callback_data="menu:duel"),
         InlineKeyboardButton(text="🔐 Честность", callback_data="fair")],
    ] + ([[chat_button()]] if chat_button() else []))


def play_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button()],
        [InlineKeyboardButton(text="💣 Сапёр в чате", callback_data="menu:mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="menu:dice")],
        [InlineKeyboardButton(text="🎰 Игры", callback_data="menu:games"),
         InlineKeyboardButton(text="⚔️ Дуэли", callback_data="menu:duel")],
        [InlineKeyboardButton(text="🏆 Топ игроков", callback_data="top"),
         InlineKeyboardButton(text="🔐 Честность игры", callback_data="fair")],
    ])


def dice_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for bet in DICE_BETS:
        rows.append([
            InlineKeyboardButton(text=f"{num(bet)} на чёт", callback_data=f"d:{bet}:e"),
            InlineKeyboardButton(text=f"{num(bet)} на нечёт", callback_data=f"d:{bet}:o"),
        ])
    rows.append([webapp_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def finished_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Новая партия", callback_data="menu:mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="menu:dice")],
        [webapp_button()],
    ])


async def safe_edit(message: Message, text: str,
                    keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        await message.answer(text, reply_markup=keyboard)
    except Exception:
        await message.answer(text, reply_markup=keyboard)


def build_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher()

    def get_user(source) -> dict:
        return db.ensure_user(source.from_user.id, source.from_user.username,
                              source.from_user.first_name)

    def is_admin(user: dict) -> bool:
        if user["user_id"] in config.admin_ids:
            return True
        name = (user.get("username") or "").lower()
        if name and name in config.admin_usernames:
            return True
        return (user.get("role") or "user") in ("admin", "moderator")

    ROLE_RANK = {"user": 0, "moderator": 1, "admin": 2}

    def is_owner(user: dict) -> bool:
        if user["user_id"] in config.admin_ids:
            return True
        name = (user.get("username") or "").lower()
        return bool(name) and name in config.admin_usernames

    def role_of(user: dict) -> str:
        if is_owner(user):
            return "admin"
        role = (user.get("role") or "user").lower()
        return role if role in ROLE_RANK else "user"

    def rank(user: dict) -> int:
        return ROLE_RANK[role_of(user)]

    def can(user: dict, needed: str) -> bool:
        return rank(user) >= ROLE_RANK.get(needed, 2)

    def roles_text() -> str:
        return ("👥 <b>Роли и права</b>\n\n"
                "<b>Игрок</b>\n"
                "• игры в чате и приложении, бонусы, задания\n"
                "• переводы, промокоды, топ, история, честность\n\n"
                "<b>Модератор</b>\n"
                "• всё как у игрока\n"
                "• /stats — статистика бота\n"
                "• /player ID — карточка игрока\n"
                "• /ban и /unban — блокировка и разблокировка\n"
                "• /logs — журнал действий\n\n"
                "<b>Админ</b>\n"
                "• всё как у модератора\n"
                "• /setbal и /addbal — баланс игрока\n"
                "• /give — выдача предметов\n"
                "• /role — назначение ролей (admin — только владелец)\n"
                "• /promo_new, /promo_list, /promo_off, /promo_post\n"
                "• /maint on|off и /game имя on|off\n"
                "• /broadcast — рассылка игрокам\n\n"
                "<b>Владелец</b> (ID из ADMIN_IDS)\n"
                "• полный доступ и назначение админов\n\n"
                "Команды работают и в группах — просто добавьте бота в чат.")

    def find_user(raw: str) -> dict | None:
        raw = (raw or "").strip()
        if raw.startswith("@"):
            return db.user_by_username(raw)
        if raw.lstrip("-").isdigit():
            return db.user(int(raw))
        return db.user_by_username(raw)

    def player_card(target: dict) -> str:
        name = target.get("first_name") or "Игрок"
        username = f"@{target['username']}" if target.get("username") else "—"
        banned = "заблокирован" if target.get("is_banned") else "активен"
        return (f"👤 <b>{name}</b>\n"
                f"ID: <code>{target['user_id']}</code>\n"
                f"username: {username}\n"
                f"Роль: <b>{role_of(target)}</b> · {banned}\n"
                f"Баланс: {num(int(target['balance']))} mCoin\n"
                f"Партий: {num(int(target['games_played']))} · "
                f"побед: {num(int(target['games_won']))}\n"
                f"Оборот: {num(int(target['total_wagered']))} mCoin")

    def bet_error(user: dict, bet: int, game_key: str | None = None) -> str | None:
        if user.get("is_banned"):
            return "Аккаунт заблокирован."
        settings = db.settings()
        if game_key and int(settings.get("game_" + game_key, 1)) != 1:
            return "Эта игра временно отключена."
        if int(settings.get("maintenance", 0)) and not is_admin(user):
            return "Идут технические работы — игра скоро вернётся."
        min_bet = int(settings.get("min_bet", game.MIN_BET))
        max_bet = int(settings.get("max_bet", game.MAX_BET))
        if not (min_bet <= bet <= max_bet):
            return f"Ставка от {num(min_bet)} до {num(max_bet)} mCoin."
        if int(user["balance"]) < bet:
            return "Недостаточно mCoin. Забери бонус: /bonus"
        return None

    def charm_bonus(user: dict, payout: int) -> int:
        if payout <= 0:
            return payout
        if not db.take_item(user["user_id"], "charm"):
            return payout
        extra = int(payout * game.CHARM_BONUS)
        if extra <= 0:
            return payout
        return payout + extra

    def apply_relic(user: dict, key: str, payout: int) -> int:
        if payout <= 0:
            return payout
        relic = game.GAME_RELICS.get(key)
        if not relic or db.item_qty(user["user_id"], relic) <= 0:
            return payout
        bonus = int(payout * game.RELIC_BONUS)
        if bonus <= 0:
            return payout
        return payout + bonus

    def gold_pick_bonus(user: dict, payout: int) -> int:
        if payout <= 0:
            return payout
        if db.item_qty(user["user_id"], "gold_pick") <= 0:
            return payout
        bonus = int(payout * game.GOLD_PICK_BONUS)
        if bonus <= 0:
            return payout
        return payout + bonus

    def insurance_refund(user: dict, bet: int) -> int:
        if not db.take_item(user["user_id"], "insurance"):
            return 0
        refund = min(int(bet * game.INSURANCE_REFUND), game.INSURANCE_CAP)
        if refund > 0:
            db.add_balance(user["user_id"], refund)
        return refund

    def finish_game(user: dict, bet: int, payout: int, mult: float):
        xp_gain = game.XP_PER_GAME + (game.XP_PER_WIN if payout > 0 else 0)
        before = game.level_from_xp(int(user.get("xp") or 0))
        db.finish_stats(user["user_id"], bet, payout, mult)
        db.add_xp(user["user_id"], xp_gain)
        earned = awards.evaluate(db, user["user_id"])
        db.claim_referral_bonus(user["user_id"])
        after = game.level_from_xp(int(db.user(user["user_id"]).get("xp") or 0))
        return earned, xp_gain, before, after

    def xp_line(xp_gain: int, before: int, after: int) -> str:
        text = f"🎖 +{xp_gain} XP"
        if after > before:
            text += f" · ⬆️ уровень {after} — {game.level_title(after)}"
        return text

    def awards_lines(earned: list[dict]) -> list[str]:
        return [f"🏅 Достижение: {item['title']} (+{num(item['reward'])} mCoin)"
                for item in earned]

    def cashout_round(user: dict, rnd: dict, round_id: str, opened: list[int],
                      mult: float, auto: bool = False):
        payout = game.payout_for(rnd["bet"], mult)
        payout = charm_bonus(user, payout)
        payout = apply_relic(user, "mines", payout)
        payout = gold_pick_bonus(user, payout)
        db.update_round(round_id, opened, mult, "cashed", payout)
        db.add_balance(user["user_id"], payout)
        earned, xp_gain, level_before, level_after = finish_game(
            user, rnd["bet"], payout, mult)
        balance = db.user(user["user_id"])["balance"]
        title = "🤖 <b>Авто-кэшаут!</b>" if auto else "💰 <b>Забрал!</b>"
        lines = [title, "",
                 f"Множитель: ×{mult:.2f}",
                 f"Выплата: <b>+{num(payout)}</b> mCoin",
                 xp_line(xp_gain, level_before, level_after)]
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(balance)} mCoin")
        return "\n".join(lines), payout

    def referral_link(user_id: int) -> str:
        name = config.bot_username or "bot"
        return f"https://t.me/{name}?start=ref_{user_id}"

    def profile_text(user: dict) -> str:
        now = int(time.time())
        lost = max(0, int(user["total_wagered"]) - int(user["total_won"]))
        deposits_total = sum(int(row["amount"]) for row in db.deposits(user["user_id"]))
        level = game.level_view(user.get("xp") or 0)
        duels_played = int(user.get("duels_played") or 0)
        duels_won = int(user.get("duels_won") or 0)
        lines = [
            "👤 <b>Профиль</b>",
            f"💰 Баланс: <b>{num(user['balance'])} mCoin</b>",
            f"🎁 GMPOINT: <b>{num(user.get('gmpoint') or 0)}</b>",
            f"⭐ Уровень {level['level']} — {level['title']}",
            f"🎖 XP: {level['into']} / {level['need']}",
            f"🎯 Партий: {user['games_played']} · побед: {user['games_won']}",
            f"📉 Проиграно: {num(lost)} mCoin",
            f"🔥 Лучший множитель: ×{user['best_multiplier']:.2f}",
        ]
        if duels_played:
            lines.append(f"⚔️ Дуэли: {duels_played} · побед: {duels_won}")
        place = db.rank(user["user_id"])
        if place:
            lines.append(f"🏆 Место в топе: #{place}")
        if deposits_total:
            lines.append(f"🏦 В депозитах: {num(deposits_total)} mCoin")
        hourly_left = game.HOURLY_COOLDOWN - (now - int(user.get("last_hourly") or 0))
        spin_left = game.SPIN_COOLDOWN - (now - int(user.get("last_spin") or 0))
        lines.append("")
        lines.append("🎁 Часовой бонус: " + ("готов" if hourly_left <= 0
                                            else f"через {left_text(hourly_left)}"))
        lines.append("🎡 Колесо дня: " + ("готово" if spin_left <= 0
                                         else f"через {left_text(spin_left)}"))
        return "\n".join(lines)

    def achievements_text(user: dict) -> str:
        earned = awards.evaluate(db, user["user_id"])
        fresh = db.user(user["user_id"])
        claimed = db.user_achievements(user["user_id"])
        stats = awards.metrics(db, user["user_id"])
        level = game.level_view(fresh.get("xp") or 0)
        pending = level_pending(fresh)
        lines = ["🏅 <b>Достижения</b>",
                 f"⭐ Уровень {level['level']} — {level['title']}",
                 f"🎖 XP: {level['into']} / {level['need']}"]
        if pending:
            lines.append(f"🎁 Наград за уровни: {len(pending)} — забери в «Наградах»")
        lines.append("")
        for ach in game.ACHIEVEMENTS:
            progress = min(ach["target"], stats.get(ach["metric"], 0))
            if ach["key"] in claimed:
                mark = "✅"
            elif progress >= ach["target"]:
                mark = "🔓"
            else:
                mark = "▫️"
            lines.append(f"{mark} {ach['icon']} {ach['title']} — "
                         f"{progress}/{ach['target']} · +{num(ach['reward'])} mCoin")
        if earned:
            lines += ["", "Новые:"] + awards_lines(earned)
            lines.append(f"💰 Баланс: {num(fresh['balance'])} mCoin")
        return "\n".join(lines)

    def level_pending(user: dict) -> list[int]:
        level = game.level_view(user.get("xp") or 0)["level"]
        claimed = db.level_claims(user["user_id"])
        return [lvl for lvl in range(2, level + 1) if lvl not in claimed]

    def level_reward_line(reward: dict) -> str:
        parts = [f"+{num(reward['coins'])} mCoin"]
        if reward["gmpoint"]:
            parts.append(f"+{reward['gmpoint']} GMPOINT")
        if reward["lootbox"]:
            parts.append(f"+{reward['lootbox']} лутбокс")
        if reward["prefix"]:
            prefix = game.prefix_view(reward["prefix"])
            parts.append(f"префикс «{prefix['title']}»" if prefix else "префикс")
        return " · ".join(parts)

    def level_menu_text(user: dict) -> str:
        view = game.level_view(user.get("xp") or 0)
        pending = level_pending(user)
        lines = ["🎁 <b>Награды за уровень</b>",
                 f"⭐ Уровень {view['level']} — {view['title']}",
                 f"🎖 XP: {num(view['into'])} / {num(view['need'])}", ""]
        if pending:
            coins = sum(game.level_reward(lvl)["coins"] for lvl in pending)
            lines.append(f"Доступно наград: <b>{len(pending)}</b> "
                         f"(от {num(coins)} mCoin)")
            lines.append("")
            for lvl in pending[-6:]:
                lines.append(f"• {lvl} ур. — {level_reward_line(game.level_reward(lvl))}")
            if len(pending) > 6:
                lines.append(f"… и ещё {len(pending) - 6}")
        else:
            lines.append("Все награды за достигнутые уровни уже получены.")
        nxt = game.level_reward(view["level"] + 1)
        lines += ["",
                  f"Следующий, {view['level'] + 1} ур.: {level_reward_line(nxt)}",
                  f"Осталось набрать {num(max(0, view['next'] - view['xp']))} XP"]
        return "\n".join(lines)

    def level_menu_keyboard(user: dict) -> InlineKeyboardMarkup:
        rows = []
        if level_pending(user):
            rows.append([InlineKeyboardButton(text="🎁 Забрать награды",
                                              callback_data="level:claim")])
        rows.append([InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:ach"),
                     InlineKeyboardButton(text="🏆 Топ по уровню",
                                          callback_data="top:level")])
        rows.append([webapp_button()])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def claim_levels(user: dict) -> tuple[list[dict], int]:
        level = game.level_view(user.get("xp") or 0)["level"]
        claimed = db.level_claims(user["user_id"])
        got: list[dict] = []
        coins = 0
        for lvl in range(2, level + 1):
            if lvl in claimed:
                continue
            reward = game.level_reward(lvl)
            if db.claim_level(user["user_id"], lvl, reward["coins"],
                              reward["gmpoint"], reward["lootbox"],
                              reward["prefix"]):
                got.append(reward)
                coins += reward["coins"]
        return got, coins

    def user_name(user: dict | None) -> str:
        if not user:
            return "игрок"
        if user.get("username"):
            return "@" + str(user["username"]).lstrip("@")
        return user.get("first_name") or f"id{user['user_id']}"

    def duel_top_text() -> str:
        rows = db.top_duelists(10)
        lines = ["🏆 <b>Топ дуэлянтов</b>", ""]
        medals = ("🥇", "🥈", "🥉")
        for index, row in enumerate(rows, 1):
            prefix = medals[index - 1] if index <= 3 else f"{index}."
            lines.append(f"{prefix} {user_name(row)} — {row['duels_won']} побед "
                         f"из {row['duels_played']}")
        if not rows:
            lines.append("Пока никто не играл дуэли.")
        return "\n".join(lines)

    def duel_menu_text(user: dict) -> str:
        pending = db.pending_duel_for(user["user_id"])
        lines = ["⚔️ <b>Дуэли 1×1</b>", "",
                 "Вызови друга: <code>/duel 100 @username</code>",
                 f"Победитель забирает {num(game.duel_prize(100))} mCoin "
                 "со ставки 100 (комиссия 5%).", ""]
        if pending:
            other_id = (pending["opponent_id"]
                        if int(pending["challenger_id"]) == int(user["user_id"])
                        else pending["challenger_id"])
            other = db.user(other_id)
            role = ("твой вызов" if int(pending["challenger_id"]) == int(user["user_id"])
                    else "тебя вызвали")
            lines.append(f"⏳ Активный вызов: {user_name(other)} · "
                         f"{num(pending['bet'])} mCoin ({role})")
        else:
            lines.append("Активных вызовов нет.")
        lines += ["", f"Пар: {user['duels_played']} · побед: {user['duels_won']}"]
        top = db.top_duelists(3)
        if top:
            lines += ["", "<b>Топ дуэлянтов</b>"]
            for index, row in enumerate(top, 1):
                lines.append(f"{index}. {user_name(row)} — {row['duels_won']} побед "
                             f"из {row['duels_played']}")
        return "\n".join(lines)

    def duel_menu_keyboard(user: dict) -> InlineKeyboardMarkup:
        rows = []
        pending = db.pending_duel_for(user["user_id"])
        if pending and int(pending["opponent_id"]) == int(user["user_id"]):
            rows.append([
                InlineKeyboardButton(text="⚔️ Принять",
                                     callback_data=f"duel:accept:{pending['id']}"),
                InlineKeyboardButton(text="❌ Отклонить",
                                     callback_data=f"duel:decline:{pending['id']}"),
            ])
        rows.append([InlineKeyboardButton(text="🏆 Топ дуэлянтов",
                                          callback_data="duel:top")])
        rows.append([webapp_button()])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def duel_result_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Ещё дуэль", callback_data="menu:duel")],
            [webapp_button()],
        ])

    def resolve_duel(duel: dict, challenger: dict, opponent: dict):
        bet = int(duel["bet"])
        prize = game.duel_prize(bet)
        c_roll = game.duel_roll(challenger["server_seed"], challenger["client_seed"],
                               db.bump_nonce(challenger["user_id"]))
        o_roll = game.duel_roll(opponent["server_seed"], opponent["client_seed"],
                               db.bump_nonce(opponent["user_id"]))
        if c_roll == o_roll:
            winner_id = None
        elif c_roll > o_roll:
            winner_id = challenger["user_id"]
        else:
            winner_id = opponent["user_id"]
        now = int(time.time())
        if not db.finish_duel(duel["id"], c_roll, o_roll, winner_id,
                              2 * bet - prize, now):
            return None
        if winner_id is None:
            db.add_balance(challenger["user_id"], bet)
            db.add_balance(opponent["user_id"], bet)
            db.add_duel_stats(challenger["user_id"], False)
            db.add_duel_stats(opponent["user_id"], False)
            db.add_xp(challenger["user_id"], game.XP_PER_GAME)
            db.add_xp(opponent["user_id"], game.XP_PER_GAME)
        else:
            winner = challenger if int(winner_id) == int(challenger["user_id"]) else opponent
            loser = opponent if int(winner_id) == int(challenger["user_id"]) else challenger
            db.add_balance(winner_id, prize)
            db.add_duel_stats(winner_id, True)
            db.add_duel_stats(loser["user_id"], False)
            db.add_xp(winner_id, game.XP_PER_GAME + game.XP_PER_DUEL_WIN)
            db.add_xp(loser["user_id"], game.XP_PER_GAME)
        awards.evaluate(db, challenger["user_id"])
        awards.evaluate(db, opponent["user_id"])
        return {"c_roll": c_roll, "o_roll": o_roll, "winner_id": winner_id,
                "prize": prize, "bet": bet}

    def duel_play_text(duel: dict, viewer: dict, result: dict) -> str:
        challenger = db.user(duel["challenger_id"])
        opponent = db.user(duel["opponent_id"])
        lines = ["⚔️ <b>Дуэль завершена</b>", "",
                 f"{user_name(challenger)}: <b>{result['c_roll']}</b>",
                 f"{user_name(opponent)}: <b>{result['o_roll']}</b>", ""]
        if result["winner_id"] is None:
            lines.append("🤝 Ничья — ставки возвращены.")
        elif int(result["winner_id"]) == int(viewer["user_id"]):
            lines.append(f"🏆 Победа! +{num(result['prize'])} mCoin")
        else:
            lines.append(f"❌ Поражение. −{num(result['bet'])} mCoin")
        fresh = db.user(viewer["user_id"])
        lines.append(f"💰 Баланс: {num(fresh['balance'])} mCoin")
        return "\n".join(lines)

    def profile_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonus"),
             InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
            [InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:ach"),
             InlineKeyboardButton(text="🎯 Задания", callback_data="menu:tasks")],
            [InlineKeyboardButton(text="🏆 Топ по балансу", callback_data="top"),
             InlineKeyboardButton(text="⭐ Топ по уровню", callback_data="top:level")],
            [webapp_button()],
        ])

    def top_text() -> str:
        rows = db.leaderboard(10)
        lines = ["🏆 <b>Топ по балансу</b>", ""]
        medals = ("🥇", "🥈", "🥉")
        for index, row in enumerate(rows, 1):
            name = row["username"] or row["first_name"] or f"id{row['user_id']}"
            prefix = medals[index - 1] if index <= 3 else f"{index}."
            lines.append(f"{prefix} {name} — {num(row['balance'])} mCoin")
        if not rows:
            lines.append("Пока пусто")
        return "\n".join(lines)

    def top_level_text() -> str:
        rows = db.top_by_level(10)
        lines = ["⭐ <b>Топ по уровню</b>", ""]
        medals = ("🥇", "🥈", "🥉")
        for index, row in enumerate(rows, 1):
            name = row["username"] or row["first_name"] or f"id{row['user_id']}"
            level = game.level_view(row.get("xp") or 0)
            prefix = game.prefix_view(row.get("prefix"))
            mark = f" {prefix['title']}" if prefix else ""
            place = medals[index - 1] if index <= 3 else f"{index}."
            lines.append(
                f"{place} {name}{mark} — {level['level']} ур. "
                f"({level['title']}) · {num(level['xp'])} XP")
        if not rows:
            lines.append("Пока пусто")
        return "\n".join(lines)

    def admin_players_text(data: dict) -> str:
        lines = [
            "👥 <b>Игроки</b>",
            f"Всего: <b>{num(data['total'])}</b> · "
            f"страница {data['page']} из {data['pages']}",
            "",
        ]
        if not data["items"]:
            lines.append("Пока нет игроков.")
            return "\n".join(lines)
        start = (data["page"] - 1) * data["per_page"]
        for index, row in enumerate(data["items"], start + 1):
            level = game.level_view(row.get("xp") or 0)
            name = row["first_name"] or "без имени"
            nick = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
            prefix = game.prefix_view(row.get("prefix"))
            marks = []
            if row.get("is_banned"):
                marks.append("🚫 бан")
            if (row.get("role") or "user") != "user":
                marks.append(f"🛠 {row['role']}")
            played = (date_text(int(row["last_played"]))
                      if row.get("last_played") else "ещё не играл")
            head = f"{index}. <b>{name}</b> · {nick}"
            if prefix:
                head += f" · {prefix['title']}"
            if marks:
                head += f" · {' · '.join(marks)}"
            lines.append(
                f"{head}\n"
                f"   💰 {num(row['balance'])} mCoin · ⭐ {level['level']} ур. "
                f"({level['title']})\n"
                f"   🎮 партий: {row['games_played']} · побед: {row['games_won']}\n"
                f"   🕒 {played}"
            )
        return "\n".join(lines)

    def admin_players_keyboard(data: dict) -> InlineKeyboardMarkup:
        page = int(data["page"])
        pages = int(data["pages"])
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton(text="◀️ Назад",
                                            callback_data=f"adm:pl:{page - 1}"))
        if page < pages:
            nav.append(InlineKeyboardButton(text="Вперёд ▶️",
                                            callback_data=f"adm:pl:{page + 1}"))
        rows = []
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton(text="🔄 Обновить",
                                          callback_data=f"adm:pl:{page}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def bank_text(user: dict) -> str:
        lines = [
            "🏦 <b>ДЕПОЗИТ БАНК</b>",
            f"Баланс: <b>{num(user['balance'])} mCoin</b>",
            "",
            "💵 <b>Временные депозиты</b>",
        ]
        for plan in game.DEPOSIT_PLANS:
            percent = plan["rate_bps"] / 100
            per_day = percent / plan["days"]
            lines.append(f"├ {plan['days']} дн. — <b>{pct(percent)}%</b> "
                         f"({pct(per_day)}% в день)")
        lines += [
            "",
            "🪙 <b>Накопительный счёт</b>",
            f"└ {pct(game.SAVINGS_RATE_BPS / 100)}% в день, снять можно в любой момент",
            "",
            f"Минимальный вклад — {num(game.DEPOSIT_MIN)} mCoin. "
            "Проценты начисляются при закрытии.",
        ]
        return "\n".join(lines)

    def bank_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💵 Временные депозиты", callback_data="dep:fixed")],
            [InlineKeyboardButton(text="🪙 Накопительный счёт", callback_data="dep:savings")],
            [InlineKeyboardButton(text="📖 Мои депозиты", callback_data="dep:mine")],
            [webapp_button()],
        ])

    def fixed_text() -> str:
        lines = ["💵 <b>Временные депозиты</b>", "",
                 "Процент фиксируется в момент вклада:", ""]
        for plan in game.DEPOSIT_PLANS:
            percent = plan["rate_bps"] / 100
            lines.append(f"• {plan['days']} дн. — <b>{pct(percent)}%</b>")
        lines += ["", "Выбери срок 👇"]
        return "\n".join(lines)

    def fixed_keyboard() -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(
            text=f"{plan['days']} дн. — {pct(plan['rate_bps'] / 100)}%",
            callback_data=f"depf:{plan['days']}")] for plan in game.DEPOSIT_PLANS]
        rows.append([InlineKeyboardButton(text="⬅️ В банк", callback_data="dep:main")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def deposit_amounts_text(days: int) -> str:
        plan = next((item for item in game.DEPOSIT_PLANS if item["days"] == days), None)
        if not plan:
            return "Неизвестный срок."
        return (f"💵 <b>Депозит на {days} дн.</b>\n\n"
                f"Ставка: <b>{pct(plan['rate_bps'] / 100)}%</b> за весь срок\n"
                f"Сумма: от {num(game.DEPOSIT_MIN)} до {num(game.DEPOSIT_MAX)} mCoin\n\n"
                "Выбери сумму 👇")

    def deposit_amounts_keyboard(days: int) -> InlineKeyboardMarkup:
        rows = []
        for start in range(0, len(DEPOSIT_AMOUNTS), 3):
            rows.append([
                InlineKeyboardButton(text=num(value), callback_data=f"depa:{days}:{value}")
                for value in DEPOSIT_AMOUNTS[start:start + 3]
            ])
        rows.append([InlineKeyboardButton(text="⬅️ Другой срок", callback_data="dep:fixed")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def savings_text(user: dict) -> str:
        now = int(time.time())
        savings = db.savings(user["user_id"])
        if not savings:
            return ("🪙 <b>Накопительный счёт</b>\n\n"
                    "Счёт ещё не открыт.\n"
                    f"Ставка — {pct(game.SAVINGS_RATE_BPS / 100)}% в день, "
                    "снять можно в любой момент.")
        accrued = game.savings_interest(savings["amount"], savings["rate_bps"],
                                        now - int(savings["started_at"]))
        return ("🪙 <b>Накопительный счёт</b>\n\n"
                f"На счёте: <b>{num(savings['amount'])} mCoin</b>\n"
                f"Накоплено: +{num(accrued)} mCoin\n"
                f"Ставка: {pct(savings['rate_bps'] / 100)}% в день\n\n"
                "Пополнить или забрать можно в любой момент.")

    def savings_keyboard(user: dict) -> InlineKeyboardMarkup:
        rows = []
        for start in range(0, len(SAVINGS_AMOUNTS), 2):
            rows.append([
                InlineKeyboardButton(text=f"+{num(value)}", callback_data=f"savp:{value}")
                for value in SAVINGS_AMOUNTS[start:start + 2]
            ])
        if db.savings(user["user_id"]):
            rows.append([InlineKeyboardButton(text="💰 Забрать всё", callback_data="savw")])
        rows.append([InlineKeyboardButton(text="⬅️ В банк", callback_data="dep:main")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def deposits_text(user: dict) -> tuple[str, InlineKeyboardMarkup]:
        now = int(time.time())
        rows_all = db.deposits(user["user_id"])
        fixed = [row for row in rows_all if row["kind"] == "fixed"]
        savings = next((row for row in rows_all if row["kind"] == "savings"), None)
        lines = ["📖 <b>Мои депозиты</b>", ""]
        rows: list[list[InlineKeyboardButton]] = []
        if not fixed and not savings:
            lines.append("Пока пусто. Открой вклад в разделе «Временные депозиты».")
        for row in fixed:
            interest = game.deposit_interest(row["amount"], row["rate_bps"])
            total = int(row["amount"]) + interest
            ends = int(row["ends_at"] or 0)
            if now >= ends:
                lines.append(f"✅ {num(row['amount'])} mCoin — готов к закрытию, "
                             f"к выплате {num(total)}")
                rows.append([InlineKeyboardButton(
                    text=f"✅ Забрать {num(total)}", callback_data=f"depc:{row['id']}")])
            else:
                lines.append(f"🔒 {num(row['amount'])} mCoin → {num(total)} "
                             f"к {date_text(ends)} (+{num(interest)})")
                rows.append([InlineKeyboardButton(
                    text=f"⏳ Ещё {left_text(ends - now)}",
                    callback_data=f"depw:{row['id']}")])
        if savings:
            interest = game.savings_interest(savings["amount"], savings["rate_bps"],
                                             now - int(savings["started_at"]))
            lines.append(f"🪙 Накопительный счёт: {num(savings['amount'])} (+{num(interest)})")
            rows.append([InlineKeyboardButton(text="💰 Забрать со счёта",
                                              callback_data="savw")])
        rows.append([InlineKeyboardButton(text="⬅️ В банк", callback_data="dep:main")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)

    def mines_hint_text() -> str:
        settings = db.settings()
        return ("💣 <b>Сапёр в чате</b>\n\n"
                "Напиши: <code>/mines 100 5</code>\n"
                "где 100 — ставка, 5 — число мин.\n"
                "Авто-кэшаут: <code>/mines 100 5 2</code> — забрать на ×2.\n\n"
                f"Ставка: от {num(settings.get('min_bet', game.MIN_BET))} "
                f"до {num(settings.get('max_bet', game.MAX_BET))} mCoin\n"
                f"Мин: от {settings.get('min_mines', 1)} "
                f"до {settings.get('max_mines', 24)}\n\n"
                "Открывай клетки кнопками — множитель растёт. "
                "В любой момент нажми «Забрать».")

    def mines_hint_keyboard() -> InlineKeyboardMarkup:
        settings = db.settings()
        min_bet = int(settings.get("min_bet", game.MIN_BET))
        max_bet = int(settings.get("max_bet", game.MAX_BET))
        base = max(100, min_bet)
        bigger = min(base * 5, max_bet)
        rows = [
            [InlineKeyboardButton(text=f"{num(base)} · 5 мин", callback_data=f"ms:{base}:5"),
             InlineKeyboardButton(text=f"{num(bigger)} · 5 мин",
                                  callback_data=f"ms:{bigger}:5")],
            [InlineKeyboardButton(text=f"{num(base)} · 10 мин", callback_data=f"ms:{base}:10"),
             InlineKeyboardButton(text=f"{num(bigger)} · 3 мин",
                                  callback_data=f"ms:{bigger}:3")],
            [InlineKeyboardButton(text=f"{num(base)} · 5 мин · авто ×2",
                                  callback_data=f"ms:{base}:5:2")],
            [webapp_button("🎮 Полное поле в приложении")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def start_mines(user: dict, bet: int, mines: int, target: float = 0):
        error = bet_error(user, bet, "mines")
        if error:
            return error, None
        settings = db.settings()
        min_mines = int(settings.get("min_mines", 1))
        max_mines = int(settings.get("max_mines", 24))
        if not (min_mines <= mines <= max_mines):
            return f"Число мин от {min_mines} до {max_mines}.", None
        if target:
            top = game.max_multiplier(mines)
            if not (1.05 <= target <= top):
                return (f"Авто-кэшаут от ×1,05 до ×{top:.2f} "
                        f"для {mines} мин."), None
        if db.active_round(user["user_id"]):
            return "Сначала заверши текущую партию — нажми «Забрать» в её сообщении.", None
        nonce = db.bump_nonce(user["user_id"])
        positions = game.generate_mines(user["server_seed"], user["client_seed"],
                                        nonce, mines)
        round_id = uuid.uuid4().hex[:12]
        db.add_balance(user["user_id"], -bet)
        db.create_round(round_id, user["user_id"], bet, mines, positions,
                        user["server_seed"], user["client_seed"], nonce,
                        float(target or 0))
        return None, db.round(round_id)

    def mines_text(rnd: dict) -> str:
        opened = list(rnd["opened"])
        safe = game.CELLS - int(rnd["mines"])
        mult = float(rnd["multiplier"])
        lines = [
            f"💣 <b>Сапёр</b> · мин: {rnd['mines']}",
            f"Ставка: {num(rnd['bet'])} mCoin",
            f"Открыто: {len(opened)} из {safe}",
            f"Множитель: ×{mult:.2f}",
        ]
        if opened:
            payout = game.payout_for(rnd["bet"], mult)
            lines.append(f"К выплате: <b>{num(payout)}</b> mCoin")
        else:
            lines.append("К выплате: открой хотя бы одну клетку")
        target = float(rnd.get("auto_target") or 0)
        if target:
            lines.append(f"🤖 Авто-кэшаут: ×{target:.2f}")
        chance = game.next_chance(int(rnd["mines"]), len(opened)) * 100
        lines += ["", f"Шанс следующей клетки: {chance:.1f}%",
                  "Нажми клетку, потом «Забрать»."]
        return "\n".join(lines)

    def mines_keyboard(rnd: dict) -> InlineKeyboardMarkup:
        opened = set(rnd["opened"])
        rows = []
        for row in range(game.SIDE):
            buttons = []
            for col in range(game.SIDE):
                cell = row * game.SIDE + col
                label = CELL_OPEN if cell in opened else CELL_CLOSED
                buttons.append(InlineKeyboardButton(
                    text=label, callback_data=f"m:{rnd['id']}:{cell}"))
            rows.append(buttons)
        if opened:
            payout = game.payout_for(rnd["bet"], float(rnd["multiplier"]))
            rows.append([InlineKeyboardButton(
                text=f"💰 Забрать {num(payout)}", callback_data=f"c:{rnd['id']}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def mines_lost_text(rnd: dict, cell: int, refund: int, balance: int) -> str:
        mines = ", ".join(str(pos + 1) for pos in sorted(rnd["mine_positions"]))
        lines = ["💥 <b>Мина!</b>",
                 f"Клетка {cell + 1} оказалась миной.",
                 f"Ставка {num(rnd['bet'])} mCoin потеряна."]
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin.")
        lines += ["", f"Открыто клеток: {len(rnd['opened'])} · "
                       f"множитель дошёл до ×{float(rnd['multiplier']):.2f}",
                  f"Мины были на клетках: {mines}",
                  f"💰 Баланс: {num(balance)} mCoin"]
        return "\n".join(lines)

    def play_dice(user: dict, bet: int, pick: str) -> str:
        error = bet_error(user, bet, "dice")
        if error:
            return "⚠️ " + error
        nonce = db.bump_nonce(user["user_id"])
        roll = game.roll_dice(user["server_seed"], user["client_seed"], nonce)
        is_even = roll % 2 == 0
        win = is_even if pick == "even" else not is_even
        multiplier = game.DICE_MULTIPLIER if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "dice", payout)
        else:
            refund = insurance_refund(user, bet)
        db.add_balance(user["user_id"], payout - bet)
        db.add_play(uuid.uuid4().hex[:16], user["user_id"], "dice", bet, win, payout,
                    {"roll": roll, "pick": pick, "nonce": nonce, "chat": True})
        earned, xp_gain, level_before, level_after = finish_game(
            user, bet, payout, multiplier or 1.0)
        balance = db.user(user["user_id"])["balance"]
        pick_title = "чёт" if pick == "even" else "нечёт"
        lines = [f"🎲 Выпало: <b>{roll}</b> ({'чёт' if is_even else 'нечёт'})",
                 f"Ставка: {num(bet)} mCoin на {pick_title}"]
        if win:
            lines.append(f"✅ Выигрыш: <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Мимо")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, level_before, level_after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: <b>{num(balance)}</b> mCoin")
        return "\n".join(lines)

    def dice_hint_text() -> str:
        settings = db.settings()
        return ("🎲 <b>Кости</b>\n\n"
                "Напиши: <code>/dice 100 чёт</code>\n"
                "Выплата — ×1,96 при победе.\n\n"
                f"Ставка: от {num(settings.get('min_bet', game.MIN_BET))} "
                f"до {num(settings.get('max_bet', game.MAX_BET))} mCoin.\n\n"
                "Можно и кнопкой 👇")

    def settle_play(user: dict, game_name: str, bet: int, payout: int,
                    mult: float, detail: dict):
        db.add_balance(user["user_id"], payout - bet)
        db.add_play(uuid.uuid4().hex[:16], user["user_id"], game_name, bet,
                    payout > 0, payout, detail)
        return finish_game(user, bet, payout, mult)

    def games_hint_text() -> str:
        return ("🎰 <b>Игры в чате</b>\n\n"
                "/roulette 100 красное — рулетка (×2, зеро ×36)\n"
                "/slots 100 — слоты (пара ×1,2, тройка до ×200)\n"
                "/crash 100 2.5 — краш, цель от ×1,20 до ×10\n"
                "/coin 100 орёл — монета, выплата ×1,96\n"
                "/basket 100 — бросок в кольцо, выплата ×2,4\n\n"
                "Результат считается из твоего seed — проверить можно /fair.")

    def games_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="menu:roulette"),
             InlineKeyboardButton(text="🎰 Слоты", callback_data="menu:slots")],
            [InlineKeyboardButton(text="💥 Краш", callback_data="menu:crash"),
             InlineKeyboardButton(text="🪙 Орёл и решка", callback_data="menu:coin")],
            [InlineKeyboardButton(text="🏀 Баскет", callback_data="menu:basket")],
            [webapp_button()],
        ])

    def roulette_hint_text() -> str:
        return ("🎡 <b>Рулетка</b>\n\n"
                "Напиши: <code>/roulette 100 красное</code>\n"
                "Красное или чёрное — ×2, зеро — ×36.\n\n"
                "Быстрый старт:")

    def roulette_hint_keyboard() -> InlineKeyboardMarkup:
        rows = []
        for bet in (100, 500):
            rows.append([
                InlineKeyboardButton(text=f"{num(bet)} красное",
                                     callback_data=f"rl:{bet}:red"),
                InlineKeyboardButton(text=f"{num(bet)} чёрное",
                                     callback_data=f"rl:{bet}:black"),
                InlineKeyboardButton(text="зеро",
                                     callback_data=f"rl:{bet}:green"),
            ])
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def slots_hint_text() -> str:
        return ("🎰 <b>Слоты</b>\n\n"
                "Напиши: <code>/slots 100</code>\n"
                "Пара символов — ×1,2, три одинаковых — от ×4 до ×200.\n\n"
                "Быстрый старт:")

    def slots_hint_keyboard() -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text=num(bet), callback_data=f"sl:{bet}")
                 for bet in (100, 500, 1000)]]
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def crash_hint_text() -> str:
        return ("💥 <b>Краш</b>\n\n"
                "Напиши: <code>/crash 100 2.5</code>\n"
                "Ставка и цель от ×1,20 до ×10,00.\n"
                "Если точка краша не ниже цели — забираешь ставку × цель.\n\n"
                "Быстрый старт:")

    def crash_hint_keyboard() -> InlineKeyboardMarkup:
        rows = [[
            InlineKeyboardButton(text="×1,5", callback_data="cr:100:1.5"),
            InlineKeyboardButton(text="×2", callback_data="cr:100:2"),
            InlineKeyboardButton(text="×3", callback_data="cr:100:3"),
        ]]
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def play_roulette(user: dict, bet: int, pick: str) -> str:
        error = bet_error(user, bet, "roulette")
        if error:
            return "⚠️ " + error
        nonce = db.bump_nonce(user["user_id"])
        number = game.roulette_number(user["server_seed"], user["client_seed"], nonce)
        multiplier = game.roulette_multiplier(number, pick)
        payout = int(math.floor(bet * multiplier)) if multiplier > 0 else 0
        refund = 0
        if payout > 0:
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "roulette", payout)
        else:
            refund = insurance_refund(user, bet)
        earned, xp_gain, before, after = settle_play(
            user, "roulette", bet, payout, multiplier or 1.0,
            {"number": number, "pick": pick, "nonce": nonce, "chat": True})
        color = ("зелёное" if number == 0
                 else "красное" if number in game.ROULETTE_RED else "чёрное")
        pick_title = {"red": "красное", "black": "чёрное", "green": "зеро"}[pick]
        lines = ["🎡 <b>Рулетка</b>", "",
                 f"Выпало: <b>{number}</b> ({color})",
                 f"Ставка: {num(bet)} mCoin на {pick_title}"]
        if payout > 0:
            lines.append(f"✅ Выигрыш: <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Мимо")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, before, after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(db.user(user['user_id'])['balance'])} mCoin")
        return "\n".join(lines)

    def play_slots(user: dict, bet: int) -> str:
        error = bet_error(user, bet, "slots")
        if error:
            return "⚠️ " + error
        nonce = db.bump_nonce(user["user_id"])
        reels, multiplier = game.spin_slots(user["server_seed"],
                                            user["client_seed"], nonce)
        payout = int(math.floor(bet * multiplier)) if multiplier > 0 else 0
        refund = 0
        if payout > 0:
            payout = charm_bonus(user, payout)
        else:
            refund = insurance_refund(user, bet)
        earned, xp_gain, before, after = settle_play(
            user, "slots", bet, payout, multiplier or 1.0,
            {"reels": [reel["key"] for reel in reels], "nonce": nonce, "chat": True})
        icons = " ".join(reel["icon"] for reel in reels)
        lines = ["🎰 <b>Слоты</b>", "", f"<b>{icons}</b>", ""]
        if payout > 0:
            lines.append(f"✅ ×{multiplier:.2f} — <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Нет совпадений")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, before, after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(db.user(user['user_id'])['balance'])} mCoin")
        return "\n".join(lines)

    def play_crash(user: dict, bet: int, target: float) -> str:
        error = bet_error(user, bet, "crash")
        if error:
            return "⚠️ " + error
        if not (game.CRASH_MIN <= target <= game.CRASH_MAX):
            return f"⚠️ Цель от ×{game.CRASH_MIN:.2f} до ×{game.CRASH_MAX:.2f}"
        target = round(float(target), 2)
        nonce = db.bump_nonce(user["user_id"])
        point = game.crash_point(user["server_seed"], user["client_seed"], nonce)
        win = point >= target
        payout = int(math.floor(bet * target)) if win else 0
        refund = 0
        if win:
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "crash", payout)
        else:
            refund = insurance_refund(user, bet)
        earned, xp_gain, before, after = settle_play(
            user, "crash", bet, payout, target if win else 0.0,
            {"point": point, "target": target, "nonce": nonce, "chat": True})
        lines = ["💥 <b>Краш</b>", "",
                 f"Точка: <b>×{point:.2f}</b>",
                 f"Твоя цель: ×{target:.2f}",
                 f"Ставка: {num(bet)} mCoin", ""]
        if win:
            lines.append(f"✅ Выигрыш: <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Краш раньше цели")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, before, after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(db.user(user['user_id'])['balance'])} mCoin")
        return "\n".join(lines)

    def coin_hint_text() -> str:
        return ("🪙 <b>Орёл и решка</b>\n\n"
                "Напиши: <code>/coin 100 орёл</code>\n"
                "Выплата ×1,96 при победе.\n\n"
                "Быстрый старт:")

    def coin_hint_keyboard() -> InlineKeyboardMarkup:
        rows = []
        for bet in (100, 500):
            rows.append([
                InlineKeyboardButton(text=f"{num(bet)} орёл",
                                     callback_data=f"cf:{bet}:heads"),
                InlineKeyboardButton(text=f"{num(bet)} решка",
                                     callback_data=f"cf:{bet}:tails"),
            ])
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def play_coin(user: dict, bet: int, pick: str) -> str:
        error = bet_error(user, bet, "coinflip")
        if error:
            return "⚠️ " + error
        nonce = db.bump_nonce(user["user_id"])
        side = game.coinflip(user["server_seed"], user["client_seed"], nonce)
        win = side == pick
        multiplier = game.COINFLIP_MULTIPLIER if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "coinflip", payout)
        else:
            refund = insurance_refund(user, bet)
        earned, xp_gain, before, after = settle_play(
            user, "coinflip", bet, payout, multiplier or 1.0,
            {"side": side, "pick": pick, "nonce": nonce, "chat": True})
        side_title = "орёл" if side == "heads" else "решка"
        pick_title = "орёл" if pick == "heads" else "решка"
        lines = ["🪙 <b>Орёл и решка</b>", "",
                 f"Выпало: <b>{side_title}</b>",
                 f"Ставка: {num(bet)} mCoin на {pick_title}"]
        if win:
            lines.append(f"✅ Выигрыш: <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Мимо")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, before, after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(db.user(user['user_id'])['balance'])} mCoin")
        return "\n".join(lines)

    def basket_hint_text() -> str:
        settings = db.settings()
        return ("🏀 <b>Баскет</b>\n\n"
                "Выбери, что будет: мяч попадёт или промахнётся.\n"
                "Напиши: <code>/basket 100 попадёт</code>\n"
                "или: <code>/basket 100 промах</code>\n\n"
                "Бот отправляет анимацию 🏀 из Telegram — она и решает.\n"
                "Попадание платит ×2,4 · промах ×1,6.\n\n"
                f"Ставка: от {num(settings.get('min_bet', game.MIN_BET))} "
                f"до {num(settings.get('max_bet', game.MAX_BET))} mCoin.\n\n"
                "Или просто жми кнопку 👇")

    def basket_hint_keyboard() -> InlineKeyboardMarkup:
        rows = []
        for bet in (100, 500):
            rows.append([
                InlineKeyboardButton(text=f"{num(bet)} · попадёт",
                                     callback_data=f"bs:{bet}:hit"),
                InlineKeyboardButton(text=f"{num(bet)} · промах",
                                     callback_data=f"bs:{bet}:miss"),
            ])
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="menu:games")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def play_basket(user: dict, bet: int, dice_value: int, pick: str = "hit") -> str:
        error = bet_error(user, bet, "basket")
        if error:
            return "⚠️ " + error
        scored = dice_value >= game.BASKET_SCORE_MIN
        win = (scored and pick == "hit") or (not scored and pick == "miss")
        multiplier = (game.BASKET_MULTIPLIER if scored
                      else game.BASKET_MISS_MULTIPLIER) if win else 0.0
        payout = int(math.floor(bet * multiplier)) if win else 0
        refund = 0
        if win:
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "basket", payout)
        else:
            refund = insurance_refund(user, bet)
        earned, xp_gain, level_before, level_after = settle_play(
            user, "basket", bet, payout, multiplier or 1.0,
            {"dice": dice_value, "scored": scored, "pick": pick, "chat": True})
        pick_title = "попадание" if pick == "hit" else "промах"
        lines = ["🏀 <b>Баскет</b>", "",
                 f"Бросок: <b>{dice_value}</b> из 5 — "
                 f"{'попал' if scored else 'мимо'}",
                 f"Ставка: {num(bet)} mCoin на {pick_title}"]
        if win:
            lines.append(f"✅ Угадал! Выигрыш: <b>+{num(payout)}</b> mCoin")
        else:
            lines.append("❌ Не угадал — ставка сгорела")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} mCoin")
        lines.append(xp_line(xp_gain, level_before, level_after))
        lines.extend(awards_lines(earned))
        lines.append(f"💰 Баланс: {num(db.user(user['user_id'])['balance'])} mCoin")
        return "\n".join(lines)

    def transfer_text(sender: dict, target_raw: str, amount: int) -> str:
        if amount < 1:
            return "⚠️ Сумма должна быть больше нуля"
        if amount > int(sender["balance"]):
            return "⚠️ Недостаточно средств"
        target = (target_raw or "").strip()
        recipient = None
        if target.startswith("@"):
            recipient = db.user_by_username(target)
        elif target.isdigit():
            recipient = db.user(int(target))
        else:
            recipient = db.user_by_username(target)
        if not recipient:
            return "⚠️ Игрок не найден. Укажи ID или @username"
        if int(recipient["user_id"]) == int(sender["user_id"]):
            return "⚠️ Нельзя перевести самому себе"
        if recipient.get("is_banned"):
            return "⚠️ Получатель заблокирован"
        db.make_transfer(uuid.uuid4().hex[:16], sender["user_id"],
                         int(recipient["user_id"]), amount)
        name = (recipient.get("username") or recipient.get("first_name")
                or str(recipient["user_id"]))
        balance = db.user(sender["user_id"])["balance"]
        return ("💸 <b>Перевод отправлен</b>\n\n"
                f"Кому: <b>{name}</b> · ID {recipient['user_id']}\n"
                f"Сумма: <b>{num(amount)}</b> mCoin\n"
                f"💰 Баланс: {num(balance)} mCoin")

    def promo_text(user: dict, code: str) -> str:
        code = code.strip().upper()
        promo = db.promo(code) or {}
        currency = str(promo.get("currency") or "mcoin")
        status, amount = db.claim_promo(code, user["user_id"],
                                        int(time.time()))
        errors = {
            "not_found": "Такого промокода нет",
            "inactive": "Промокод больше не действует",
            "expired": "Срок действия промокода истёк",
            "already": "Вы уже активировали этот промокод",
            "exhausted": "Промокод закончился",
        }
        if status != "ok":
            return "⚠️ " + errors.get(status, "Не удалось активировать промокод")
        fresh = db.user(user["user_id"])
        if currency == "gmpoint":
            return ("🎁 <b>Промокод активирован</b>\n\n"
                    f"Начислено: <b>+{num(amount)}</b> GMPOINT\n"
                    f"🎁 Всего: {num(fresh['gmpoint'])} GMPOINT")
        return ("🎁 <b>Промокод активирован</b>\n\n"
                f"Начислено: <b>+{num(amount)}</b> mCoin\n"
                f"💰 Баланс: {num(fresh['balance'])} mCoin")

    def tasks_view(user: dict) -> tuple[str, InlineKeyboardMarkup]:
        refs = db.referrals(user["user_id"])
        claimed = db.invite_claims(user["user_id"])
        lines = ["🎯 <b>Задания</b>", "",
                 f"👥 Друзей: {refs['total']} · активных: {refs['active']}", "",
                 "<b>Лестница приглашений</b>"]
        rows: list[list[InlineKeyboardButton]] = []
        for item in game.REF_LADDER:
            step = int(item["step"])
            reward = int(item["reward"])
            if step in claimed:
                mark, tail = "✅", "получено"
            elif refs["total"] >= step:
                mark, tail = "🔓", "можно забрать"
                rows.append([InlineKeyboardButton(
                    text=f"🎁 Забрать {num(reward)}", callback_data=f"inv:{step}")])
            else:
                mark, tail = "🔒", f"ещё {step - refs['total']} чел."
            lines.append(f"{mark} {step} друзей — {num(reward)} mCoin ({tail})")
        if config.sponsor_channels:
            done = db.sponsor_claims(user["user_id"])
            lines += ["", "<b>Спонсоры</b>"]
            for channel in config.sponsor_channels:
                if channel in done:
                    lines.append(f"✅ @{channel} — "
                                 f"{num(game.SPONSOR_REWARD)} mCoin получено")
                    continue
                lines.append(f"🎁 @{channel} — {num(game.SPONSOR_REWARD)} mCoin")
                rows.append([
                    InlineKeyboardButton(text=f"Открыть @{channel}",
                                         url=f"https://t.me/{channel}"),
                    InlineKeyboardButton(text="Проверить",
                                         callback_data=f"sp:{channel}"),
                ])
        lines += ["", "Твоя ссылка:", f"<code>{referral_link(user['user_id'])}</code>"]
        rows.append([webapp_button("🎯 Задания в приложении")])
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)

    def claim_bonuses(user: dict) -> str:
        now = int(time.time())
        settings = db.settings()
        lines = ["🎁 <b>Бонусы</b>", ""]
        gained = 0
        hourly_left = game.HOURLY_COOLDOWN - (now - int(user.get("last_hourly") or 0))
        if hourly_left <= 0:
            amount = db.claim_hourly(user["user_id"], now, game.HOURLY_COOLDOWN,
                                     game.HOURLY_BONUS)
            if amount:
                gained += amount
                lines.append(f"✅ Часовой: +{num(amount)} mCoin")
            else:
                lines.append("⏳ Часовой: ещё не готов")
        else:
            lines.append(f"⏳ Часовой: через {left_text(hourly_left)}")

        daily_left = game.DAILY_COOLDOWN - (now - int(user.get("last_daily") or 0))
        if daily_left <= 0:
            doubled = db.take_item(user["user_id"], "double_daily")
            bonus = int(settings.get("daily_bonus", game.DAILY_BONUS))
            if doubled:
                bonus *= 2
            amount = db.claim_daily(user["user_id"], now, game.DAILY_COOLDOWN, bonus)
            if amount is None:
                if doubled:
                    db.add_item(user["user_id"], "double_daily")
                lines.append("⏳ Ежедневный: ещё не готов")
            else:
                db.add_balance(user["user_id"], amount)
                gained += amount
                suffix = " (×2 за предмет)" if doubled else ""
                lines.append(f"✅ Ежедневный: +{num(amount)} mCoin{suffix}")
        else:
            lines.append(f"⏳ Ежедневный: через {left_text(daily_left)}")

        if gained:
            earned = awards.evaluate(db, user["user_id"])
            fresh = db.user(user["user_id"])
            if earned:
                lines += [""] + awards_lines(earned)
            lines += ["", f"💰 Баланс: <b>{num(fresh['balance'])}</b> mCoin"]
        else:
            lines += ["", "Пока нечего забирать — возвращайся позже."]
        return "\n".join(lines)

    def prize_title(prize: dict) -> str:
        if prize["kind"] == "coins":
            return f"+{num(prize['amount'])} mCoin"
        item = next((entry for entry in game.SHOP_ITEMS if entry["key"] == prize["item"]),
                    None)
        title = item["title"] if item else prize["item"]
        qty = game.CHARM_CHARGES if prize["item"] == "charm" else 1
        return f"{title} ×{qty}"

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        args = (message.text or "").split(maxsplit=1)
        referrer = None
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer = int(args[1][4:])
            except ValueError:
                referrer = None
            if referrer == message.from_user.id:
                referrer = None
        user = db.ensure_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            referrer,
        )
        await message.answer(
            WELCOME + f"\n\n💰 Твой баланс: <b>{num(user['balance'])} mCoin</b>",
            reply_markup=main_keyboard(),
        )

    @dp.message(Command("play", "app"))
    async def play(message: Message) -> None:
        db.ensure_user(message.from_user.id, message.from_user.username,
                       message.from_user.first_name)
        await message.answer(
            "🎮 <b>Играть</b>\n\n"
            "Полное поле, магазин и история — в приложении.\n"
            "А в чате доступны /mines и /dice.",
            reply_markup=play_keyboard(),
        )

    @dp.message(Command("mines", "saper"))
    async def mines_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(mines_hint_text(), reply_markup=mines_hint_keyboard())
            return
        if not parts[1].isdigit():
            await message.answer("Ставка должна быть числом. Пример: <code>/mines 100 5</code>")
            return
        bet = int(parts[1])
        mines = 5
        if len(parts) > 2:
            if not parts[2].isdigit():
                await message.answer(
                    "Число мин тоже числом. Пример: <code>/mines 100 5</code>")
                return
            mines = int(parts[2])
        target = 0.0
        if len(parts) > 3:
            try:
                target = float(parts[3].replace(",", "."))
            except ValueError:
                await message.answer("Авто-кэшаут — число. Пример: "
                                     "<code>/mines 100 5 2</code>")
                return
        user = get_user(message)
        error, rnd = start_mines(user, bet, mines, target)
        if error:
            await message.answer("⚠️ " + error, reply_markup=mines_hint_keyboard())
            return
        await message.answer(mines_text(rnd), reply_markup=mines_keyboard(rnd))

    @dp.message(Command("dice", "bet"))
    async def dice_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(dice_hint_text(), reply_markup=dice_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/dice 100 чёт</code>")
            return
        raw_pick = parts[2].lower() if len(parts) > 2 else ""
        if raw_pick in ("чёт", "чет", "ч", "even", "e"):
            pick = "even"
        elif raw_pick in ("нечёт", "нечет", "н", "odd", "o"):
            pick = "odd"
        else:
            await message.answer("Выбери «чёт» или «нечёт». Пример: "
                                 "<code>/dice 100 чёт</code>")
            return
        user = get_user(message)
        await message.answer(play_dice(user, int(raw_bet), pick))

    @dp.message(Command("roulette", "roul"))
    async def roulette_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(roulette_hint_text(),
                                 reply_markup=roulette_hint_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/roulette 100 красное</code>")
            return
        raw = parts[2].lower()
        if raw in ("красное", "красный", "к", "red", "r"):
            pick = "red"
        elif raw in ("чёрное", "черное", "чёрный", "черный", "ч", "black", "b"):
            pick = "black"
        elif raw in ("зеро", "зелёное", "зеленое", "0", "green", "g", "з"):
            pick = "green"
        else:
            await message.answer("Выбери: красное, чёрное или зеро.")
            return
        user = get_user(message)
        await message.answer(play_roulette(user, int(raw_bet), pick))

    @dp.message(Command("slots", "slot"))
    async def slots_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(slots_hint_text(), reply_markup=slots_hint_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/slots 100</code>")
            return
        user = get_user(message)
        await message.answer(play_slots(user, int(raw_bet)))

    @dp.message(Command("crash"))
    async def crash_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(crash_hint_text(),
                                 reply_markup=crash_hint_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/crash 100 2.5</code>")
            return
        try:
            target = float(parts[2].replace(",", "."))
        except ValueError:
            await message.answer("Цель должна быть числом. Пример: "
                                 "<code>/crash 100 2.5</code>")
            return
        user = get_user(message)
        await message.answer(play_crash(user, int(raw_bet), target))

    @dp.message(Command("coin", "flip"))
    async def coin_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(coin_hint_text(), reply_markup=coin_hint_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/coin 100 орёл</code>")
            return
        raw = parts[2].lower()
        if raw in ("орёл", "орел", "о", "heads", "h"):
            pick = "heads"
        elif raw in ("решка", "р", "tails", "t"):
            pick = "tails"
        else:
            await message.answer("Выбери: орёл или решка.")
            return
        user = get_user(message)
        await message.answer(play_coin(user, int(raw_bet), pick))

    @dp.message(Command("basket", "basketball", "bask"))
    async def basket_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(basket_hint_text(), reply_markup=basket_hint_keyboard())
            return
        raw_bet = parts[1].replace(" ", "")
        if not raw_bet.isdigit():
            await message.answer("Ставка должна быть числом. Пример: "
                                 "<code>/basket 100 попадёт</code>")
            return
        pick = "hit"
        if len(parts) >= 3:
            word = parts[2].lower()
            if word in ("промах", "промахнётся", "промахнется", "мимо", "miss", "нет"):
                pick = "miss"
            elif word in ("попадёт", "попадет", "попадание", "попал", "hit", "да"):
                pick = "hit"
            else:
                await message.answer("Выбери: попадёт или промах. Пример: "
                                     "<code>/basket 100 промах</code>")
                return
        user = get_user(message)
        bet = int(raw_bet)
        error = bet_error(user, bet, "basket")
        if error:
            await message.answer("⚠️ " + error)
            return
        shot = await message.answer_dice(emoji="🏀")
        await message.answer(play_basket(user, bet, shot.dice.value, pick),
                             reply_markup=basket_hint_keyboard())

    @dp.message(Command("pay", "transfer"))
    async def pay_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(
                "💸 <b>Перевод игроку</b>\n\n"
                "Напиши: <code>/pay 100 @ник</code> или <code>/pay 100 123456789</code>\n"
                "Свой ID видно в /balance.")
            return
        raw_amount = parts[1].replace(" ", "")
        if not raw_amount.isdigit():
            await message.answer("Сумма должна быть числом. Пример: "
                                 "<code>/pay 100 @ник</code>")
            return
        user = get_user(message)
        await message.answer(transfer_text(user, parts[2], int(raw_amount)))

    @dp.message(Command("promo"))
    async def promo_cmd(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("🎁 Введи код: <code>/promo КОД</code>")
            return
        user = get_user(message)
        await message.answer(promo_text(user, parts[1]))

    @dp.message(Command("updates", "news"))
    async def updates_cmd(message: Message) -> None:
        await message.answer(updates.full_text(), disable_web_page_preview=True)

    @dp.message(Command("duel", "duels"))
    async def duel_cmd(message: Message) -> None:
        user = get_user(message)
        parts = (message.text or "").split()
        if len(parts) > 1 and parts[1].lower() in ("top", "топ"):
            await message.answer(duel_top_text(), reply_markup=duel_menu_keyboard(user))
            return
        if len(parts) < 3:
            await message.answer(duel_menu_text(user),
                                 reply_markup=duel_menu_keyboard(user))
            return
        target = next((part for part in parts[1:] if part.startswith("@")), None)
        bet_raw = next((part for part in parts[1:] if part.isdigit()), None)
        if not target or not bet_raw:
            await message.answer("Формат: <code>/duel 100 @username</code>")
            return
        bet = int(bet_raw)
        error = bet_error(user, bet)
        if error:
            await message.answer("⚠️ " + error)
            return
        opponent = db.user_by_username(target)
        if not opponent:
            await message.answer("⚠️ Этот игрок ещё не запускал бота.")
            return
        if int(opponent["user_id"]) == int(user["user_id"]):
            await message.answer("⚠️ Нельзя вызвать самого себя.")
            return
        if opponent.get("is_banned"):
            await message.answer("⚠️ Игрок заблокирован.")
            return
        if int(opponent["balance"]) < bet:
            await message.answer("⚠️ У соперника недостаточно mCoin.")
            return
        if db.pending_duel_for(user["user_id"]):
            await message.answer("⚠️ У тебя уже есть активный вызов.")
            return
        if db.pending_duel_for(opponent["user_id"]):
            await message.answer("⚠️ У соперника уже есть активный вызов.")
            return
        now = int(time.time())
        duel_id = uuid.uuid4().hex[:10]
        db.add_balance(user["user_id"], -bet)
        db.create_duel(duel_id, user["user_id"], opponent["user_id"], bet, now)
        prize = game.duel_prize(bet)
        try:
            await message.bot.send_message(
                opponent["user_id"],
                "⚔️ <b>Вызов на дуэль</b>\n\n"
                f"{user_name(user)} вызывает тебя на <b>{num(bet)} mCoin</b>.\n"
                f"Победитель забирает {num(prize)} mCoin.\n"
                "Вызов действует 10 минут.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⚔️ Принять",
                                         callback_data=f"duel:accept:{duel_id}"),
                    InlineKeyboardButton(text="❌ Отклонить",
                                         callback_data=f"duel:decline:{duel_id}"),
                ]]),
            )
        except Exception:
            if db.close_duel(duel_id, "cancelled", now):
                db.add_balance(user["user_id"], bet)
            await message.answer("⚠️ Не удалось отправить вызов — ставка возвращена.")
            return
        await message.answer(
            "⚔️ <b>Вызов отправлен</b>\n\n"
            f"{user_name(opponent)} получил вызов на <b>{num(bet)} mCoin</b>.\n"
            f"Победитель забирает {num(prize)} mCoin.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отменить вызов",
                                     callback_data=f"duel:cancel:{duel_id}")]]),
        )

    @dp.message(Command("spin", "wheel"))
    async def spin_cmd(message: Message) -> None:
        user = get_user(message)
        if user.get("is_banned"):
            await message.answer("Аккаунт заблокирован.")
            return
        settings = db.settings()
        if int(settings.get("game_wheel", 1)) != 1:
            await message.answer("Колесо временно отключено.")
            return
        now = int(time.time())
        left = game.SPIN_COOLDOWN - (now - int(user.get("last_spin") or 0))
        if left > 0:
            await message.answer(
                f"🎡 Крутить можно раз в 12 часов.\n"
                f"Следующее вращение через <b>{left_text(left)}</b>.")
            return
        nonce = db.bump_nonce(user["user_id"])
        index, prize = game.spin_daily(user["server_seed"], user["client_seed"], nonce)
        day = int(user.get("spin_day") or 1)
        next_day = day + 1 if day < game.SPIN_STREAK_DAYS else 1
        if prize["kind"] == "coins":
            db.add_balance(user["user_id"], prize["amount"])
        else:
            db.add_item(user["user_id"], prize["item"], prize_title_qty(prize))
        db.mark_spin(user["user_id"], now, next_day)
        awards.evaluate(db, user["user_id"])
        fresh = db.user(user["user_id"])
        await message.answer(
            "🎡 <b>Колесо дня</b>\n\n"
            f"Выпало: <b>{prize_title(prize)}</b>\n"
            f"День серии: {day}/{game.SPIN_STREAK_DAYS}\n"
            f"💰 Баланс: {num(fresh['balance'])} mCoin\n\n"
            f"Следующее вращение через {left_text(game.SPIN_COOLDOWN)}",
            reply_markup=main_keyboard(),
        )

    def prize_title_qty(prize: dict) -> int:
        return game.CHARM_CHARGES if prize["item"] == "charm" else 1

    @dp.message(Command("bonus", "daily"))
    async def bonus_cmd(message: Message) -> None:
        user = get_user(message)
        await message.answer(claim_bonuses(user), reply_markup=main_keyboard())

    @dp.message(Command("balance", "profile", "me"))
    async def balance_cmd(message: Message) -> None:
        user = get_user(message)
        await message.answer(profile_text(user), reply_markup=profile_keyboard())

    @dp.message(Command("achievements", "ach"))
    async def achievements_cmd(message: Message) -> None:
        user = get_user(message)
        await message.answer(achievements_text(user), reply_markup=profile_keyboard())

    @dp.callback_query(F.data == "menu:ach")
    async def menu_ach(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(achievements_text(user),
                                      reply_markup=profile_keyboard())
        await callback.answer()

    @dp.message(Command("levels", "level"))
    async def levels_cmd(message: Message) -> None:
        user = get_user(message)
        await message.answer(level_menu_text(user),
                             reply_markup=level_menu_keyboard(user))

    @dp.callback_query(F.data == "level:menu")
    async def level_menu_cb(callback) -> None:
        user = get_user(callback)
        await safe_edit(callback.message, level_menu_text(user),
                        level_menu_keyboard(user))
        await callback.answer()

    @dp.callback_query(F.data == "level:claim")
    async def level_claim_cb(callback) -> None:
        user = get_user(callback)
        got, coins = claim_levels(user)
        fresh = db.user(user["user_id"])
        if not got:
            await callback.answer("Наград пока нет", show_alert=True)
            await safe_edit(callback.message, level_menu_text(fresh),
                            level_menu_keyboard(fresh))
            return
        last = got[-1]
        parts = [f"Уровней: {len(got)}", f"+{num(coins)} mCoin"]
        gmpoint = sum(item["gmpoint"] for item in got)
        if gmpoint:
            parts.append(f"+{gmpoint} GMPOINT")
        boxes = sum(item["lootbox"] for item in got)
        if boxes:
            parts.append(f"+{boxes} лутбокс")
        prefixes = [game.prefix_view(item["prefix"]) for item in got if item["prefix"]]
        for prefix in prefixes:
            if prefix:
                parts.append(f"префикс «{prefix['title']}»")
        await callback.answer(f"Получено до уровня {last['level']}", show_alert=False)
        await safe_edit(
            callback.message,
            "🎉 <b>Награды получены</b>\n\n" + "\n".join(f"• {p}" for p in parts) +
            f"\n\n💰 Баланс: {num(fresh['balance'])} mCoin",
            level_menu_keyboard(fresh),
        )

    @dp.message(Command("deposit", "bank"))
    async def deposit_cmd(message: Message) -> None:
        user = get_user(message)
        await message.answer(bank_text(user), reply_markup=bank_keyboard())

    @dp.message(Command("tasks", "quests"))
    async def tasks_cmd(message: Message) -> None:
        user = get_user(message)
        text, keyboard = tasks_view(user)
        await message.answer(text, reply_markup=keyboard)

    @dp.message(Command("top"))
    async def top_cmd(message: Message) -> None:
        await message.answer(top_text(), reply_markup=main_keyboard())

    @dp.message(Command("ref"))
    async def ref(message: Message) -> None:
        user = get_user(message)
        stats = db.referrals(user["user_id"])
        await message.answer(
            f"👥 <b>Приглашай друзей</b>\n\n"
            f"<code>{referral_link(user['user_id'])}</code>\n\n"
            f"Приглашено: {stats['total']}, активных: {stats['active']}\n"
            f"За каждого друга, сыгравшего 5 партий, — {game.REF_BONUS} mCoin.\n"
            "Плюс награды по лестнице: /tasks",
            disable_web_page_preview=True,
        )

    @dp.message(Command("chat"))
    async def chat_cmd(message: Message) -> None:
        get_user(message)
        if not config.chat_url:
            await message.answer(
                "💬 <b>Чат игроков</b>\n\n"
                "Чат ещё не настроен. Создай группу в Telegram, добавь в неё бота "
                "администратором и укажи ссылку в переменной <code>CHAT_URL</code>.",
            )
            return
        await message.answer(
            "💬 <b>Чат игроков</b>\n\nОбсуждай игры, ищи соперников для дуэлей и делись выигрышами.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Открыть чат", url=config.chat_url)],
            ]),
        )

    @dp.message(Command("fair"))
    async def fair(message: Message) -> None:
        user = get_user(message)
        await message.answer(
            "🔐 <b>Provably fair</b>\n\n"
            f"Хеш серверного seed:\n<code>{user['server_seed_hash']}</code>\n"
            f"Клиентский seed: <code>{user['client_seed']}</code>\n"
            f"Nonce: {user['nonce']}\n\n"
            "Позиции мин считаются как HMAC-SHA256(server_seed, client_seed:nonce:i). "
            "Кости и колесо используют тот же поток. "
            "Сменить seed и увидеть старый можно в приложении на вкладке «Честность»."
        )

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        await message.answer(
            "💣 <b>Что умеет бот</b>\n\n"
            "<b>Играть в чате</b>\n"
            "/mines 100 5 — сапёр: ставка и число мин\n"
            "/dice 100 чёт — кости, выплата ×1,96\n"
            "/roulette 100 красное — рулетка (зеро ×36)\n"
            "/slots 100 — слоты (тройки до ×200)\n"
            "/crash 100 2.5 — краш с целью ×1,20–×10\n"
            "/coin 100 орёл — орёл и решка, ×1,96\n"
            "/basket 100 попадёт — баскет: забросит мяч или нет\n"
            "/duel 100 @username — дуэль 1×1 на бросок\n"
            "/spin — колесо дня раз в 12 часов\n\n"
            "<b>Баланс и бонусы</b>\n"
            "/balance — профиль, ID и статистика\n"
            "/pay 100 @ник — перевод другому игроку\n"
            "/promo КОД — активировать промокод\n"
            "/bonus — часовой и ежедневный бонусы\n"
            "/deposit — вклады под процент\n"
            "/tasks — приглашения и спонсоры\n"
            "/achievements — уровни и достижения\n"
            "/top — рейтинг игроков\n\n"
            "<b>Приложение</b>\n"
            "/play — полное поле, магазин и история\n"
            "/ref — ссылка для друзей\n"
            "/fair — проверка честности\n\n"
            "<b>В группах</b>\n"
            "Добавьте бота в чат — игры и команды работают там же,\n"
            "/chatid покажет ID чата для настроек.\n\n"
            "Валюта mCoin виртуальная: реальные деньги не принимаются и не выводятся.",
            reply_markup=main_keyboard(),
        )

    @dp.message(Command("roles"))
    async def roles_cmd(message: Message) -> None:
        await message.answer(roles_text())

    @dp.message(Command("chatid"))
    async def chatid_cmd(message: Message) -> None:
        chat = message.chat
        title = chat.title or getattr(chat, "full_name", "") or ""
        await message.answer(
            "🆔 <b>Этот чат</b>\n\n"
            f"ID: <code>{chat.id}</code>\n"
            f"Тип: {chat.type}\n"
            f"Название: {title}\n\n"
            "Для анонсов обновлений добавьте бота админом в канал и укажите\n"
            "<code>UPDATE_CHANNEL=@username</code> в переменных окружения.")

    @dp.message(Command("stats"))
    async def stats_cmd(message: Message) -> None:
        user = get_user(message)
        if not can(user, "moderator"):
            await message.answer("Команда доступна модераторам и админам.")
            return
        s = db.admin_stats()
        await message.answer(
            "📊 <b>Сводка</b>\n\n"
            f"Игроков: {num(int(s.get('users', 0)))}\n"
            f"Забанено: {num(int(s.get('banned', 0)))}\n"
            f"Партий: {num(int(s.get('rounds', 0)))}\n"
            f"Активных: {num(int(s.get('active_rounds', 0)))}\n"
            f"Оборот: {num(int(s.get('wagered', 0)))} mCoin\n"
            f"Выплачено: {num(int(s.get('paid', 0)))} mCoin")

    @dp.message(Command("player"))
    async def player_cmd(message: Message) -> None:
        user = get_user(message)
        if not can(user, "moderator"):
            await message.answer("Команда доступна модераторам и админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: <code>/player 123456789</code> "
                                 "или <code>/player @ник</code>")
            return
        target = find_user(parts[1])
        if not target:
            await message.answer("Игрок не найден.")
            return
        await message.answer(player_card(target))

    @dp.message(Command("ban"))
    async def ban_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "moderator"):
            await message.answer("Команда доступна модераторам и админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: <code>/ban 123456789 причина</code>")
            return
        target = find_user(parts[1])
        if not target:
            await message.answer("Игрок не найден.")
            return
        if int(target["user_id"]) == int(actor["user_id"]):
            await message.answer("Себя банить не нужно.")
            return
        if not is_owner(actor) and rank(target) >= rank(actor):
            await message.answer("Нельзя блокировать равного или старшего по роли.")
            return
        reason = " ".join(parts[2:]).strip() or "не указана"
        db.admin_set_ban(int(target["user_id"]), True)
        db.admin_log(actor["user_id"], int(target["user_id"]), "ban",
                     {"reason": reason})
        await message.answer(f"⛔ Игрок <code>{target['user_id']}</code> заблокирован.\n"
                             f"Причина: {reason}")

    @dp.message(Command("unban"))
    async def unban_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "moderator"):
            await message.answer("Команда доступна модераторам и админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: <code>/unban 123456789</code>")
            return
        target = find_user(parts[1])
        if not target:
            await message.answer("Игрок не найден.")
            return
        db.admin_set_ban(int(target["user_id"]), False)
        db.admin_log(actor["user_id"], int(target["user_id"]), "unban", {})
        await message.answer(f"✅ Игрок <code>{target['user_id']}</code> разблокирован.")

    @dp.message(Command("logs"))
    async def logs_cmd(message: Message) -> None:
        user = get_user(message)
        if not can(user, "moderator"):
            await message.answer("Команда доступна модераторам и админам.")
            return
        rows = db.admin_actions(10)
        if not rows:
            await message.answer("Журнал пока пуст.")
            return
        lines = ["📜 <b>Последние действия</b>", ""]
        for row in rows:
            lines.append(f"• {row.get('action', '?')} · "
                         f"{row.get('admin_id', '?')} → "
                         f"{row.get('target_id', '—')}")
        await message.answer("\n".join(lines))

    @dp.message(Command("setbal"))
    async def setbal_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer("Формат: <code>/setbal 123456789 5000</code>")
            return
        target = find_user(parts[1])
        try:
            value = int(parts[2])
        except ValueError:
            await message.answer("Баланс должен быть числом.")
            return
        if not target or value < 0:
            await message.answer("Игрок не найден или баланс отрицательный.")
            return
        new_balance = db.admin_set_balance(int(target["user_id"]), value)
        db.admin_log(actor["user_id"], int(target["user_id"]), "setbal",
                     {"value": value})
        await message.answer(f"💰 Баланс <code>{target['user_id']}</code>: "
                             f"{num(int(new_balance))} mCoin")

    @dp.message(Command("addbal"))
    async def addbal_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer("Формат: <code>/addbal 123456789 500</code> "
                                 "(минус — списать)")
            return
        target = find_user(parts[1])
        try:
            delta = int(parts[2])
        except ValueError:
            await message.answer("Сумма должна быть числом.")
            return
        if not target:
            await message.answer("Игрок не найден.")
            return
        balance = int(target["balance"]) + delta
        if balance < 0:
            await message.answer("Баланс не может уйти в минус.")
            return
        db.admin_set_balance(int(target["user_id"]), balance)
        db.admin_log(actor["user_id"], int(target["user_id"]), "addbal",
                     {"delta": delta})
        await message.answer(f"💰 Баланс <code>{target['user_id']}</code>: "
                             f"{num(balance)} mCoin")

    @dp.message(Command("role"))
    async def role_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        parts = (message.text or "").split()
        if len(parts) < 3 or parts[2].lower() not in ("user", "moderator", "admin"):
            await message.answer(
                "Формат: <code>/role 123456789 moderator</code>\n"
                "Роли: user, moderator, admin.")
            return
        target = find_user(parts[1])
        role = parts[2].lower()
        if not target:
            await message.answer("Игрок не найден.")
            return
        if int(target["user_id"]) == int(actor["user_id"]):
            await message.answer("Свою роль менять нельзя.")
            return
        if role == "admin" and not is_owner(actor):
            await message.answer("Назначать админов может только владелец.")
            return
        if not is_owner(actor) and rank(target) >= rank(actor):
            await message.answer("Нельзя менять роль равного или старшего.")
            return
        db.admin_set_role(int(target["user_id"]), role)
        db.admin_log(actor["user_id"], int(target["user_id"]), "role",
                     {"role": role})
        await message.answer(f"🛠 Игрок <code>{target['user_id']}</code> теперь "
                             f"<b>{role}</b>.")

    @dp.message(Command("give"))
    async def give_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        parts = (message.text or "").split()
        known = {item["key"] for item in game.SHOP_ITEMS}
        known |= {"insurance", "double_daily", "charm"}
        if len(parts) < 3:
            await message.answer("Формат: <code>/give 123456789 insurance 2</code>\n"
                                 "Предметы: " + ", ".join(sorted(known)))
            return
        target = find_user(parts[1])
        item = parts[2].strip()
        try:
            qty = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            qty = 1
        if not target:
            await message.answer("Игрок не найден.")
            return
        if item not in known:
            await message.answer("Неизвестный предмет. Доступно: "
                                 + ", ".join(sorted(known)))
            return
        qty = max(1, min(100, qty))
        total = db.add_item(int(target["user_id"]), item, qty)
        db.admin_log(actor["user_id"], int(target["user_id"]), "give",
                     {"item": item, "qty": qty})
        await message.answer(f"🎁 Выдано {item} ×{qty}. Всего у игрока: {total}.")

    @dp.message(Command("maint"))
    async def maint_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        parts = (message.text or "").split()
        arg = parts[1].lower() if len(parts) > 1 else ""
        if arg not in ("on", "off", "1", "0"):
            await message.answer("Формат: <code>/maint on</code> или "
                                 "<code>/maint off</code>")
            return
        value = 1 if arg in ("on", "1") else 0
        db.set_settings({"maintenance": value})
        db.admin_log(actor["user_id"], None, "maintenance", {"value": value})
        await message.answer("🛠 Техработы включены." if value
                             else "✅ Техработы выключены.")

    @dp.message(Command("game"))
    async def game_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        aliases = {
            "mines": "mines", "сапёр": "mines", "сапер": "mines",
            "dice": "dice", "кости": "dice",
            "wheel": "wheel", "колесо": "wheel",
            "crash": "crash", "краш": "crash",
            "coinflip": "coinflip", "орёл": "coinflip", "орел": "coinflip",
            "blackjack": "blackjack", "21": "blackjack",
            "basket": "basket", "баскет": "basket",
            "roulette": "roulette", "рулетка": "roulette",
            "slots": "slots", "слоты": "slots",
        }
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(
                "Формат: <code>/game basket off</code>\n"
                "Игры: " + ", ".join(sorted(set(aliases.values()))))
            return
        key = aliases.get(parts[1].lower())
        arg = parts[2].lower()
        if not key or arg not in ("on", "off", "1", "0"):
            await message.answer("Неизвестная игра или состояние. "
                                 "Пример: <code>/game dice off</code>")
            return
        value = 1 if arg in ("on", "1") else 0
        db.set_settings({f"game_{key}": value})
        db.admin_log(actor["user_id"], None, "game", {"game": key, "value": value})
        await message.answer(f"🎮 Игра <b>{key}</b> "
                             f"{'включена' if value else 'выключена'}.")

    @dp.message(Command("broadcast"))
    async def broadcast_cmd(message: Message) -> None:
        actor = get_user(message)
        if not can(actor, "admin"):
            await message.answer("Команда доступна админам.")
            return
        text = (message.text or "").partition(" ")[2].strip()
        if not text:
            await message.answer("Формат: <code>/broadcast текст</code>")
            return
        if len(text) > 3500:
            await message.answer("Слишком длинное сообщение (до 3500 символов).")
            return
        sent = 0
        failed = 0
        for user_id in db.broadcast_ids():
            try:
                await message.bot.send_message(user_id, text)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.03)
        db.admin_log(actor["user_id"], None, "broadcast",
                     {"sent": sent, "failed": failed})
        await message.answer(f"📣 Рассылка: отправлено {sent}, ошибок {failed}.")

    @dp.message(Command("admin"))
    async def admin_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        url = f"{config.public_url}/?admin=1" if config.public_url else "https://example.com/"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Открыть админку", web_app=WebAppInfo(url=url))],
            [InlineKeyboardButton(text="👥 Все игроки", callback_data="adm:pl:1")],
        ])
        await message.answer(
            "<b>Админ-панель</b>\n\n"
            "• Игроки — поиск, начисление и списание mCoin, выдача предметов, бан\n"
            "• Сводка — оборот, выплаты, RTP, статистика по играм\n"
            "• Промокоды — создание, лимиты, публикация в канал\n"
            "• Настройки — лимиты ставки, число мин, бонус, игры, техработы\n\n"
            "<b>Команды</b>\n"
            "/roles — кто что может\n"
            "/stats · /player ID · /logs\n"
            "/ban ID · /unban ID\n"
            "/setbal ID сумма · /addbal ID сумма\n"
            "/role ID moderator · /give ID предмет\n"
            "/promo_new · /promo_list · /promo_post · /promo_off\n"
            "/maint on|off · /game имя on|off · /broadcast текст\n"
            "/chatid — ID группы или канала",
            reply_markup=keyboard,
        )

    @dp.message(Command("promo_new"))
    async def promo_new_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        parts = (message.text or "").split()
        if len(parts) < 4:
            await message.answer(
                "Формат: <code>/promo_new 500 100 50000 [КОД]</code>\n"
                "500 — сумма на игрока, 100 — сколько активаций (0 — без лимита),\n"
                "50000 — общий бюджет (0 — без лимита). Код можно не указывать.")
            return
        try:
            amount = int(parts[1])
            uses = int(parts[2])
            budget = int(parts[3])
        except ValueError:
            await message.answer("Сумма, активации и бюджет должны быть числами.")
            return
        if amount < 1 or max(amount * uses, amount) > 100_000_000:
            await message.answer("Проверьте сумму и лимиты.")
            return
        code = parts[4].strip().upper() if len(parts) > 4 else uuid.uuid4().hex[:8].upper()
        if db.promo(code):
            await message.answer("Такой промокод уже есть. Выберите другой.")
            return
        db.create_promo(code, amount, max(0, uses), max(0, budget), 1, None, "")
        await message.answer(
            f"🎁 Промокод <code>{code}</code> создан\n"
            f"На игрока: {num(amount)} mCoin\n"
            f"Активаций: {uses if uses > 0 else 'без лимита'}\n"
            f"Бюджет: {num(budget) if budget > 0 else 'без лимита'}\n\n"
            f"Игроки вводят: <code>/promo {code}</code>")

    @dp.message(Command("promo_list"))
    async def promo_list_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        rows = db.promos(10)
        if not rows:
            await message.answer("Промокодов пока нет. Создайте: "
                                 "<code>/promo_new 500 100 50000</code>")
            return
        lines = ["🎁 <b>Последние промокоды</b>", ""]
        for promo in rows:
            state = "активен" if int(promo["active"]) else "выключен"
            uses = (f"{promo['used']}/{promo['max_uses']}"
                    if int(promo["max_uses"]) else f"{promo['used']}/∞")
            budget = (f"{num(int(promo['spent']))}/{num(int(promo['budget']))}"
                      if int(promo["budget"]) else f"{num(int(promo['spent']))}/∞")
            lines.append(f"<code>{promo['code']}</code> · {num(int(promo['amount']))} mCoin"
                         f" · активаций {uses} · выплачено {budget} · {state}")
        await message.answer("\n".join(lines))

    @dp.message(Command("promo_off"))
    async def promo_off_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: <code>/promo_off КОД</code>")
            return
        code = parts[1].strip().upper()
        if db.promo_deactivate(code):
            await message.answer(f"Промокод <code>{code}</code> выключен.")
        else:
            await message.answer("Такого промокода нет.")

    @dp.message(Command("promo_post"))
    async def promo_post_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Формат: <code>/promo_post КОД</code>")
            return
        code = parts[1].strip().upper()
        promo = db.promo(code)
        if not promo:
            await message.answer("Такого промокода нет.")
            return
        if not config.update_channel:
            await message.answer("Канал не настроен: добавьте UPDATE_CHANNEL "
                                 "вида @my_channel в переменные окружения.")
            return
        left = ("∞" if not int(promo["max_uses"])
                else str(max(0, int(promo["max_uses"]) - int(promo["used"]))))
        budget_left = ("∞" if not int(promo["budget"])
                       else num(max(0, int(promo["budget"]) - int(promo["spent"]))))
        text = (f"🎁 <b>Промокод {code}</b>\n\n"
                f"+{num(int(promo['amount']))} mCoin каждому\n"
                f"Осталось активаций: {left}\n"
                f"Осталось в бюджете: {budget_left} mCoin\n\n"
                f"Активировать: <code>/promo {code}</code>")
        channel = config.update_channel
        target = channel if channel.startswith("@") else "@" + channel
        try:
            await message.bot.send_message(target, text)
            await message.answer("Промокод опубликован в канале.")
        except Exception as exc:
            await message.answer(f"Не удалось опубликовать: {exc}")

    @dp.callback_query(F.data == "top")
    async def top_cb(callback) -> None:
        await callback.message.answer(top_text())
        await callback.answer()

    @dp.callback_query(F.data == "top:menu")
    async def top_menu_cb(callback) -> None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 По балансу", callback_data="top"),
             InlineKeyboardButton(text="⭐ По уровню", callback_data="top:level")],
            [InlineKeyboardButton(text="⚔️ Дуэлянты", callback_data="duel:top")],
        ])
        await safe_edit(callback.message, "🏆 <b>Рейтинги</b>\n\nВыбери, что показать.",
                        keyboard)
        await callback.answer()

    @dp.callback_query(F.data == "top:level")
    async def top_level_cb(callback) -> None:
        await callback.message.answer(top_level_text())
        await callback.answer()

    @dp.callback_query(F.data.startswith("adm:pl:"))
    async def admin_players_cb(callback) -> None:
        user = get_user(callback)
        if not is_admin(user):
            await callback.answer("Команда доступна только администратору.",
                                  show_alert=True)
            return
        try:
            page = int(callback.data.split(":")[2])
        except (IndexError, ValueError):
            page = 1
        data = db.admin_players(page, 10)
        await safe_edit(callback.message, admin_players_text(data),
                        admin_players_keyboard(data))
        await callback.answer()

    @dp.callback_query(F.data == "fair")
    async def fair_cb(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(
            f"Хеш seed: <code>{user['server_seed_hash']}</code>\n"
            f"Клиентский seed: <code>{user['client_seed']}</code>\n"
            f"Nonce: {user['nonce']}"
        )
        await callback.answer()

    @dp.callback_query(F.data == "menu:mines")
    async def menu_mines(callback) -> None:
        await callback.message.answer(mines_hint_text(),
                                      reply_markup=mines_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:dice")
    async def menu_dice(callback) -> None:
        await callback.message.answer(dice_hint_text(), reply_markup=dice_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:bonus")
    async def menu_bonus(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(claim_bonuses(user), reply_markup=main_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:bank")
    async def menu_bank(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(bank_text(user), reply_markup=bank_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:balance")
    async def menu_balance(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(profile_text(user), reply_markup=profile_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:tasks")
    async def menu_tasks(callback) -> None:
        user = get_user(callback)
        text, keyboard = tasks_view(user)
        await callback.message.answer(text, reply_markup=keyboard)
        await callback.answer()

    @dp.callback_query(F.data.startswith("ms:"))
    async def mines_quick(callback) -> None:
        parts = callback.data.split(":")
        target = float(parts[3]) if len(parts) > 3 else 0.0
        user = get_user(callback)
        error, rnd = start_mines(user, int(parts[1]), int(parts[2]), target)
        if error:
            await callback.answer(error, show_alert=True)
            return
        await safe_edit(callback.message, mines_text(rnd), mines_keyboard(rnd))
        await callback.answer("Партия началась")

    @dp.callback_query(F.data.startswith("m:"))
    async def mines_open(callback) -> None:
        _, round_id, cell_raw = callback.data.split(":")
        cell = int(cell_raw)
        user = get_user(callback)
        rnd = db.round(round_id)
        if not rnd or int(rnd["user_id"]) != int(user["user_id"]):
            await callback.answer("Это не твоя партия", show_alert=True)
            return
        if rnd["status"] != "active":
            await callback.answer("Партия уже завершена", show_alert=True)
            return
        if cell in rnd["opened"]:
            await callback.answer("Клетка уже открыта")
            return
        if cell in rnd["mine_positions"]:
            db.update_round(round_id, rnd["opened"], rnd["multiplier"], "lost", 0)
            earned, xp_gain, level_before, level_after = finish_game(
                user, rnd["bet"], 0, 0)
            refund = insurance_refund(user, rnd["bet"])
            balance = db.user(user["user_id"])["balance"]
            text = mines_lost_text(rnd, cell, refund, balance)
            text += "\n" + xp_line(xp_gain, level_before, level_after)
            if earned:
                text += "\n" + "\n".join(awards_lines(earned))
            await safe_edit(callback.message, text, finished_keyboard())
            await callback.answer("💥 Мина!")
            return
        opened = rnd["opened"] + [cell]
        mult = game.multiplier(int(rnd["mines"]), len(opened))
        safe = game.CELLS - int(rnd["mines"])
        if len(opened) >= safe:
            payout = game.payout_for(rnd["bet"], mult)
            payout = charm_bonus(user, payout)
            payout = apply_relic(user, "mines", payout)
            payout = gold_pick_bonus(user, payout)
            db.update_round(round_id, opened, mult, "won", payout)
            db.add_balance(user["user_id"], payout)
            earned, xp_gain, level_before, level_after = finish_game(
                user, rnd["bet"], payout, mult)
            balance = db.user(user["user_id"])["balance"]
            lines = ["🏆 <b>Поле очищено!</b>", "",
                     f"Множитель: ×{mult:.2f}",
                     f"Выплата: <b>+{num(payout)}</b> mCoin",
                     xp_line(xp_gain, level_before, level_after)]
            lines.extend(awards_lines(earned))
            lines.append(f"💰 Баланс: {num(balance)} mCoin")
            await safe_edit(callback.message, "\n".join(lines), finished_keyboard())
            await callback.answer(f"+{num(payout)}")
            return
        target = float(rnd.get("auto_target") or 0)
        if target and mult >= target:
            text, payout = cashout_round(user, rnd, round_id, opened, mult, auto=True)
            await safe_edit(callback.message, text, finished_keyboard())
            await callback.answer(f"Авто-кэшаут +{num(payout)}")
            return
        db.update_round(round_id, opened, mult, "active", 0)
        fresh = dict(rnd)
        fresh["opened"] = opened
        fresh["multiplier"] = mult
        await safe_edit(callback.message, mines_text(fresh), mines_keyboard(fresh))
        await callback.answer("Безопасно")

    @dp.callback_query(F.data.startswith("c:"))
    async def mines_cashout(callback) -> None:
        _, round_id = callback.data.split(":")
        user = get_user(callback)
        rnd = db.round(round_id)
        if not rnd or int(rnd["user_id"]) != int(user["user_id"]):
            await callback.answer("Это не твоя партия", show_alert=True)
            return
        if rnd["status"] != "active":
            await callback.answer("Партия уже завершена", show_alert=True)
            return
        if not rnd["opened"]:
            await callback.answer("Сначала открой хотя бы одну клетку", show_alert=True)
            return
        mult = game.multiplier(int(rnd["mines"]), len(rnd["opened"]))
        text, payout = cashout_round(user, rnd, round_id, rnd["opened"], mult)
        await safe_edit(callback.message, text, finished_keyboard())
        await callback.answer(f"+{num(payout)}")

    @dp.callback_query(F.data == "menu:duel")
    async def menu_duel(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(duel_menu_text(user),
                                      reply_markup=duel_menu_keyboard(user))
        await callback.answer()

    @dp.callback_query(F.data == "duel:top")
    async def duel_top(callback) -> None:
        user = get_user(callback)
        await callback.message.answer(duel_top_text(),
                                      reply_markup=duel_menu_keyboard(user))
        await callback.answer()

    @dp.callback_query(F.data.startswith("duel:accept:"))
    async def duel_accept(callback) -> None:
        duel_id = callback.data.split(":")[-1]
        user = get_user(callback)
        duel = db.duel(duel_id)
        if not duel or duel["status"] != "pending":
            await callback.answer("Вызов уже неактивен", show_alert=True)
            return
        if int(duel["opponent_id"]) != int(user["user_id"]):
            await callback.answer("Этот вызов не тебе", show_alert=True)
            return
        now = int(time.time())
        challenger = db.user(duel["challenger_id"])
        if not challenger:
            await callback.answer("Соперник не найден", show_alert=True)
            return
        bet = int(duel["bet"])
        if now - int(duel["created_at"]) > game.DUEL_TTL:
            if db.close_duel(duel_id, "expired", now):
                db.add_balance(challenger["user_id"], bet)
                awards.evaluate(db, challenger["user_id"])
            await safe_edit(callback.message,
                            "⌛ <b>Вызов истёк</b>\nСтавка возвращена сопернику.",
                            None)
            await callback.answer("Вызов истёк", show_alert=True)
            return
        if int(user["balance"]) < bet:
            await callback.answer("Недостаточно mCoin для ответа", show_alert=True)
            return
        db.add_balance(user["user_id"], -bet)
        result = resolve_duel(duel, challenger, user)
        if result is None:
            db.add_balance(user["user_id"], bet)
            await callback.answer("Вызов уже обработан", show_alert=True)
            return
        await safe_edit(callback.message, duel_play_text(duel, user, result),
                        duel_result_keyboard())
        try:
            await callback.bot.send_message(
                challenger["user_id"], duel_play_text(duel, challenger, result),
                reply_markup=duel_result_keyboard())
        except Exception:
            pass
        await callback.answer("Дуэль завершена")

    @dp.callback_query(F.data.startswith("duel:decline:"))
    async def duel_decline(callback) -> None:
        duel_id = callback.data.split(":")[-1]
        user = get_user(callback)
        duel = db.duel(duel_id)
        if not duel or duel["status"] != "pending":
            await callback.answer("Вызов уже неактивен", show_alert=True)
            return
        if int(duel["opponent_id"]) != int(user["user_id"]):
            await callback.answer("Этот вызов не тебе", show_alert=True)
            return
        now = int(time.time())
        bet = int(duel["bet"])
        if not db.close_duel(duel_id, "declined", now):
            await callback.answer("Вызов уже обработан", show_alert=True)
            return
        challenger = db.user(duel["challenger_id"])
        db.add_balance(challenger["user_id"], bet)
        awards.evaluate(db, challenger["user_id"])
        await safe_edit(callback.message,
                        "❌ <b>Вызов отклонён</b>\nСтавка возвращена сопернику.",
                        None)
        try:
            await callback.bot.send_message(
                challenger["user_id"],
                f"❌ {user_name(user)} отклонил вызов на {num(bet)} mCoin. "
                "Ставка возвращена.")
        except Exception:
            pass
        await callback.answer("Отклонено")

    @dp.callback_query(F.data.startswith("duel:cancel:"))
    async def duel_cancel(callback) -> None:
        duel_id = callback.data.split(":")[-1]
        user = get_user(callback)
        duel = db.duel(duel_id)
        if not duel or duel["status"] != "pending":
            await callback.answer("Вызов уже неактивен", show_alert=True)
            return
        if int(duel["challenger_id"]) != int(user["user_id"]):
            await callback.answer("Отменить может только автор вызова", show_alert=True)
            return
        now = int(time.time())
        bet = int(duel["bet"])
        if not db.close_duel(duel_id, "cancelled", now):
            await callback.answer("Вызов уже обработан", show_alert=True)
            return
        db.add_balance(user["user_id"], bet)
        awards.evaluate(db, user["user_id"])
        await safe_edit(callback.message,
                        "❌ <b>Вызов отменён</b>\nСтавка возвращена.", None)
        try:
            await callback.bot.send_message(
                duel["opponent_id"],
                f"❌ {user_name(user)} отменил вызов на {num(bet)} mCoin.")
        except Exception:
            pass
        await callback.answer("Отменено")

    @dp.callback_query(F.data == "menu:games")
    async def menu_games(callback) -> None:
        await callback.message.answer(games_hint_text(), reply_markup=games_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:roulette")
    async def menu_roulette(callback) -> None:
        await callback.message.answer(roulette_hint_text(),
                                      reply_markup=roulette_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:slots")
    async def menu_slots(callback) -> None:
        await callback.message.answer(slots_hint_text(),
                                      reply_markup=slots_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "menu:crash")
    async def menu_crash(callback) -> None:
        await callback.message.answer(crash_hint_text(),
                                      reply_markup=crash_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("rl:"))
    async def roulette_quick(callback) -> None:
        _, bet_raw, pick = callback.data.split(":")
        user = get_user(callback)
        await callback.message.answer(play_roulette(user, int(bet_raw), pick))
        await callback.answer("Готово")

    @dp.callback_query(F.data.startswith("sl:"))
    async def slots_quick(callback) -> None:
        bet = int(callback.data.split(":")[1])
        user = get_user(callback)
        await callback.message.answer(play_slots(user, bet))
        await callback.answer("Готово")

    @dp.callback_query(F.data.startswith("cr:"))
    async def crash_quick(callback) -> None:
        _, bet_raw, target_raw = callback.data.split(":")
        user = get_user(callback)
        await callback.message.answer(play_crash(user, int(bet_raw),
                                                 float(target_raw)))
        await callback.answer("Готово")

    @dp.callback_query(F.data == "menu:coin")
    async def menu_coin(callback) -> None:
        await callback.message.answer(coin_hint_text(),
                                      reply_markup=coin_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("cf:"))
    async def coin_quick(callback) -> None:
        _, bet_raw, pick = callback.data.split(":")
        user = get_user(callback)
        await callback.message.answer(play_coin(user, int(bet_raw), pick))
        await callback.answer("Готово")

    @dp.callback_query(F.data == "menu:basket")
    async def menu_basket(callback) -> None:
        await callback.message.answer(basket_hint_text(),
                                      reply_markup=basket_hint_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("bs:"))
    async def basket_quick(callback) -> None:
        parts_cb = callback.data.split(":")
        bet_raw = parts_cb[1]
        pick = parts_cb[2] if len(parts_cb) > 2 else "hit"
        user = get_user(callback)
        bet = int(bet_raw)
        error = bet_error(user, bet, "basket")
        if error:
            await callback.answer(error[:60], show_alert=True)
            return
        shot = await callback.message.answer_dice(emoji="🏀")
        await callback.message.answer(play_basket(user, bet, shot.dice.value, pick),
                                      reply_markup=basket_hint_keyboard())
        await callback.answer("Бросок!")

    @dp.callback_query(F.data.startswith("d:"))
    async def dice_quick(callback) -> None:
        _, bet_raw, pick_raw = callback.data.split(":")
        pick = "even" if pick_raw == "e" else "odd"
        user = get_user(callback)
        text = play_dice(user, int(bet_raw), pick)
        await callback.message.answer(text)
        prefix = "⚠️ " if text.startswith("⚠️") else ""
        await callback.answer(prefix + ("Готово" if not prefix else text[2:40]))

    @dp.callback_query(F.data == "dep:main")
    async def dep_main(callback) -> None:
        user = get_user(callback)
        await safe_edit(callback.message, bank_text(user), bank_keyboard())
        await callback.answer()

    @dp.callback_query(F.data == "dep:fixed")
    async def dep_fixed(callback) -> None:
        await safe_edit(callback.message, fixed_text(), fixed_keyboard())
        await callback.answer()

    @dp.callback_query(F.data.startswith("depf:"))
    async def dep_plan(callback) -> None:
        days = int(callback.data.split(":")[1])
        await safe_edit(callback.message, deposit_amounts_text(days),
                        deposit_amounts_keyboard(days))
        await callback.answer()

    @dp.callback_query(F.data.startswith("depa:"))
    async def dep_create(callback) -> None:
        _, days_raw, amount_raw = callback.data.split(":")
        days = int(days_raw)
        amount = int(amount_raw)
        plan = next((item for item in game.DEPOSIT_PLANS if item["days"] == days), None)
        if not plan:
            await callback.answer("Неизвестный срок", show_alert=True)
            return
        user = get_user(callback)
        if user.get("is_banned"):
            await callback.answer("Аккаунт заблокирован.", show_alert=True)
            return
        if not (game.DEPOSIT_MIN <= amount <= game.DEPOSIT_MAX):
            await callback.answer(
                f"Сумма от {num(game.DEPOSIT_MIN)} до {num(game.DEPOSIT_MAX)}",
                show_alert=True)
            return
        if int(user["balance"]) < amount:
            await callback.answer("Недостаточно mCoin. Забери бонус: /bonus",
                                  show_alert=True)
            return
        now = int(time.time())
        ends = now + days * 86400
        interest = game.deposit_interest(amount, plan["rate_bps"])
        deposit_id = uuid.uuid4().hex[:12]
        db.add_balance(user["user_id"], -amount)
        db.create_deposit(deposit_id, user["user_id"], "fixed", amount,
                          plan["rate_bps"], now, ends)
        awards.evaluate(db, user["user_id"])
        fresh = db.user(user["user_id"])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Мои депозиты", callback_data="dep:mine")],
            [InlineKeyboardButton(text="🏦 В банк", callback_data="dep:main")],
        ])
        await safe_edit(
            callback.message,
            "✅ <b>Депозит открыт</b>\n\n"
            f"Сумма: {num(amount)} mCoin\n"
            f"Срок: {days} дн. — до {date_text(ends)}\n"
            f"Доход: +{num(interest)} mCoin ({pct(plan['rate_bps'] / 100)}%)\n"
            f"К закрытию: {num(amount + interest)} mCoin\n\n"
            f"💰 Баланс: {num(fresh['balance'])} mCoin",
            keyboard,
        )
        await callback.answer("Депозит открыт")

    @dp.callback_query(F.data == "dep:savings")
    async def dep_savings(callback) -> None:
        user = get_user(callback)
        await safe_edit(callback.message, savings_text(user),
                        savings_keyboard(user))
        await callback.answer()

    @dp.callback_query(F.data.startswith("savp:"))
    async def savings_put(callback) -> None:
        amount = int(callback.data.split(":")[1])
        user = get_user(callback)
        if user.get("is_banned"):
            await callback.answer("Аккаунт заблокирован.", show_alert=True)
            return
        if int(user["balance"]) < amount:
            await callback.answer("Недостаточно mCoin", show_alert=True)
            return
        now = int(time.time())
        savings = db.savings(user["user_id"])
        if savings:
            interest = game.savings_interest(savings["amount"], savings["rate_bps"],
                                             now - int(savings["started_at"]))
            if interest > 0:
                db.add_balance(user["user_id"], interest)
            db.update_savings(savings["id"], int(savings["amount"]) + amount, now)
        else:
            db.create_deposit(uuid.uuid4().hex[:12], user["user_id"], "savings",
                              amount, game.SAVINGS_RATE_BPS, now, None)
        db.add_balance(user["user_id"], -amount)
        awards.evaluate(db, user["user_id"])
        fresh = db.user(user["user_id"])
        await safe_edit(callback.message, savings_text(fresh),
                        savings_keyboard(fresh))
        await callback.answer(f"Пополнено на {num(amount)}")

    @dp.callback_query(F.data == "savw")
    async def savings_close(callback) -> None:
        user = get_user(callback)
        savings = db.savings(user["user_id"])
        if not savings:
            await callback.answer("Счёт пуст", show_alert=True)
            return
        now = int(time.time())
        interest = game.savings_interest(savings["amount"], savings["rate_bps"],
                                         now - int(savings["started_at"]))
        payout = int(savings["amount"]) + interest
        if not db.close_deposit(savings["id"], payout, now):
            await callback.answer("Счёт уже закрыт", show_alert=True)
            return
        db.add_balance(user["user_id"], payout)
        awards.evaluate(db, user["user_id"])
        balance = db.user(user["user_id"])["balance"]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🪙 Накопительный счёт",
                                  callback_data="dep:savings")],
            [InlineKeyboardButton(text="🏦 В банк", callback_data="dep:main")],
        ])
        await safe_edit(
            callback.message,
            "✅ <b>Счёт закрыт</b>\n\n"
            f"На счёте было: {num(savings['amount'])} mCoin\n"
            f"Проценты: +{num(interest)} mCoin\n"
            f"Выплачено: <b>{num(payout)}</b> mCoin\n"
            f"💰 Баланс: {num(balance)} mCoin",
            keyboard,
        )
        await callback.answer("Снято")

    @dp.callback_query(F.data == "dep:mine")
    async def dep_mine(callback) -> None:
        user = get_user(callback)
        text, keyboard = deposits_text(user)
        await safe_edit(callback.message, text, keyboard)
        await callback.answer()

    @dp.callback_query(F.data.startswith("depc:"))
    async def deposit_close(callback) -> None:
        deposit_id = callback.data.split(":", 1)[1]
        user = get_user(callback)
        row = db.deposit(deposit_id)
        if not row or int(row["user_id"]) != int(user["user_id"]) \
                or row["status"] != "active":
            await callback.answer("Депозит не найден", show_alert=True)
            return
        now = int(time.time())
        if row["kind"] == "fixed":
            ends = int(row["ends_at"] or 0)
            if now < ends:
                await callback.answer(
                    f"Депозит закроется {date_text(ends)}", show_alert=True)
                return
            payout = int(row["amount"]) + game.deposit_interest(
                row["amount"], row["rate_bps"])
        else:
            payout = int(row["amount"]) + game.savings_interest(
                row["amount"], row["rate_bps"], now - int(row["started_at"]))
        if not db.close_deposit(deposit_id, payout, now):
            await callback.answer("Депозит уже закрыт", show_alert=True)
            return
        db.add_balance(user["user_id"], payout)
        awards.evaluate(db, user["user_id"])
        balance = db.user(user["user_id"])["balance"]
        text, keyboard = deposits_text(db.user(user["user_id"]))
        await safe_edit(
            callback.message,
            f"✅ <b>Депозит закрыт</b>\n\n"
            f"Вложено: {num(row['amount'])} mCoin\n"
            f"Выплачено: <b>{num(payout)}</b> mCoin\n"
            f"💰 Баланс: {num(balance)} mCoin\n\n" + text,
            keyboard,
        )
        await callback.answer(f"+{num(payout)}")

    @dp.callback_query(F.data.startswith("depw:"))
    async def deposit_wait(callback) -> None:
        deposit_id = callback.data.split(":", 1)[1]
        row = db.deposit(deposit_id)
        if not row or row["status"] != "active":
            await callback.answer("Депозит не найден", show_alert=True)
            return
        ends = int(row["ends_at"] or 0)
        left = ends - int(time.time())
        await callback.answer(
            f"Закроется {date_text(ends)} — через {left_text(left)}",
            show_alert=True)

    @dp.callback_query(F.data.startswith("inv:"))
    async def invite_claim(callback) -> None:
        step = int(callback.data.split(":")[1])
        reward = next((int(item["reward"]) for item in game.REF_LADDER
                       if int(item["step"]) == step), None)
        if reward is None:
            await callback.answer("Неизвестная ступень", show_alert=True)
            return
        user = get_user(callback)
        refs = db.referrals(user["user_id"])
        if refs["total"] < step:
            await callback.answer("Не хватает приглашённых", show_alert=True)
            return
        if not db.invite_claim(user["user_id"], step):
            await callback.answer("Награда уже получена", show_alert=True)
            return
        db.add_balance(user["user_id"], reward)
        awards.evaluate(db, user["user_id"])
        text, keyboard = tasks_view(db.user(user["user_id"]))
        await safe_edit(callback.message, text, keyboard)
        await callback.answer(f"+{num(reward)} mCoin")

    @dp.callback_query(F.data.startswith("sp:"))
    async def sponsor_claim(callback) -> None:
        channel = callback.data.split(":", 1)[1]
        if channel not in config.sponsor_channels:
            await callback.answer("Неизвестный спонсор", show_alert=True)
            return
        user = get_user(callback)
        if user.get("is_banned"):
            await callback.answer("Аккаунт заблокирован.", show_alert=True)
            return
        if channel in db.sponsor_claims(user["user_id"]):
            await callback.answer("Награда уже получена", show_alert=True)
            return
        try:
            member = await callback.bot.get_chat_member(chat_id="@" + channel,
                                                        user_id=user["user_id"])
            status = getattr(member, "status", "")
        except Exception:
            await callback.answer(
                "Не удалось проверить подписку. Бот должен быть админом канала.",
                show_alert=True)
            return
        if status not in ("member", "administrator", "creator"):
            await callback.answer("Подписка не найдена. Подпишись и нажми снова.",
                                  show_alert=True)
            return
        if not db.sponsor_claim(user["user_id"], channel):
            await callback.answer("Награда уже получена", show_alert=True)
            return
        db.add_balance(user["user_id"], game.SPONSOR_REWARD)
        awards.evaluate(db, user["user_id"])
        text, keyboard = tasks_view(db.user(user["user_id"]))
        await safe_edit(callback.message, text, keyboard)
        await callback.answer(f"+{num(game.SPONSOR_REWARD)} mCoin")

    return dp


async def announce_update(bot: Bot, db: Database) -> None:
    try:
        current = str(db.settings().get("update_version", "0"))
        if current == updates.VERSION:
            return
        image_path = Path(__file__).with_name(updates.IMAGE)
        if not image_path.exists():
            return
        text = updates.full_text()
        long_text = len(text) > 1000
        caption = updates.short_text() if long_text else text
        if config.update_channel:
            channel = config.update_channel
            targets = [channel if channel.startswith("@") else "@" + channel]
        else:
            targets = db.broadcast_ids()
        sent = 0
        for target in targets:
            try:
                await bot.send_photo(target, str(image_path), caption=caption,
                                     parse_mode="HTML")
                if long_text:
                    await bot.send_message(target, text, parse_mode="HTML",
                                           disable_web_page_preview=True)
                sent += 1
            except Exception:
                continue
            await asyncio.sleep(0.05)
        if sent:
            db.set_settings({"update_version": updates.VERSION})
    except Exception:
        pass


async def setup_bot(bot: Bot) -> None:
    if config.public_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Играть", web_app=WebAppInfo(url=f"{config.public_url}/")))
    commands = [
        BotCommand(command="play", description="Открыть приложение"),
        BotCommand(command="mines", description="Сапёр в чате"),
        BotCommand(command="dice", description="Кости в чате"),
        BotCommand(command="roulette", description="Рулетка"),
        BotCommand(command="slots", description="Слоты"),
        BotCommand(command="crash", description="Краш"),
        BotCommand(command="coin", description="Орёл и решка"),
        BotCommand(command="basket", description="Баскет: бросок в кольцо"),
        BotCommand(command="pay", description="Перевод другому игроку"),
        BotCommand(command="promo", description="Активировать промокод"),
        BotCommand(command="updates", description="Что нового"),
        BotCommand(command="roles", description="Роли и права"),
        BotCommand(command="chatid", description="ID этого чата"),
        BotCommand(command="promo_new", description="Админ: создать промокод"),
        BotCommand(command="promo_list", description="Админ: список промокодов"),
        BotCommand(command="promo_post", description="Админ: промокод в канал"),
        BotCommand(command="promo_off", description="Админ: выключить промокод"),
        BotCommand(command="duel", description="Дуэль 1×1"),
        BotCommand(command="spin", description="Колесо дня"),
        BotCommand(command="bonus", description="Бонусы"),
        BotCommand(command="balance", description="Профиль и статистика"),
        BotCommand(command="deposit", description="Депозиты"),
        BotCommand(command="tasks", description="Задания"),
        BotCommand(command="achievements", description="Уровни и достижения"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="ref", description="Пригласить друга"),
        BotCommand(command="fair", description="Честность игры"),
        BotCommand(command="chat", description="Чат игроков"),
        BotCommand(command="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:
        pass
