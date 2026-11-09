from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MenuButtonWebApp,
    WebAppInfo,
)

from config import config
from db import Database

WELCOME = (
    "💣 <b>Апрельский сапёр</b>\n\n"
    "Поле 5×5, до 24 мин. Открывай клетки, копи множитель и вовремя забирай выигрыш.\n\n"
    "• Баланс на старте — 1000 сапов\n"
    "• Ежедневный бонус — 500 сапов\n"
    "• За друга — 500 сапов, когда он сыграет 5 партий\n"
    "• Честность каждого раунда можно проверить по seed\n\n"
    "Жми «Играть» — и не наступи на мину."
)


def play_keyboard() -> InlineKeyboardMarkup:
    url = f"{config.public_url}/" if config.public_url else "https://example.com/"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="🏆 Топ игроков", callback_data="top")],
        [InlineKeyboardButton(text="🔐 Честность игры", callback_data="fair")],
    ])


def build_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        args = message.text.split(maxsplit=1)
        referrer = None
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referrer = int(args[1][4:])
            except ValueError:
                referrer = None
        user = db.ensure_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            referrer,
        )
        await message.answer(
            WELCOME + f"\n\nТвой баланс: <b>{user['balance']} сапов</b>",
            reply_markup=play_keyboard(),
        )

    @dp.message(Command("play"))
    async def play(message: Message) -> None:
        db.ensure_user(message.from_user.id, message.from_user.username,
                       message.from_user.first_name)
        await message.answer("Открывай мини-приложение 👇", reply_markup=play_keyboard())

    @dp.message(Command("balance"))
    async def balance(message: Message) -> None:
        user = db.ensure_user(message.from_user.id, message.from_user.username,
                              message.from_user.first_name)
        await message.answer(
            f"💰 Баланс: <b>{user['balance']} сапов</b>\n"
            f"🎯 Партий: {user['games_played']}, побед: {user['games_won']}\n"
            f"🔥 Лучший множитель: ×{user['best_multiplier']:.2f}"
        )

    @dp.message(Command("ref"))
    async def ref(message: Message) -> None:
        user = db.ensure_user(message.from_user.id, message.from_user.username,
                              message.from_user.first_name)
        me = await message.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user['user_id']}"
        stats = db.referrals(user["user_id"])
        await message.answer(
            f"👥 Приглашай друзей:\n<code>{link}</code>\n\n"
            f"Приглашено: {stats['total']}, активных: {stats['active']}\n"
            f"За каждого друга, сыгравшего 5 партий, — 500 сапов.",
            disable_web_page_preview=True,
        )

    @dp.message(Command("fair"))
    async def fair(message: Message) -> None:
        user = db.ensure_user(message.from_user.id, message.from_user.username,
                              message.from_user.first_name)
        await message.answer(
            "🔐 <b>Provably fair</b>\n\n"
            f"Хеш серверного seed:\n<code>{user['server_seed_hash']}</code>\n"
            f"Клиентский seed: <code>{user['client_seed']}</code>\n"
            f"Nonce: {user['nonce']}\n\n"
            "Позиции мин считаются как HMAC-SHA256(server_seed, client_seed:nonce:i). "
            "Сменить seed и увидеть старый можно в приложении на вкладке «Честность»."
        )

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        await message.answer(
            "<b>Команды</b>\n"
            "/play — открыть игру\n"
            "/balance — баланс и статистика\n"
            "/ref — реферальная ссылка\n"
            "/fair — данные для проверки честности\n\n"
            "Это развлекательная игра на виртуальные сапы. "
            "Реальные деньги не принимаются и не выводятся."
        )

    @dp.message(Command("admin"))
    async def admin_cmd(message: Message) -> None:
        if message.from_user.id not in config.admin_ids:
            await message.answer("Команда доступна только администратору.")
            return
        url = f"{config.public_url}/?admin=1" if config.public_url else "https://example.com/"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Открыть админку", web_app=WebAppInfo(url=url))],
        ])
        await message.answer(
            "<b>Админ-панель</b>\n\n"
            "• Игроки — поиск, начисление и списание сапов, бан\n"
            "• Сводка — оборот, выплаты, RTP, последние ставки\n"
            "• Настройки — лимиты ставки, число мин, бонус, техработы",
            reply_markup=keyboard,
        )

    @dp.callback_query(F.data == "top")
    async def top(callback) -> None:
        rows = db.leaderboard(10)
        lines = ["🏆 <b>Топ по балансу</b>\n"]
        for i, row in enumerate(rows, 1):
            name = row["username"] or row["first_name"] or f"id{row['user_id']}"
            lines.append(f"{i}. {name} — {row['balance']} сапов")
        if not rows:
            lines.append("Пока пусто")
        await callback.message.answer("\n".join(lines))
        await callback.answer()

    @dp.callback_query(F.data == "fair")
    async def fair_cb(callback) -> None:
        user = db.ensure_user(callback.from_user.id, callback.from_user.username,
                              callback.from_user.first_name)
        await callback.message.answer(
            f"Хеш seed: <code>{user['server_seed_hash']}</code>\n"
            f"Клиентский seed: <code>{user['client_seed']}</code>\n"
            f"Nonce: {user['nonce']}"
        )
        await callback.answer()

    return dp


async def setup_bot(bot: Bot) -> None:
    if config.public_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Играть", web_app=WebAppInfo(url=f"{config.public_url}/")))
