import json
import os
import sqlite3
import threading
import time


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id          INTEGER PRIMARY KEY,
        username         TEXT,
        first_name       TEXT,
        balance          INTEGER NOT NULL DEFAULT 1000,
        created_at       INTEGER NOT NULL,
        games_played     INTEGER NOT NULL DEFAULT 0,
        games_won        INTEGER NOT NULL DEFAULT 0,
        total_wagered    INTEGER NOT NULL DEFAULT 0,
        total_won        INTEGER NOT NULL DEFAULT 0,
        best_multiplier  REAL NOT NULL DEFAULT 1.0,
        last_daily       INTEGER NOT NULL DEFAULT 0,
        server_seed      TEXT,
        server_seed_hash TEXT,
        client_seed      TEXT,
        nonce            INTEGER NOT NULL DEFAULT 0,
        referred_by      INTEGER,
        ref_paid         INTEGER NOT NULL DEFAULT 0,
        is_banned        INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rounds (
        id             TEXT PRIMARY KEY,
        user_id        INTEGER NOT NULL,
        bet            INTEGER NOT NULL,
        mines          INTEGER NOT NULL,
        mine_positions TEXT NOT NULL,
        opened         TEXT NOT NULL DEFAULT '[]',
        multiplier     REAL NOT NULL DEFAULT 1.0,
        status         TEXT NOT NULL DEFAULT 'active',
        payout         INTEGER NOT NULL DEFAULT 0,
        server_seed    TEXT NOT NULL,
        client_seed    TEXT NOT NULL,
        nonce          INTEGER NOT NULL,
        created_at     INTEGER NOT NULL,
        finished_at    INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rounds_user ON rounds(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rounds_status ON rounds(status)",
    """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]

DEFAULT_SETTINGS = {
    "min_bet": "10",
    "max_bet": "100000",
    "min_mines": "1",
    "max_mines": "24",
    "daily_bonus": "500",
    "maintenance": "0",
}


class Database:
    def __init__(self, path: str = "data/saper.db", dsn: str | None = None):
        self._lock = threading.RLock()
        self._dsn = (dsn if dsn is not None else os.getenv("DATABASE_URL", "")).strip()
        self.backend = "postgres" if self._dsn else "sqlite"

        if self.backend == "postgres":
            import psycopg
            from psycopg.rows import dict_row

            self._psycopg = psycopg
            self._conn = psycopg.connect(
                self._dsn, row_factory=dict_row, autocommit=True, connect_timeout=10)
            self._ph = "%s"
            for statement in SCHEMA_STATEMENTS:
                self._conn.execute(statement)
            self._migrate()
        else:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(";".join(SCHEMA_STATEMENTS))
            self._ph = "?"
            self._migrate()
            self._conn.commit()

    # --- low level -------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self._ph == "%s" else sql

    def _reconnect(self) -> None:
        self._conn = self._psycopg.connect(
            self._dsn, row_factory=self._dict_row_factory(), autocommit=True,
            connect_timeout=10)

    def _dict_row_factory(self):
        from psycopg.rows import dict_row

        return dict_row

    def _is_connection_error(self, exc: Exception) -> bool:
        if self.backend != "postgres":
            return False
        return isinstance(exc, (self._psycopg.OperationalError, self._psycopg.InterfaceError))

    def _query(self, sql: str, params: tuple = (), mode: str = "all"):
        with self._lock:
            for attempt in range(2):
                try:
                    cur = self._conn.execute(self._sql(sql), params)
                    if mode == "one":
                        row = cur.fetchone()
                        return dict(row) if row is not None else None
                    if mode == "all":
                        return [dict(r) for r in cur.fetchall()]
                    if self.backend == "sqlite":
                        self._conn.commit()
                    return cur.rowcount
                except Exception as exc:
                    if attempt == 1 or not self._is_connection_error(exc):
                        raise
                    self._reconnect()

    def _row(self, sql: str, params=()) -> dict | None:
        return self._query(sql, params, "one")

    def _rows(self, sql: str, params=()) -> list[dict]:
        return self._query(sql, params, "all")

    def _exec(self, sql: str, params=()) -> int:
        return self._query(sql, params, "exec")

    def _table_columns(self, table: str) -> set[str]:
        if self.backend == "postgres":
            rows = self._rows(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (table,))
            return {row["column_name"] for row in rows}
        rows = self._rows(f"PRAGMA table_info({table})")
        return {row["name"] for row in rows}

    def _migrate(self) -> None:
        if "is_banned" not in self._table_columns("users"):
            self._exec(
                "ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0")
        for key, value in DEFAULT_SETTINGS.items():
            self._exec(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO NOTHING",
                (key, value),
            )

    # --- users -----------------------------------------------------------
    def ensure_user(self, user_id: int, username: str | None, first_name: str | None,
                    referrer: int | None = None) -> dict:
        with self._lock:
            row = self._row("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if row:
                self._exec(
                    "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                    (username, first_name, user_id),
                )
                return self.user(user_id)
            now = int(time.time())
            import hashlib
            import secrets

            seed = secrets.token_hex(32)
            client_seed = secrets.token_hex(8)
            seed_hash = hashlib.sha256(seed.encode()).hexdigest()
            if referrer == user_id or (referrer and not self._row(
                    "SELECT 1 FROM users WHERE user_id = ?", (referrer,))):
                referrer = None
            self._exec(
                """INSERT INTO users (user_id, username, first_name, balance, created_at,
                       server_seed, server_seed_hash, client_seed, referred_by)
                   VALUES (?, ?, ?, 1000, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, now, seed, seed_hash, client_seed, referrer),
            )
            return self.user(user_id)

    def user(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def set_balance(self, user_id: int, balance: int) -> None:
        self._exec("UPDATE users SET balance = ? WHERE user_id = ?", (balance, user_id))

    def add_balance(self, user_id: int, delta: int) -> int:
        with self._lock:
            self._exec("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                       (delta, user_id))
            row = self._row("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            return row["balance"] if row else 0

    def bump_nonce(self, user_id: int) -> int:
        with self._lock:
            self._exec("UPDATE users SET nonce = nonce + 1 WHERE user_id = ?", (user_id,))
            row = self._row("SELECT nonce FROM users WHERE user_id = ?", (user_id,))
            return row["nonce"] if row else 0

    def set_client_seed(self, user_id: int, client_seed: str) -> None:
        self._exec("UPDATE users SET client_seed = ? WHERE user_id = ?",
                   (client_seed, user_id))

    def rotate_seed(self, user_id: int, new_server_seed: str, new_hash: str,
                    new_client_seed: str) -> None:
        self._exec(
            """UPDATE users SET server_seed = ?, server_seed_hash = ?, client_seed = ?,
                   nonce = 0 WHERE user_id = ?""",
            (new_server_seed, new_hash, new_client_seed, user_id),
        )

    # --- rounds ----------------------------------------------------------
    def create_round(self, round_id: str, user_id: int, bet: int, mines: int,
                     positions: list[int], server_seed: str, client_seed: str,
                     nonce: int) -> None:
        self._exec(
            """INSERT INTO rounds (id, user_id, bet, mines, mine_positions, opened,
                   multiplier, status, payout, server_seed, client_seed, nonce, created_at)
               VALUES (?, ?, ?, ?, ?, '[]', 1.0, 'active', 0, ?, ?, ?, ?)""",
            (round_id, user_id, bet, mines, json.dumps(positions), server_seed,
             client_seed, nonce, int(time.time())),
        )

    def round(self, round_id: str) -> dict | None:
        row = self._row("SELECT * FROM rounds WHERE id = ?", (round_id,))
        return self._hydrate(row)

    def active_round(self, user_id: int) -> dict | None:
        row = self._row(
            "SELECT * FROM rounds WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1", (user_id,))
        return self._hydrate(row)

    @staticmethod
    def _hydrate(row: dict | None) -> dict | None:
        if not row:
            return None
        row["mine_positions"] = json.loads(row["mine_positions"])
        row["opened"] = json.loads(row["opened"])
        return row

    def update_round(self, round_id: str, opened: list[int], multiplier: float,
                     status: str, payout: int) -> None:
        finished = int(time.time()) if status != "active" else None
        self._exec(
            """UPDATE rounds SET opened = ?, multiplier = ?, status = ?, payout = ?,
                   finished_at = ? WHERE id = ?""",
            (json.dumps(opened), multiplier, status, payout, finished, round_id),
        )

    def finish_stats(self, user_id: int, bet: int, won: int, multiplier: float) -> None:
        best = "GREATEST(best_multiplier, ?)" if self.backend == "postgres" \
            else "MAX(best_multiplier, ?)"
        self._exec(
            f"""UPDATE users SET games_played = games_played + 1,
                   games_won = games_won + ?,
                   total_wagered = total_wagered + ?,
                   total_won = total_won + ?,
                   best_multiplier = {best}
               WHERE user_id = ?""",
            (1 if won > 0 else 0, bet, won, multiplier, user_id),
        )

    def history(self, user_id: int, limit: int = 20) -> list[dict]:
        return self._rows(
            """SELECT id, bet, mines, opened, multiplier, status, payout, created_at
               FROM rounds WHERE user_id = ? AND status != 'active'
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        )

    def leaderboard(self, limit: int = 20) -> list[dict]:
        return self._rows(
            """SELECT user_id, username, first_name, balance, best_multiplier, games_played
               FROM users ORDER BY balance DESC LIMIT ?""",
            (limit,),
        )

    def top_multiplier(self, limit: int = 10) -> list[dict]:
        return self._rows(
            """SELECT user_id, username, first_name, best_multiplier
               FROM users WHERE best_multiplier > 1.0
               ORDER BY best_multiplier DESC LIMIT ?""",
            (limit,),
        )

    def rank(self, user_id: int) -> int:
        me = self.user(user_id)
        if not me:
            return 0
        row = self._row(
            "SELECT COUNT(*) AS c FROM users WHERE balance > ?", (me["balance"],))
        return (row["c"] + 1) if row else 1

    def referrals(self, user_id: int) -> dict:
        total = self._row("SELECT COUNT(*) AS c FROM users WHERE referred_by = ?",
                          (user_id,))
        active = self._row(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by = ? AND games_played >= 5",
            (user_id,))
        paid = self._row(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by = ? AND ref_paid = 1",
            (user_id,))
        return {
            "total": total["c"] if total else 0,
            "active": active["c"] if active else 0,
            "paid": paid["c"] if paid else 0,
        }

    def claim_referral_bonus(self, user_id: int) -> int | None:
        with self._lock:
            me = self.user(user_id)
            if not me or not me["referred_by"] or me["ref_paid"]:
                return None
            if me["games_played"] < 5:
                return None
            self._exec("UPDATE users SET ref_paid = 1 WHERE user_id = ?", (user_id,))
            self.add_balance(me["referred_by"], 500)
            return me["referred_by"]

    # --- settings --------------------------------------------------------
    def settings(self) -> dict:
        values = dict(DEFAULT_SETTINGS)
        for row in self._rows("SELECT key, value FROM settings"):
            values[row["key"]] = row["value"]
        result = {}
        for key, raw in values.items():
            try:
                result[key] = int(raw)
            except (TypeError, ValueError):
                result[key] = raw
        return result

    def set_settings(self, updates: dict) -> dict:
        with self._lock:
            for key, value in updates.items():
                if key not in DEFAULT_SETTINGS:
                    continue
                self._exec("UPDATE settings SET value = ? WHERE key = ?", (str(value), key))
        return self.settings()

    # --- admin -----------------------------------------------------------
    ADMIN_USER_FIELDS = (
        "user_id, username, first_name, balance, games_played, games_won, "
        "total_wagered, total_won, best_multiplier, is_banned, created_at"
    )

    def admin_users(self, query: str = "", limit: int = 20) -> list[dict]:
        where: list[str] = []
        params: list = []
        q = (query or "").strip()
        if q:
            digits = q.lstrip("-")
            if digits.isdigit():
                where.append("user_id = ?")
                params.append(int(q))
            like = f"%{q}%"
            where.append("(username LIKE ? OR first_name LIKE ?)")
            params.extend([like, like])
        sql = f"SELECT {self.ADMIN_USER_FIELDS} FROM users"
        if where:
            sql += " WHERE " + " OR ".join(where)
        sql += " ORDER BY balance DESC LIMIT ?"
        params.append(int(limit))
        return self._rows(sql, tuple(params))

    def admin_set_balance(self, user_id: int, value: int) -> int:
        with self._lock:
            self._exec("UPDATE users SET balance = ? WHERE user_id = ?",
                       (max(0, int(value)), user_id))
            row = self._row("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            return row["balance"] if row else 0

    def admin_set_ban(self, user_id: int, banned: bool) -> None:
        self._exec("UPDATE users SET is_banned = ? WHERE user_id = ?",
                   (1 if banned else 0, user_id))

    def admin_stats(self) -> dict:
        now = int(time.time())
        day_start = now - (now % 86400)
        users = self._row("SELECT COUNT(*) AS c FROM users")
        banned = self._row("SELECT COUNT(*) AS c FROM users WHERE is_banned = 1")
        rounds = self._row("SELECT COUNT(*) AS c FROM rounds WHERE status != 'active'")
        active = self._row("SELECT COUNT(*) AS c FROM rounds WHERE status = 'active'")
        totals = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COALESCE(SUM(CASE WHEN payout > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM rounds WHERE status != 'active'""")
        today = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COUNT(*) AS rounds
               FROM rounds WHERE status != 'active' AND created_at >= ?""",
            (day_start,))
        balances = self._row("SELECT COALESCE(SUM(balance), 0) AS s FROM users")
        best = self._row(
            """SELECT r.id, r.user_id, u.username, u.first_name, r.bet, r.payout,
                      r.multiplier, r.mines
               FROM rounds r LEFT JOIN users u ON u.user_id = r.user_id
               WHERE r.status != 'active' ORDER BY r.payout DESC LIMIT 1""")
        wagered = totals["wagered"] if totals else 0
        paid = totals["paid"] if totals else 0
        rtp = round((paid / wagered) * 100, 2) if wagered else 0.0
        return {
            "users": users["c"] if users else 0,
            "banned": banned["c"] if banned else 0,
            "rounds": rounds["c"] if rounds else 0,
            "active_rounds": active["c"] if active else 0,
            "wagered": wagered,
            "paid": paid,
            "profit": wagered - paid,
            "rtp": rtp,
            "wins": totals["wins"] if totals else 0,
            "balances": balances["s"] if balances else 0,
            "today": {
                "wagered": today["wagered"] if today else 0,
                "paid": today["paid"] if today else 0,
                "rounds": today["rounds"] if today else 0,
            },
            "best_round": best,
        }

    def admin_rounds(self, user_id: int | None = None, limit: int = 20) -> list[dict]:
        sql = (
            "SELECT r.id, r.user_id, u.username, u.first_name, r.bet, r.mines, r.opened, "
            "r.multiplier, r.status, r.payout, r.created_at "
            "FROM rounds r LEFT JOIN users u ON u.user_id = r.user_id"
        )
        params: list = []
        if user_id:
            sql += " WHERE r.user_id = ?"
            params.append(user_id)
        sql += " ORDER BY r.created_at DESC LIMIT ?"
        params.append(int(limit))
        return self._rows(sql, tuple(params))
