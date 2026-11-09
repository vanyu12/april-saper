import asyncio
import logging
import os

from aiohttp import web

os.environ.setdefault("DEV_MODE", "1")
os.environ.setdefault("DEV_USER_ID", "1")

from api import build_app
from config import config
from db import Database


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    config.dev_mode = True
    db = Database(config.db_path, config.database_url)
    app = build_app(db)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    print(f"Dev-сервер: http://127.0.0.1:{config.port}/ (API без Telegram, пользователь id={config.dev_user_id})")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
