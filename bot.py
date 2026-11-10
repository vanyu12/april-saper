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
    "На старте — 1000 сапов. За друга, сыгравшего 5 партий, — 500 сапов.\n"
    "Сапы виртуальные: реальные деньги не принимаются и не выводятся."
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
         InlineKeyboardButton(text="🎯 Задания", callback_data="menu:tasks")],
        [InlineKeyboardButton(text="🏆 Топ игроков", callback_data="top"),
         InlineKeyboardButton(text="🔐 Честность", callback_data="fair")],
    ])


def play_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [webapp_button()],
        [InlineKeyboardButton(text="💣 Сапёр в чате", callback_data="menu:mines"),
         InlineKeyboardButton(text="🎲 Кости", callback_data="menu:dice")],
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
            return f"Ставка от {num(min_bet)} до {num(max_bet)} сапов."
        if int(user["balance"]) < bet:
            return "Недостаточно сапов. Забери бонус: /bonus"
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

    def referral_link(user_id: int) -> str:
        name = config.bot_username or "bot"
        return f"https://t.me/{name}?start=ref_{user_id}"

    def profile_text(user: dict) -> str:
        now = int(time.time())
        lost = max(0, int(user["total_wagered"]) - int(user["total_won"]))
        deposits_total = sum(int(row["amount"]) for row in db.deposits(user["user_id"]))
        lines = [
            "👤 <b>Профиль</b>",
            f"💰 Баланс: <b>{num(user['balance'])} сапов</b>",
            f"🎯 Партий: {user['games_played']} · побед: {user['games_won']}",
            f"📉 Проиграно: {num(lost)} сапов",
            f"🔥 Лучший множитель: ×{user['best_multiplier']:.2f}",
        ]
        place = db.rank(user["user_id"])
        if place:
            lines.append(f"🏆 Место в топе: #{place}")
        if deposits_total:
            lines.append(f"🏦 В депозитах: {num(deposits_total)} сапов")
        hourly_left = game.HOURLY_COOLDOWN - (now - int(user.get("last_hourly") or 0))
        spin_left = game.SPIN_COOLDOWN - (now - int(user.get("last_spin") or 0))
        lines.append("")
        lines.append("🎁 Часовой бонус: " + ("готов" if hourly_left <= 0
                                            else f"через {left_text(hourly_left)}"))
        lines.append("🎡 Колесо дня: " + ("готово" if spin_left <= 0
                                         else f"через {left_text(spin_left)}"))
        return "\n".join(lines)

    def profile_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Бонусы", callback_data="menu:bonus"),
             InlineKeyboardButton(text="🏦 Банк", callback_data="menu:bank")],
            [InlineKeyboardButton(text="🎯 Задания", callback_data="menu:tasks"),
             InlineKeyboardButton(text="🏆 Топ", callback_data="top")],
            [webapp_button()],
        ])

    def top_text() -> str:
        rows = db.leaderboard(10)
        lines = ["🏆 <b>Топ по балансу</b>", ""]
        medals = ("🥇", "🥈", "🥉")
        for index, row in enumerate(rows, 1):
            name = row["username"] or row["first_name"] or f"id{row['user_id']}"
            prefix = medals[index - 1] if index <= 3 else f"{index}."
            lines.append(f"{prefix} {name} — {num(row['balance'])} сапов")
        if not rows:
            lines.append("Пока пусто")
        return "\n".join(lines)

    def bank_text(user: dict) -> str:
        lines = [
            "🏦 <b>ДЕПОЗИТ БАНК</b>",
            f"Баланс: <b>{num(user['balance'])} сапов</b>",
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
            f"Минимальный вклад — {num(game.DEPOSIT_MIN)} сапов. "
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
                f"Сумма: от {num(game.DEPOSIT_MIN)} до {num(game.DEPOSIT_MAX)} сапов\n\n"
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
                f"На счёте: <b>{num(savings['amount'])} сапов</b>\n"
                f"Накоплено: +{num(accrued)} сапов\n"
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
                lines.append(f"✅ {num(row['amount'])} сапов — готов к закрытию, "
                             f"к выплате {num(total)}")
                rows.append([InlineKeyboardButton(
                    text=f"✅ Забрать {num(total)}", callback_data=f"depc:{row['id']}")])
            else:
                lines.append(f"🔒 {num(row['amount'])} сапов → {num(total)} "
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
                "где 100 — ставка, 5 — число мин.\n\n"
                f"Ставка: от {num(settings.get('min_bet', game.MIN_BET))} "
                f"до {num(settings.get('max_bet', game.MAX_BET))} сапов\n"
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
            [webapp_button("🎮 Полное поле в приложении")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def start_mines(user: dict, bet: int, mines: int):
        error = bet_error(user, bet, "mines")
        if error:
            return error, None
        settings = db.settings()
        min_mines = int(settings.get("min_mines", 1))
        max_mines = int(settings.get("max_mines", 24))
        if not (min_mines <= mines <= max_mines):
            return f"Число мин от {min_mines} до {max_mines}.", None
        if db.active_round(user["user_id"]):
            return "Сначала заверши текущую партию — нажми «Забрать» в её сообщении.", None
        nonce = db.bump_nonce(user["user_id"])
        positions = game.generate_mines(user["server_seed"], user["client_seed"],
                                        nonce, mines)
        round_id = uuid.uuid4().hex[:12]
        db.add_balance(user["user_id"], -bet)
        db.create_round(round_id, user["user_id"], bet, mines, positions,
                        user["server_seed"], user["client_seed"], nonce)
        return None, db.round(round_id)

    def mines_text(rnd: dict) -> str:
        opened = list(rnd["opened"])
        safe = game.CELLS - int(rnd["mines"])
        mult = float(rnd["multiplier"])
        lines = [
            f"💣 <b>Сапёр</b> · мин: {rnd['mines']}",
            f"Ставка: {num(rnd['bet'])} сапов",
            f"Открыто: {len(opened)} из {safe}",
            f"Множитель: ×{mult:.2f}",
        ]
        if opened:
            payout = game.payout_for(rnd["bet"], mult)
            lines.append(f"К выплате: <b>{num(payout)}</b> сапов")
        else:
            lines.append("К выплате: открой хотя бы одну клетку")
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
                 f"Ставка {num(rnd['bet'])} сапов потеряна."]
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} сапов.")
        lines += ["", f"Мины были на клетках: {mines}",
                  f"💰 Баланс: {num(balance)} сапов"]
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
        db.finish_stats(user["user_id"], bet, payout, multiplier or 1.0)
        db.claim_referral_bonus(user["user_id"])
        balance = db.user(user["user_id"])["balance"]
        pick_title = "чёт" if pick == "even" else "нечёт"
        lines = [f"🎲 Выпало: <b>{roll}</b> ({'чёт' if is_even else 'нечёт'})",
                 f"Ставка: {num(bet)} сапов на {pick_title}"]
        if win:
            lines.append(f"✅ Выигрыш: <b>+{num(payout)}</b> сапов")
        else:
            lines.append("❌ Мимо")
        if refund:
            lines.append(f"🛡 Страховка вернула {num(refund)} сапов")
        lines.append(f"💰 Баланс: <b>{num(balance)}</b> сапов")
        return "\n".join(lines)

    def dice_hint_text() -> str:
        settings = db.settings()
        return ("🎲 <b>Кости</b>\n\n"
                "Напиши: <code>/dice 100 чёт</code>\n"
                "Выплата — ×1,96 при победе.\n\n"
                f"Ставка: от {num(settings.get('min_bet', game.MIN_BET))} "
                f"до {num(settings.get('max_bet', game.MAX_BET))} сапов.\n\n"
                "Можно и кнопкой 👇")

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
            lines.append(f"{mark} {step} друзей — {num(reward)} сапов ({tail})")
        if config.sponsor_channels:
            done = db.sponsor_claims(user["user_id"])
            lines += ["", "<b>Спонсоры</b>"]
            for channel in config.sponsor_channels:
                if channel in done:
                    lines.append(f"✅ @{channel} — "
                                 f"{num(game.SPONSOR_REWARD)} сапов получено")
                    continue
                lines.append(f"🎁 @{channel} — {num(game.SPONSOR_REWARD)} сапов")
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
                lines.append(f"✅ Часовой: +{num(amount)} сапов")
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
                lines.append(f"✅ Ежедневный: +{num(amount)} сапов{suffix}")
        else:
            lines.append(f"⏳ Ежедневный: через {left_text(daily_left)}")

        if gained:
            fresh = db.user(user["user_id"])
            lines += ["", f"💰 Баланс: <b>{num(fresh['balance'])}</b> сапов"]
        else:
            lines += ["", "Пока нечего забирать — возвращайся позже."]
        return "\n".join(lines)

    def prize_title(prize: dict) -> str:
        if prize["kind"] == "coins":
            return f"+{num(prize['amount'])} сапов"
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
            WELCOME + f"\n\n💰 Твой баланс: <b>{num(user['balance'])} сапов</b>",
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
        user = get_user(message)
        error, rnd = start_mines(user, bet, mines)
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
        fresh = db.user(user["user_id"])
        await message.answer(
            "🎡 <b>Колесо дня</b>\n\n"
            f"Выпало: <b>{prize_title(prize)}</b>\n"
            f"День серии: {day}/{game.SPIN_STREAK_DAYS}\n"
            f"💰 Баланс: {num(fresh['balance'])} сапов\n\n"
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
            f"За каждого друга, сыгравшего 5 партий, — {game.REF_BONUS} сапов.\n"
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
            "/spin — колесо дня раз в 12 часов\n\n"
            "<b>Баланс и бонусы</b>\n"
            "/balance — профиль и статистика\n"
            "/bonus — часовой и ежедневный бонусы\n"
            "/deposit — вклады под процент\n"
            "/tasks — приглашения и спонсоры\n"
            "/top — рейтинг игроков\n\n"
            "<b>Приложение</b>\n"
            "/play — полное поле, магазин и история\n"
            "/ref — ссылка для друзей\n"
            "/fair — проверка честности\n\n"
            "Сапы виртуальные: реальные деньги не принимаются и не выводятся.",
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
            "• Игроки — поиск, начисление и списание сапов, выдача предметов, бан\n"
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
        _, bet_raw, mines_raw = callback.data.split(":")
        user = get_user(callback)
        error, rnd = start_mines(user, int(bet_raw), int(mines_raw))
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
            db.finish_stats(user["user_id"], rnd["bet"], 0, 0)
            refund = insurance_refund(user, rnd["bet"])
            db.claim_referral_bonus(user["user_id"])
            balance = db.user(user["user_id"])["balance"]
            await safe_edit(callback.message,
                            mines_lost_text(rnd, cell, refund, balance),
                            finished_keyboard())
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
            balance = db.add_balance(user["user_id"], payout)
            db.finish_stats(user["user_id"], rnd["bet"], payout, mult)
            db.claim_referral_bonus(user["user_id"])
            await safe_edit(
                callback.message,
                "🏆 <b>Поле очищено!</b>\n\n"
                f"Множитель: ×{mult:.2f}\n"
                f"Выплата: <b>+{num(payout)}</b> сапов\n"
                f"💰 Баланс: {num(balance)} сапов",
                finished_keyboard(),
            )
            await callback.answer(f"+{num(payout)}")
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
        payout = game.payout_for(rnd["bet"], mult)
        payout = charm_bonus(user, payout)
        payout = apply_relic(user, "mines", payout)
        db.update_round(round_id, rnd["opened"], mult, "cashed", payout)
        balance = db.add_balance(user["user_id"], payout)
        db.finish_stats(user["user_id"], rnd["bet"], payout, mult)
        db.claim_referral_bonus(user["user_id"])
        await safe_edit(
            callback.message,
            "💰 <b>Забрал!</b>\n\n"
            f"Множитель: ×{mult:.2f}\n"
            f"Выплата: <b>+{num(payout)}</b> сапов\n"
            f"💰 Баланс: {num(balance)} сапов",
            finished_keyboard(),
        )
        await callback.answer(f"+{num(payout)}")

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
            await callback.answer("Недостаточно сапов. Забери бонус: /bonus",
                                  show_alert=True)
            return
        now = int(time.time())
        ends = now + days * 86400
        interest = game.deposit_interest(amount, plan["rate_bps"])
        deposit_id = uuid.uuid4().hex[:12]
        db.add_balance(user["user_id"], -amount)
        db.create_deposit(deposit_id, user["user_id"], "fixed", amount,
                          plan["rate_bps"], now, ends)
        fresh = db.user(user["user_id"])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Мои депозиты", callback_data="dep:mine")],
            [InlineKeyboardButton(text="🏦 В банк", callback_data="dep:main")],
        ])
        await safe_edit(
            callback.message,
            "✅ <b>Депозит открыт</b>\n\n"
            f"Сумма: {num(amount)} сапов\n"
            f"Срок: {days} дн. — до {date_text(ends)}\n"
            f"Доход: +{num(interest)} сапов ({pct(plan['rate_bps'] / 100)}%)\n"
            f"К закрытию: {num(amount + interest)} сапов\n\n"
            f"💰 Баланс: {num(fresh['balance'])} сапов",
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
            await callback.answer("Недостаточно сапов", show_alert=True)
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
        balance = db.add_balance(user["user_id"], payout)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🪙 Накопительный счёт",
                                  callback_data="dep:savings")],
            [InlineKeyboardButton(text="🏦 В банк", callback_data="dep:main")],
        ])
        await safe_edit(
            callback.message,
            "✅ <b>Счёт закрыт</b>\n\n"
            f"На счёте было: {num(savings['amount'])} сапов\n"
            f"Проценты: +{num(interest)} сапов\n"
            f"Выплачено: <b>{num(payout)}</b> сапов\n"
            f"💰 Баланс: {num(balance)} сапов",
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
        balance = db.add_balance(user["user_id"], payout)
        text, keyboard = deposits_text(db.user(user["user_id"]))
        await safe_edit(
            callback.message,
            f"✅ <b>Депозит закрыт</b>\n\n"
            f"Вложено: {num(row['amount'])} сапов\n"
            f"Выплачено: <b>{num(payout)}</b> сапов\n"
            f"💰 Баланс: {num(balance)} сапов\n\n" + text,
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
        text, keyboard = tasks_view(db.user(user["user_id"]))
        await safe_edit(callback.message, text, keyboard)
        await callback.answer(f"+{num(reward)} сапов")

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
        text, keyboard = tasks_view(db.user(user["user_id"]))
        await safe_edit(callback.message, text, keyboard)
        await callback.answer(f"+{num(game.SPONSOR_REWARD)} сапов")

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
        BotCommand(command="spin", description="Колесо дня"),
        BotCommand(command="bonus", description="Бонусы"),
        BotCommand(command="balance", description="Профиль и статистика"),
        BotCommand(command="deposit", description="Депозиты"),
        BotCommand(command="tasks", description="Задания"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="ref", description="Пригласить друга"),
        BotCommand(command="fair", description="Честность игры"),
        BotCommand(command="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:
        pass
