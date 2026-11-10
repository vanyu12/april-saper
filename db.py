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
        is_banned        INTEGER NOT NULL DEFAULT 0,
        photo_url        TEXT NOT NULL DEFAULT '',
        last_hourly      INTEGER NOT NULL DEFAULT 0,
        last_spin        INTEGER NOT NULL DEFAULT 0,
        spin_day         INTEGER NOT NULL DEFAULT 1,
        xp               INTEGER NOT NULL DEFAULT 0,
        duels_played     INTEGER NOT NULL DEFAULT 0,
        duels_won        INTEGER NOT NULL DEFAULT 0
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
        auto_target    REAL NOT NULL DEFAULT 0,
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
    """
    CREATE TABLE IF NOT EXISTS plays (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        game       TEXT NOT NULL,
        bet        INTEGER NOT NULL,
        win        INTEGER NOT NULL DEFAULT 0,
        payout     INTEGER NOT NULL DEFAULT 0,
        detail     TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_plays_user ON plays(user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS quest_claims (
        user_id    INTEGER NOT NULL,
        day        TEXT NOT NULL,
        quest      TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, day, quest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER NOT NULL,
        item    TEXT NOT NULL,
        qty     INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, item)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deposits (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        kind       TEXT NOT NULL DEFAULT 'fixed',
        amount     INTEGER NOT NULL,
        rate_bps   INTEGER NOT NULL,
        started_at INTEGER NOT NULL,
        ends_at    INTEGER,
        status     TEXT NOT NULL DEFAULT 'active',
        payout     INTEGER NOT NULL DEFAULT 0,
        closed_at  INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS invite_claims (
        user_id    INTEGER NOT NULL,
        step       INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, step)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sponsor_claims (
        user_id    INTEGER NOT NULL,
        channel    TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, channel)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_achievements (
        user_id    INTEGER NOT NULL,
        key        TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS duels (
        id              TEXT PRIMARY KEY,
        challenger_id   INTEGER NOT NULL,
        opponent_id     INTEGER NOT NULL,
        bet             INTEGER NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',
        challenger_roll INTEGER,
        opponent_roll   INTEGER,
        winner_id       INTEGER,
        rake            INTEGER NOT NULL DEFAULT 0,
        created_at      INTEGER NOT NULL,
        finished_at     INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_duels_status ON duels(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_duels_users ON duels(challenger_id, opponent_id)",
]

DEFAULT_SETTINGS = {
    "min_bet": "10",
    "max_bet": "100000",
    "min_mines": "1",
    "max_mines": "24",
    "daily_bonus": "300",
    "maintenance": "0",
    "game_mines": "1",
    "game_dice": "1",
    "game_wheel": "1",
    "game_crash": "1",
    "game_roulette": "1",
    "game_slots": "1",
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

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

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
        present = self._table_columns("users")
        for name, ddl in (
            ("photo_url", "TEXT NOT NULL DEFAULT ''"),
            ("last_hourly", "INTEGER NOT NULL DEFAULT 0"),
            ("last_spin", "INTEGER NOT NULL DEFAULT 0"),
            ("spin_day", "INTEGER NOT NULL DEFAULT 1"),
            ("xp", "INTEGER NOT NULL DEFAULT 0"),
            ("duels_played", "INTEGER NOT NULL DEFAULT 0"),
            ("duels_won", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in present:
                self._exec(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        if "auto_target" not in self._table_columns("rounds"):
            self._exec(
                "ALTER TABLE rounds ADD COLUMN auto_target REAL NOT NULL DEFAULT 0")
        for key, value in DEFAULT_SETTINGS.items():
            self._exec(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO NOTHING",
                (key, value),
            )
        marker = self._row("SELECT value FROM settings WHERE key = 'economy_version'")
        if not marker:
            self._exec(
                "UPDATE settings SET value = ? WHERE key = 'daily_bonus' AND value = '500'",
                ("300",))
            self._exec(
                "INSERT INTO settings (key, value) VALUES ('economy_version', '1') "
                "ON CONFLICT (key) DO NOTHING")

    # --- users -----------------------------------------------------------
    def ensure_user(self, user_id: int, username: str | None, first_name: str | None,
                    referrer: int | None = None, photo_url: str | None = None) -> dict:
        with self._lock:
            row = self._row("SELECT * FROM users WHERE user_id = ?", (user_id,))
            if row:
                self._exec(
                    "UPDATE users SET username = ?, first_name = ?, "
                    "photo_url = COALESCE(?, photo_url) WHERE user_id = ?",
                    (username, first_name, photo_url, user_id),
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
                       server_seed, server_seed_hash, client_seed, referred_by, photo_url)
                   VALUES (?, ?, ?, 1000, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, now, seed, seed_hash, client_seed,
                 referrer, photo_url or ""),
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

    def add_xp(self, user_id: int, amount: int) -> int:
        with self._lock:
            self._exec("UPDATE users SET xp = xp + ? WHERE user_id = ?",
                       (int(amount), user_id))
            row = self._row("SELECT xp FROM users WHERE user_id = ?", (user_id,))
            return int(row["xp"]) if row else 0

    def user_achievements(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT key FROM user_achievements WHERE user_id = ?",
                          (user_id,))
        return {row["key"] for row in rows}

    def claim_achievement(self, user_id: int, key: str) -> bool:
        changed = self._exec(
            "INSERT INTO user_achievements (user_id, key, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, key) DO NOTHING",
            (user_id, key, int(time.time())))
        return bool(changed)

    def count_deposits(self, user_id: int) -> int:
        row = self._row("SELECT COUNT(*) AS c FROM deposits WHERE user_id = ?",
                        (user_id,))
        return int(row["c"]) if row else 0

    # --- дуэли -----------------------------------------------------------
    def user_by_username(self, username: str) -> dict | None:
        name = (username or "").lstrip("@").strip()
        if not name:
            return None
        return self._row("SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
                         (name,))

    def create_duel(self, duel_id: str, challenger_id: int, opponent_id: int,
                    bet: int, now: int) -> None:
        self._exec(
            """INSERT INTO duels (id, challenger_id, opponent_id, bet, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (duel_id, challenger_id, opponent_id, bet, now))

    def duel(self, duel_id: str) -> dict | None:
        return self._row("SELECT * FROM duels WHERE id = ?", (duel_id,))

    def pending_duel_for(self, user_id: int) -> dict | None:
        return self._row(
            """SELECT * FROM duels WHERE status = 'pending'
               AND (challenger_id = ? OR opponent_id = ?)
               ORDER BY created_at DESC LIMIT 1""", (user_id, user_id))

    def close_duel(self, duel_id: str, status: str, now: int) -> bool:
        changed = self._exec(
            "UPDATE duels SET status = ?, finished_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, now, duel_id))
        return bool(changed)

    def finish_duel(self, duel_id: str, challenger_roll: int, opponent_roll: int,
                    winner_id: int | None, rake: int, now: int) -> bool:
        changed = self._exec(
            """UPDATE duels SET status = 'finished', challenger_roll = ?,
                   opponent_roll = ?, winner_id = ?, rake = ?, finished_at = ?
               WHERE id = ? AND status = 'pending'""",
            (challenger_roll, opponent_roll, winner_id, rake, now, duel_id))
        return bool(changed)

    def add_duel_stats(self, user_id: int, won: bool) -> None:
        self._exec(
            "UPDATE users SET duels_played = duels_played + 1, "
            "duels_won = duels_won + ? WHERE user_id = ?",
            (1 if won else 0, user_id))

    def top_duelists(self, limit: int = 10) -> list[dict]:
        return self._rows(
            """SELECT user_id, username, first_name, photo_url, duels_played, duels_won
               FROM users WHERE duels_played > 0
               ORDER BY duels_won DESC, duels_played ASC, user_id LIMIT ?""",
            (int(limit),))

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
                     nonce: int, auto_target: float = 0) -> None:
        self._exec(
            """INSERT INTO rounds (id, user_id, bet, mines, mine_positions, opened,
                   multiplier, status, payout, server_seed, client_seed, nonce,
                   auto_target, created_at)
               VALUES (?, ?, ?, ?, ?, '[]', 1.0, 'active', 0, ?, ?, ?, ?, ?)""",
            (round_id, user_id, bet, mines, json.dumps(positions), server_seed,
             client_seed, nonce, float(auto_target or 0), int(time.time())),
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
            """SELECT user_id, username, first_name, photo_url, balance,
                      best_multiplier, games_played
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

    # --- бонусы и колесо -------------------------------------------------
    def claim_hourly(self, user_id: int, now: int, cooldown: int, amount: int) -> int | None:
        with self._lock:
            me = self.user(user_id)
            if not me or now - int(me["last_hourly"]) < cooldown:
                return None
            self._exec(
                "UPDATE users SET last_hourly = ?, balance = balance + ? WHERE user_id = ?",
                (now, amount, user_id))
            return amount

    def claim_daily(self, user_id: int, now: int, cooldown: int, amount: int) -> int | None:
        with self._lock:
            me = self.user(user_id)
            if not me or now - int(me["last_daily"]) < cooldown:
                return None
            self._exec("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user_id))
            return amount

    def mark_spin(self, user_id: int, now: int, spin_day: int) -> None:
        self._exec("UPDATE users SET last_spin = ?, spin_day = ? WHERE user_id = ?",
                   (now, spin_day, user_id))

    # --- приглашения -----------------------------------------------------
    def invite_claim(self, user_id: int, step: int) -> bool:
        changed = self._exec(
            "INSERT INTO invite_claims (user_id, step, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, step) DO NOTHING",
            (user_id, step, int(time.time())))
        return bool(changed)

    def invite_claims(self, user_id: int) -> set[int]:
        rows = self._rows("SELECT step FROM invite_claims WHERE user_id = ?", (user_id,))
        return {int(row["step"]) for row in rows}

    # --- спонсоры --------------------------------------------------------
    def sponsor_claim(self, user_id: int, channel: str) -> bool:
        changed = self._exec(
            "INSERT INTO sponsor_claims (user_id, channel, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, channel) DO NOTHING",
            (user_id, channel, int(time.time())))
        return bool(changed)

    def sponsor_claims(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT channel FROM sponsor_claims WHERE user_id = ?",
                          (user_id,))
        return {row["channel"] for row in rows}

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
        mine_totals = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COALESCE(SUM(CASE WHEN payout > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM rounds WHERE status != 'active'""")
        play_totals = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins,
                      COUNT(*) AS c
               FROM plays""")
        mine_today = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COUNT(*) AS c
               FROM rounds WHERE status != 'active' AND created_at >= ?""",
            (day_start,))
        play_today = self._row(
            """SELECT COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COUNT(*) AS c
               FROM plays WHERE created_at >= ?""",
            (day_start,))
        balances = self._row("SELECT COALESCE(SUM(balance), 0) AS s FROM users")
        best = self._row(
            """SELECT r.id, r.user_id, u.username, u.first_name, r.bet, r.payout,
                      r.multiplier, r.mines
               FROM rounds r LEFT JOIN users u ON u.user_id = r.user_id
               WHERE r.status != 'active' ORDER BY r.payout DESC LIMIT 1""")

        def total(row, key):
            return row[key] if row and row.get(key) is not None else 0

        wagered = total(mine_totals, "wagered") + total(play_totals, "wagered")
        paid = total(mine_totals, "paid") + total(play_totals, "paid")
        wins = total(mine_totals, "wins") + total(play_totals, "wins")
        round_count = total(rounds, "c") + total(play_totals, "c")
        rtp = round((paid / wagered) * 100, 2) if wagered else 0.0
        return {
            "users": total(users, "c"),
            "banned": total(banned, "c"),
            "rounds": round_count,
            "active_rounds": total(active, "c"),
            "wagered": wagered,
            "paid": paid,
            "profit": wagered - paid,
            "rtp": rtp,
            "wins": wins,
            "balances": total(balances, "s"),
            "today": {
                "wagered": total(mine_today, "wagered") + total(play_today, "wagered"),
                "paid": total(mine_today, "paid") + total(play_today, "paid"),
                "rounds": total(mine_today, "c") + total(play_today, "c"),
            },
            "best_round": best,
        }

    def admin_recent(self, limit: int = 12) -> list[dict]:
        rounds = self._rows(
            """SELECT r.id, r.user_id, u.username, u.first_name, r.bet, r.multiplier,
                      r.status, r.payout, r.mines, r.created_at
               FROM rounds r LEFT JOIN users u ON u.user_id = r.user_id
               WHERE r.status != 'active'
               ORDER BY r.created_at DESC LIMIT ?""",
            (int(limit),))
        plays = self._rows(
            """SELECT p.id, p.user_id, u.username, u.first_name, p.bet, p.game,
                      p.win, p.payout, p.created_at
               FROM plays p LEFT JOIN users u ON u.user_id = p.user_id
               ORDER BY p.created_at DESC, p.id DESC LIMIT ?""",
            (int(limit),))
        items: list[dict] = []
        for row in rounds:
            item = dict(row)
            item["label"] = f"{row['mines']} мин"
            items.append(item)
        names = {"dice": "Кости", "wheel": "Колесо"}
        for row in plays:
            item = dict(row)
            item["label"] = names.get(row["game"], row["game"])
            item["multiplier"] = 0.0
            item["status"] = "win" if row["win"] else "lose"
            items.append(item)
        items.sort(key=lambda entry: entry["created_at"], reverse=True)
        return items[: int(limit)]

    GAME_TITLES = {"mines": "Сапёр", "dice": "Кости", "wheel": "Колесо", "crash": "Краш"}

    def admin_game_stats(self) -> list[dict]:
        rows: list[dict] = []
        mines = self._row(
            """SELECT COUNT(*) AS rounds, COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COALESCE(SUM(CASE WHEN payout > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM rounds WHERE status != 'active'""")
        if mines:
            rows.append({
                "game": "mines", "title": "Сапёр",
                "rounds": mines["rounds"], "wagered": mines["wagered"],
                "paid": mines["paid"], "wins": mines["wins"],
            })
        for row in self._rows(
                """SELECT game, COUNT(*) AS rounds, COALESCE(SUM(bet), 0) AS wagered,
                          COALESCE(SUM(payout), 0) AS paid,
                          COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins
                   FROM plays GROUP BY game"""):
            rows.append({
                "game": row["game"],
                "title": self.GAME_TITLES.get(row["game"], row["game"]),
                "rounds": row["rounds"], "wagered": row["wagered"],
                "paid": row["paid"], "wins": row["wins"],
            })
        for row in rows:
            wagered = row["wagered"] or 0
            row["rtp"] = round((row["paid"] / wagered) * 100, 2) if wagered else 0.0
        order = ["mines", "dice", "wheel", "crash"]
        rows.sort(key=lambda item: order.index(item["game"]) if item["game"] in order else 99)
        return rows

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

    # --- other games -----------------------------------------------------
    def add_play(self, play_id: str, user_id: int, game_name: str, bet: int,
                 win: bool, payout: int, detail: dict) -> None:
        self._exec(
            """INSERT INTO plays (id, user_id, game, bet, win, payout, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (play_id, user_id, game_name, bet, 1 if win else 0, payout,
             json.dumps(detail, ensure_ascii=False), int(time.time())),
        )

    def plays(self, user_id: int, limit: int = 20) -> list[dict]:
        return self._rows(
            """SELECT id, game, bet, win, payout, detail, created_at FROM plays
               WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?""",
            (user_id, int(limit)),
        )

    def day_stats(self, user_id: int, since: int) -> dict:
        rounds = self._row(
            """SELECT COUNT(*) AS games,
                      COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS won,
                      COALESCE(SUM(CASE WHEN payout > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM rounds WHERE user_id = ? AND status != 'active' AND created_at >= ?""",
            (user_id, since))
        plays = self._row(
            """SELECT COUNT(*) AS games,
                      COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS won,
                      COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins
               FROM plays WHERE user_id = ? AND created_at >= ?""",
            (user_id, since))
        return {
            "games": (rounds["games"] if rounds else 0) + (plays["games"] if plays else 0),
            "wins": (rounds["wins"] if rounds else 0) + (plays["wins"] if plays else 0),
            "wagered": (rounds["wagered"] if rounds else 0) + (plays["wagered"] if plays else 0),
            "won": (rounds["won"] if rounds else 0) + (plays["won"] if plays else 0),
        }

    def claimed_quests(self, user_id: int, day: str) -> set[str]:
        rows = self._rows(
            "SELECT quest FROM quest_claims WHERE user_id = ? AND day = ?", (user_id, day))
        return {row["quest"] for row in rows}

    def claim_quest(self, user_id: int, day: str, quest: str) -> bool:
        changed = self._exec(
            """INSERT INTO quest_claims (user_id, day, quest, created_at)
               VALUES (?, ?, ?, ?) ON CONFLICT (user_id, day, quest) DO NOTHING""",
            (user_id, day, quest, int(time.time())),
        )
        return bool(changed)

    # --- инвентарь -------------------------------------------------------
    def item_qty(self, user_id: int, item: str) -> int:
        row = self._row("SELECT qty FROM inventory WHERE user_id = ? AND item = ?",
                        (user_id, item))
        return row["qty"] if row else 0

    def add_item(self, user_id: int, item: str, qty: int = 1) -> int:
        if qty <= 0:
            return self.item_qty(user_id, item)
        if self.backend == "postgres":
            self._exec(
                """INSERT INTO inventory (user_id, item, qty) VALUES (?, ?, ?)
                   ON CONFLICT (user_id, item)
                   DO UPDATE SET qty = inventory.qty + ?""",
                (user_id, item, qty, qty),
            )
        else:
            self._exec(
                """INSERT INTO inventory (user_id, item, qty) VALUES (?, ?, ?)
                   ON CONFLICT (user_id, item) DO UPDATE SET qty = qty + ?""",
                (user_id, item, qty, qty),
            )
        return self.item_qty(user_id, item)

    def take_item(self, user_id: int, item: str, qty: int = 1) -> bool:
        with self._lock:
            if self.item_qty(user_id, item) < qty:
                return False
            self._exec("UPDATE inventory SET qty = qty - ? WHERE user_id = ? AND item = ?",
                       (qty, user_id, item))
            return True

    def inventory(self, user_id: int) -> dict:
        rows = self._rows("SELECT item, qty FROM inventory WHERE user_id = ?", (user_id,))
        return {row["item"]: row["qty"] for row in rows if row["qty"] > 0}

    # --- депозиты --------------------------------------------------------
    def deposit(self, dep_id: str) -> dict | None:
        return self._row("SELECT * FROM deposits WHERE id = ?", (dep_id,))

    def deposits(self, user_id: int, status: str = "active") -> list[dict]:
        return self._rows(
            "SELECT * FROM deposits WHERE user_id = ? AND status = ? "
            "ORDER BY started_at DESC", (user_id, status))

    def create_deposit(self, dep_id: str, user_id: int, kind: str, amount: int,
                       rate_bps: int, now: int, ends_at: int | None) -> None:
        self._exec(
            """INSERT INTO deposits (id, user_id, kind, amount, rate_bps, started_at,
                   ends_at, status, payout, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, NULL)""",
            (dep_id, user_id, kind, amount, rate_bps, now, ends_at))

    def savings(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM deposits WHERE user_id = ? AND kind = 'savings' "
            "AND status = 'active' LIMIT 1", (user_id,))

    def update_savings(self, dep_id: str, amount: int, started_at: int) -> None:
        self._exec("UPDATE deposits SET amount = ?, started_at = ? WHERE id = ?",
                   (amount, started_at, dep_id))

    def close_deposit(self, dep_id: str, payout: int, now: int) -> bool:
        changed = self._exec(
            """UPDATE deposits SET status = 'closed', payout = ?, closed_at = ?
               WHERE id = ? AND status = 'active'""",
            (payout, now, dep_id))
        return bool(changed)

    # --- хаб игр ---------------------------------------------------------
    def game_players(self) -> dict[str, int]:
        rows = self._rows(
            "SELECT game, COUNT(DISTINCT user_id) AS c FROM plays GROUP BY game")
        return {row["game"]: int(row["c"]) for row in rows}

    def last_game(self, user_id: int) -> str | None:
        row = self._row(
            "SELECT game FROM plays WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,))
        return row["game"] if row else None
