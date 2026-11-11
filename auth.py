import hashlib
import hmac
import secrets


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=2 ** 14,
        r=8,
        p=1,
        dklen=64,
    )
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    if not password_hash or not salt:
        return False
    try:
        digest, _ = hash_password(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
