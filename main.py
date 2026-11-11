import asyncio
import logging
import sys

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from api import build_app
from bot import announce_update, build_dispatcher, setup_bot
from config import config
from db import Database

RENEWAL_URL = "https://bot-hosting.net/a/d/00fbd02f-8933-48ef-8a68-4fa65fcdd56f"


async def renewal_loop(bot: Bot) -> None:
    log = logging.getLogger("saper.renewal")
    hours = max(6, config.renewal_remind_hours)
    while True:
        await asyncio.sleep(hours * 3600)
        if not config.admin_ids:
            continue
        text = (
            "⏰ <b>Продление хостинга</b>\n\n"
            "Бесплатный тариф Bot-Hosting требует ручного продления каждые 4 дня, "
            "иначе бот останавливается.\n\n"
            f"Продлить: {RENEWAL_URL}"
        )
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(admin_id, text, disable_web_page_preview=True)
            except Exception as exc:
                log.warning("Напоминание не доставлено %s: %s", admin_id, exc)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("saper")

    if not config.bot_token:
        log.error("BOT_TOKEN не задан. Скопируйте .env.example в .env и вставьте токен из @BotFather.")
        sys.exit(1)

    db = Database(config.db_path, config.database_url)
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(db)
    app = build_app(db)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    log.info("HTTP-сервер: http://%s:%s/", config.host, config.port)

    await setup_bot(bot)
    me = await bot.get_me()
    config.bot_username = me.username or ""
    log.info("Бот: @%s", config.bot_username)
    if config.public_url:
        log.info("Mini App URL: %s/", config.public_url)
    else:
        log.warning("PUBLIC_URL не задан — кнопка WebApp будет вести на заглушку.")

    reminder = asyncio.create_task(renewal_loop(bot))
    announcement = asyncio.create_task(announce_update(bot, db))
    try:
        await dp.start_polling(bot)
    finally:
        reminder.cancel()
        announcement.cancel()
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
