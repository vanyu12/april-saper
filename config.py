import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _id_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


def _name_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [chunk.strip().lstrip("@").lower() for chunk in raw.replace(";", ",").split(",")
            if chunk.strip()]


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
    port: int = _int("PORT", _int("SERVER_PORT", 8080))
    db_path: str = os.getenv("DB_PATH", _default_db_path())
    database_url: str = os.getenv("DATABASE_URL", "").strip()
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    dev_user_id: int = _int("DEV_USER_ID", 0)
    webapp_short_name: str = os.getenv("WEBAPP_SHORT_NAME", "play").strip()
    admin_ids: list[int] = field(default_factory=lambda: _id_list("ADMIN_IDS"))
    admin_usernames: list[str] = field(
        default_factory=lambda: _name_list("ADMIN_USERNAMES"))
    renewal_remind_hours: int = _int("RENEWAL_REMIND_HOURS", 96)
    sponsor_channels: list[str] = field(
        default_factory=lambda: _name_list("SPONSOR_CHANNELS"))
    update_channel: str = os.getenv("UPDATE_CHANNEL", "").strip()
    chat_url: str = (os.getenv("CHAT_URL", "").strip()
                     or "https://t.me/AprilMines")
    bot_username: str = ""


config = Config()
