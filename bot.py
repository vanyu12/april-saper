import math
import time
import uuid

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
    "• /spin — колесо дня раз в 12 часов\n"
    "• /bonus — часовой и ежедневный бонусы\n"
    "• /deposit — вклады под процент\n\n"
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


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button()],
        [InlineKeyboardButton(text="💣 Сапёр в чате", callback_data="menu:mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="menu:dice")],
        [InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonus"),
         InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:balance"),
         InlineKeyboardButton(text="🏅 Достижения", callback_data="menu:ach")],
        [InlineKeyboardButton(text="🎯 Задания", callback_data="menu:tasks"),
         InlineKeyboardButton(text="🏆 Топ игроков", callback_data="top")],
        [InlineKeyboardButton(text="🎰 Игры", callback_data="menu:games"),
         InlineKeyboardButton(text="⚔️ Дуэли", callback_data="menu:duel")],
        [InlineKeyboardButton(text="🔐 Честность", callback_data="fair")],
    ])


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
        return bool(name) and name in config.admin_usernames

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
        db.add_balance(user["user_id"], extra)
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
        db.add_balance(user["user_id"], bonus)
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
        lines = ["🏅 <b>Достижения</b>",
                 f"⭐ Уровень {level['level']} — {level['title']}",
                 f"🎖 XP: {level['into']} / {level['need']}", ""]
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
            [InlineKeyboardButton(text="🏆 Топ", callback_data="top")],
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
                "/crash 100 2.5 — краш, цель от ×1,20 до ×10\n\n"
                "Результат считается из твоего seed — проверить можно /fair.")

    def games_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎡 Рулетка", callback_data="menu:roulette"),
             InlineKeyboardButton(text="🎰 Слоты", callback_data="menu:slots")],
            [InlineKeyboardButton(text="💥 Краш", callback_data="menu:crash")],
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
            "/duel 100 @username — дуэль 1×1 на бросок\n"
            "/spin — колесо дня раз в 12 часов\n\n"
            "<b>Баланс и бонусы</b>\n"
            "/balance — профиль и статистика\n"
            "/bonus — часовой и ежедневный бонусы\n"
            "/deposit — вклады под процент\n"
            "/tasks — приглашения и спонсоры\n"
            "/achievements — уровни и достижения\n"
            "/top — рейтинг игроков\n\n"
            "<b>Приложение</b>\n"
            "/play — полное поле, магазин и история\n"
            "/ref — ссылка для друзей\n"
            "/fair — проверка честности\n\n"
            "Валюта mCoin виртуальная: реальные деньги не принимаются и не выводятся.",
            reply_markup=main_keyboard(),
        )

    @dp.message(Command("admin"))
    async def admin_cmd(message: Message) -> None:
        user = get_user(message)
        if not is_admin(user):
            await message.answer("Команда доступна только администратору.")
            return
        url = f"{config.public_url}/?admin=1" if config.public_url else "https://example.com/"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Открыть админку", web_app=WebAppInfo(url=url))],
        ])
        await message.answer(
            "<b>Админ-панель</b>\n\n"
            "• Игроки — поиск, начисление и списание mCoin, выдача предметов, бан\n"
            "• Сводка — оборот, выплаты, RTP, статистика по играм\n"
            "• Настройки — лимиты ставки, число мин, бонус, игры, техработы",
            reply_markup=keyboard,
        )

    @dp.callback_query(F.data == "top")
    async def top_cb(callback) -> None:
        await callback.message.answer(top_text())
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
        BotCommand(command="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:
        pass
