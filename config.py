import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _default_db_path() -> str:
    if os.name != "nt":
        for candidate in ("/app/data", "/data"):
            if os.path.isdir(candidate) and os.access(candidate, os.W_OK):
                return os.path.join(candidate, "saper.db")
    return "data/saper.db"


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    public_url: str = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _int("PORT", 8080)
    db_path: str = os.getenv("DB_PATH", _default_db_path())
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    dev_user_id: int = _int("DEV_USER_ID", 0)
    webapp_short_name: str = os.getenv("WEBAPP_SHORT_NAME", "play").strip()
    bot_username: str = ""


config = Config()
