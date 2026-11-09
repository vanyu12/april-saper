import asyncio
import logging
import sys

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from api import build_app
from bot import build_dispatcher, setup_bot
from config import config
from db import Database


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

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
