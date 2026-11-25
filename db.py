import json
import os
import sqlite3
import threading
import time
import uuid


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS club_seasons (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER NOT NULL,
        ends_at    INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'open',
        winner_id  INTEGER NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS club_entries (
        season_id      INTEGER NOT NULL,
        user_id        INTEGER NOT NULL,
        entry_fee      INTEGER NOT NULL DEFAULT 0,
        finished_round INTEGER NOT NULL DEFAULT 0,
        total_won      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (season_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS club_win_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        season_id INTEGER NOT NULL,
        amount    INTEGER NOT NULL,
        at        INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_club_win_user_at ON club_win_log(user_id, at)",
    """
    CREATE TABLE IF NOT EXISTS pet_inventory (
        user_id   INTEGER PRIMARY KEY,
        pet_type  TEXT NOT NULL DEFAULT 'cat',
        level     INTEGER NOT NULL DEFAULT 1,
        xp        INTEGER NOT NULL DEFAULT 0,
        fed_at    INTEGER NOT NULL DEFAULT 0,
        born_at   INTEGER NOT NULL DEFAULT 0,
        last_play_at INTEGER NOT NULL DEFAULT 0,
        total_earned INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS islands (
        user_id   INTEGER PRIMARY KEY,
        islands   TEXT NOT NULL DEFAULT '{}',
        income_at INTEGER NOT NULL DEFAULT 0,
        total_earned INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cars (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   INTEGER NOT NULL,
        model     TEXT NOT NULL,
        fuel      INTEGER NOT NULL DEFAULT 0,
        fuel_max  INTEGER NOT NULL DEFAULT 0,
        rent_until INTEGER NOT NULL DEFAULT 0,
        bought_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS yachts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        model      TEXT NOT NULL,
        fuel       INTEGER NOT NULL DEFAULT 0,
        fuel_max   INTEGER NOT NULL DEFAULT 0,
        cruise_until INTEGER NOT NULL DEFAULT 0,
        fish_at    INTEGER NOT NULL DEFAULT 0,
        bought_at  INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS businesses (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        model        TEXT NOT NULL,
        last_collect INTEGER NOT NULL DEFAULT 0,
        bought_at    INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fish_game (
        user_id    INTEGER PRIMARY KEY,
        yacht_id   INTEGER NOT NULL,
        cell       INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mining (
        user_id      INTEGER PRIMARY KEY,
        gpus         INTEGER NOT NULL DEFAULT 0,
        slots        INTEGER NOT NULL DEFAULT 50,
        btc          REAL NOT NULL DEFAULT 0,
        power_until  INTEGER NOT NULL DEFAULT 0,
        last_collect INTEGER NOT NULL DEFAULT 0,
        bought_at    INTEGER NOT NULL DEFAULT 0
    )
    """,
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
    CREATE TABLE IF NOT EXISTS level_claims (
        user_id    INTEGER NOT NULL,
        level      INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, level)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_prefixes (
        user_id    INTEGER NOT NULL,
        prefix_key TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, prefix_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_backgrounds (
        user_id    INTEGER PRIMARY KEY,
        mime       TEXT NOT NULL,
        data       TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_avatars (
        user_id    INTEGER PRIMARY KEY,
        mime       TEXT NOT NULL,
        data       TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        user_id       INTEGER PRIMARY KEY,
        login         TEXT UNIQUE,
        password_hash TEXT,
        password_salt TEXT,
        token_hash    TEXT,
        token_expires INTEGER NOT NULL DEFAULT 0,
        created_at    INTEGER NOT NULL,
        updated_at    INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_actions (
        id         TEXT PRIMARY KEY,
        admin_id   INTEGER NOT NULL,
        target_id  INTEGER,
        action     TEXT NOT NULL,
        detail     TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gmpoint_log (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        reason     TEXT NOT NULL,
        admin_id   INTEGER,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_accounts_login ON accounts(login)",
    "CREATE INDEX IF NOT EXISTS idx_admin_actions_created ON admin_actions(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_gmpoint_log_user ON gmpoint_log(user_id, created_at DESC)",
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
    CREATE TABLE IF NOT EXISTS hour_quest_claims (
        user_id    INTEGER NOT NULL,
        hour       TEXT NOT NULL,
        quest      TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, hour, quest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_prefixes (
        key       TEXT PRIMARY KEY,
        title     TEXT NOT NULL,
        color     TEXT NOT NULL DEFAULT '#ffd166',
        color2    TEXT NOT NULL DEFAULT '',
        style     TEXT NOT NULL DEFAULT 'solid',
        bonus     REAL NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS treasury_history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        kind      TEXT NOT NULL,
        user_id   INTEGER,
        amount    INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS giveaway_entries (
        user_id INTEGER NOT NULL,
        amount  INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id)
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
    """
    CREATE TABLE IF NOT EXISTS bj_rounds (
        id          TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL,
        bet         INTEGER NOT NULL,
        deck        TEXT NOT NULL,
        player      TEXT NOT NULL,
        dealer      TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'active',
        doubled     INTEGER NOT NULL DEFAULT 0,
        payout      INTEGER NOT NULL DEFAULT 0,
        created_at  INTEGER NOT NULL,
        finished_at INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bj_user ON bj_rounds(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_bj_status ON bj_rounds(status)",
    """
    CREATE TABLE IF NOT EXISTS transfers (
        id         TEXT PRIMARY KEY,
        from_id    INTEGER NOT NULL,
        to_id      INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_transfers_from ON transfers(from_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transfers_to ON transfers(to_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS promo_codes (
        code       TEXT PRIMARY KEY,
        amount     INTEGER NOT NULL,
        max_uses   INTEGER NOT NULL DEFAULT 0,
        used       INTEGER NOT NULL DEFAULT 0,
        budget     INTEGER NOT NULL DEFAULT 0,
        spent      INTEGER NOT NULL DEFAULT 0,
        per_user   INTEGER NOT NULL DEFAULT 1,
        active     INTEGER NOT NULL DEFAULT 1,
        expires_at INTEGER,
        note       TEXT NOT NULL DEFAULT '',
        currency   TEXT NOT NULL DEFAULT 'mcoin',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promo_claims (
        code       TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (code, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clans (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        tag         TEXT NOT NULL,
        owner_id    INTEGER NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        logo        TEXT NOT NULL DEFAULT '',
        xp          INTEGER NOT NULL DEFAULT 0,
        level       INTEGER NOT NULL DEFAULT 1,
        created_at  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clans_owner ON clans(owner_id)",
    """
    CREATE TABLE IF NOT EXISTS clan_members (
        clan_id   TEXT NOT NULL,
        user_id   INTEGER NOT NULL,
        role      TEXT NOT NULL DEFAULT 'member',
        joined_at INTEGER NOT NULL,
        PRIMARY KEY (clan_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clan_members_user ON clan_members(user_id)",
    """
    CREATE TABLE IF NOT EXISTS clan_requests (
        clan_id    TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        message    TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        PRIMARY KEY (clan_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clan_invites (
        clan_id    TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (clan_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clan_messages (
        id         TEXT PRIMARY KEY,
        clan_id    TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        text       TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clan_messages_clan ON clan_messages(clan_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS friends (
        user_id    INTEGER NOT NULL,
        friend_id  INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, friend_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS friend_requests (
        from_id    INTEGER NOT NULL,
        to_id      INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (from_id, to_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_friend_requests_to ON friend_requests(to_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS market_lots (
        id         TEXT PRIMARY KEY,
        seller_id  INTEGER NOT NULL,
        item_type  TEXT NOT NULL,
        item       TEXT NOT NULL,
        qty        INTEGER NOT NULL DEFAULT 1,
        price      INTEGER NOT NULL,
        currency   TEXT NOT NULL DEFAULT 'mcoin',
        status     TEXT NOT NULL DEFAULT 'active',
        buyer_id   INTEGER,
        created_at INTEGER NOT NULL,
        sold_at    INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_market_lots_active ON market_lots(status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_market_lots_seller ON market_lots(seller_id)",
    """
    CREATE TABLE IF NOT EXISTS market_history (
        id         TEXT PRIMARY KEY,
        lot_id     TEXT NOT NULL,
        seller_id  INTEGER NOT NULL,
        buyer_id   INTEGER NOT NULL,
        item_type  TEXT NOT NULL,
        item       TEXT NOT NULL,
        qty        INTEGER NOT NULL,
        price      INTEGER NOT NULL,
        currency   TEXT NOT NULL DEFAULT 'mcoin',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auction_lots (
        id            TEXT PRIMARY KEY,
        seller_id     INTEGER NOT NULL,
        item_type     TEXT NOT NULL,
        item          TEXT NOT NULL,
        qty           INTEGER NOT NULL DEFAULT 1,
        start_price   INTEGER NOT NULL,
        min_step      INTEGER NOT NULL DEFAULT 100,
        current_bid   INTEGER NOT NULL DEFAULT 0,
        bidder_id     INTEGER,
        bids          TEXT NOT NULL DEFAULT '[]',
        ends_at       INTEGER NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active',
        created_at    INTEGER NOT NULL,
        finished_at   INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_auction_active ON auction_lots(status, ends_at)",
    """
    CREATE TABLE IF NOT EXISTS seasons (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        starts_at  INTEGER NOT NULL,
        ends_at    INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leagues (
        id         TEXT PRIMARY KEY,
        season_id  TEXT NOT NULL,
        name       TEXT NOT NULL,
        icon       TEXT NOT NULL DEFAULT '',
        min_xp     INTEGER NOT NULL DEFAULT 0,
        reward     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS league_members (
        season_id  TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        league_id  TEXT NOT NULL,
        points     INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (season_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_league_points ON league_members(league_id, points DESC)",
    """
    CREATE TABLE IF NOT EXISTS user_season_rewards (
        user_id    INTEGER NOT NULL,
        season_id  TEXT NOT NULL,
        league_id  TEXT NOT NULL,
        claimed_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, season_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS achievement_progress (
        user_id  INTEGER NOT NULL,
        key      TEXT NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ach_progress_user ON achievement_progress(user_id)",
    """
    CREATE TABLE IF NOT EXISTS auto_rounds (
        id          TEXT PRIMARY KEY,
        user_id     INTEGER NOT NULL,
        game        TEXT NOT NULL,
        strategy    TEXT NOT NULL,
        bet         INTEGER NOT NULL,
        rounds_done INTEGER NOT NULL DEFAULT 0,
        rounds_max  INTEGER NOT NULL DEFAULT 0,
        target      REAL NOT NULL DEFAULT 0,
        status      TEXT NOT NULL DEFAULT 'active',
        created_at  INTEGER NOT NULL,
        finished_at INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_auto_rounds_user ON auto_rounds(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS tournaments (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        kind       TEXT NOT NULL,
        prize      INTEGER NOT NULL,
        entry_fee  INTEGER NOT NULL DEFAULT 0,
        min_bet    INTEGER NOT NULL DEFAULT 0,
        starts_at  INTEGER NOT NULL,
        ends_at    INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending',
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments(status, ends_at)",
    """
    CREATE TABLE IF NOT EXISTS tournament_players (
        tournament_id TEXT NOT NULL,
        user_id       INTEGER NOT NULL,
        score         INTEGER NOT NULL DEFAULT 0,
        best_bet      INTEGER NOT NULL DEFAULT 0,
        joined_at     INTEGER NOT NULL,
        finished_at   INTEGER,
        PRIMARY KEY (tournament_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tournament_score ON tournament_players(tournament_id, score DESC)",
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        kind       TEXT NOT NULL,
        title      TEXT NOT NULL,
        text       TEXT NOT NULL DEFAULT '',
        meta       TEXT NOT NULL DEFAULT '{}',
        is_read    INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS virtual_chips (
        user_id     INTEGER NOT NULL,
        chips       INTEGER NOT NULL DEFAULT 0,
        updated_at  INTEGER NOT NULL,
        PRIMARY KEY (user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bot_profiles (
        id          TEXT PRIMARY KEY,
        username    TEXT NOT NULL,
        first_name  TEXT NOT NULL,
        avatar      TEXT NOT NULL DEFAULT '',
        level       INTEGER NOT NULL DEFAULT 5,
        balance     INTEGER NOT NULL DEFAULT 50000,
        play_chance REAL NOT NULL DEFAULT 0.4,
        risk        TEXT NOT NULL DEFAULT 'medium'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clan_wars (
        id          TEXT PRIMARY KEY,
        clan_a      TEXT NOT NULL,
        clan_b      TEXT NOT NULL,
        prize_a     INTEGER NOT NULL DEFAULT 0,
        prize_b     INTEGER NOT NULL DEFAULT 0,
        score_a     INTEGER NOT NULL DEFAULT 0,
        score_b     INTEGER NOT NULL DEFAULT 0,
        starts_at   INTEGER NOT NULL,
        ends_at     INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'active',
        winner_id   TEXT,
        created_at  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clan_wars_status ON clan_wars(status, ends_at)",
    """
    CREATE TABLE IF NOT EXISTS clan_war_bets (
        war_id   TEXT NOT NULL,
        user_id  INTEGER NOT NULL,
        clan_id  TEXT NOT NULL,
        amount   INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (war_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clan_war_hits (
        id         TEXT PRIMARY KEY,
        war_id     TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        target     TEXT NOT NULL,
        damage     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_war_hits ON clan_war_hits(war_id)",
    """
    CREATE TABLE IF NOT EXISTS loans (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL,
        rate_bps   INTEGER NOT NULL,
        term_days  INTEGER NOT NULL,
        take_at    INTEGER NOT NULL,
        due_at     INTEGER NOT NULL,
        paid       INTEGER NOT NULL DEFAULT 0,
        status     TEXT NOT NULL DEFAULT 'active',
        closed_at  INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_loans_user ON loans(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS streak_log (
        user_id    INTEGER NOT NULL,
        day        TEXT NOT NULL,
        streak     INTEGER NOT NULL DEFAULT 0,
        rewards    TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, day)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_streak_user ON streak_log(user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS fish_levels (
        user_id    INTEGER PRIMARY KEY,
        xp         INTEGER NOT NULL DEFAULT 0,
        level      INTEGER NOT NULL DEFAULT 1,
        total_caught INTEGER NOT NULL DEFAULT 0,
        best_weight INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS craft_recipes (
        id          TEXT PRIMARY KEY,
        output_key  TEXT NOT NULL,
        output_qty  INTEGER NOT NULL DEFAULT 1,
        inputs      TEXT NOT NULL,
        cooldown_s  INTEGER NOT NULL DEFAULT 0,
        created_at  INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS craft_jobs (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        recipe_id  TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        ends_at    INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'crafting',
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_craft_jobs_user ON craft_jobs(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS mission_chests (
        user_id    INTEGER NOT NULL,
        chest      TEXT NOT NULL,
        opened_at  INTEGER NOT NULL,
        next_at    INTEGER NOT NULL,
        PRIMARY KEY (user_id, chest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_ships (
        user_id     INTEGER NOT NULL,
        ship        TEXT NOT NULL,
        unlocked_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, ship)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clan_raids (
        id          TEXT PRIMARY KEY,
        clan_id     TEXT NOT NULL,
        boss        TEXT NOT NULL,
        hp          INTEGER NOT NULL,
        max_hp      INTEGER NOT NULL,
        reward      INTEGER NOT NULL DEFAULT 0,
        starts_at   INTEGER NOT NULL,
        ends_at     INTEGER NOT NULL,
        status      TEXT NOT NULL DEFAULT 'active',
        created_at  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clan_raids_status ON clan_raids(status, ends_at)",
    """
    CREATE TABLE IF NOT EXISTS clan_raid_hits (
        id         TEXT PRIMARY KEY,
        raid_id    TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        damage     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_raid_hits ON clan_raid_hits(raid_id)",
    """
    CREATE TABLE IF NOT EXISTS tournament_rewards (
        tournament_id TEXT NOT NULL,
        place         INTEGER NOT NULL,
        reward        INTEGER NOT NULL,
        claimed_by    INTEGER,
        PRIMARY KEY (tournament_id, place)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_claims (
        tournament_id TEXT NOT NULL,
        user_id       INTEGER NOT NULL,
        place         INTEGER NOT NULL,
        reward        INTEGER NOT NULL,
        claimed_at    INTEGER NOT NULL,
        PRIMARY KEY (tournament_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        kind       TEXT NOT NULL,
        target     INTEGER NOT NULL,
        progress   INTEGER NOT NULL DEFAULT 0,
        reward     INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'active',
        extra      TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS tokens (
        user_id    INTEGER PRIMARY KEY,
        value      INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS token_log (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        delta      INTEGER NOT NULL,
        reason     TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_token_log_user ON token_log(user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS shop_rotations (
        key        TEXT PRIMARY KEY,
        items      TEXT NOT NULL DEFAULT '{}',
        until      INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS player_cards (
        user_id    INTEGER NOT NULL,
        card       TEXT NOT NULL,
        qty        INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, card)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_player_cards_user ON player_cards(user_id)",
    """
    CREATE TABLE IF NOT EXISTS card_album (
        card    TEXT PRIMARY KEY,
        set_key TEXT NOT NULL,
        number  INTEGER NOT NULL,
        title   TEXT NOT NULL,
        rarity  TEXT NOT NULL DEFAULT 'common'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS card_offers (
        offer_id   TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        card       TEXT NOT NULL,
        price      INTEGER NOT NULL DEFAULT 0,
        qty        INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_card_offers_user ON card_offers(user_id)",
    """
    CREATE TABLE IF NOT EXISTS arena_ratings (
        user_id    INTEGER PRIMARY KEY,
        rating     INTEGER NOT NULL DEFAULT 1200,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS arena_matches (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        opponent   TEXT NOT NULL,
        bet        INTEGER NOT NULL,
        result     TEXT NOT NULL,
        payout     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_arena_matches_user ON arena_matches(user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS bingo_games (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        bet        INTEGER NOT NULL,
        board      TEXT NOT NULL,
        numbers    TEXT NOT NULL DEFAULT '[]',
        marks      TEXT NOT NULL DEFAULT '[]',
        status     TEXT NOT NULL DEFAULT 'active',
        payout     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bingo_user ON bingo_games(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS live_bets (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        session_id TEXT NOT NULL,
        game       TEXT NOT NULL,
        bet        INTEGER NOT NULL,
        odds       REAL NOT NULL DEFAULT 2.0,
        outcome    TEXT NOT NULL DEFAULT 'pending',
        payout     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_live_bets_user ON live_bets(user_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS live_sessions (
        id         TEXT PRIMARY KEY,
        game       TEXT NOT NULL,
        host_id    INTEGER NOT NULL,
        bet        INTEGER NOT NULL DEFAULT 0,
        seed       TEXT NOT NULL,
        outcome    REAL NOT NULL DEFAULT 0,
        status     TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL,
        finished_at INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_live_sessions_status ON live_sessions(status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS season_events (
        id         TEXT PRIMARY KEY,
        key        TEXT NOT NULL,
        title      TEXT NOT NULL,
        desc_text  TEXT NOT NULL DEFAULT '',
        starts_at  INTEGER NOT NULL,
        ends_at    INTEGER NOT NULL,
        prize      INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_season_events_dates ON season_events(starts_at, ends_at)",
    """
    CREATE TABLE IF NOT EXISTS event_claims (
        event_id TEXT NOT NULL,
        user_id  INTEGER NOT NULL,
        claimed_at INTEGER NOT NULL,
        PRIMARY KEY (event_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS restaurant_orders (
        id         TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        dish       TEXT NOT NULL,
        fish_key   TEXT NOT NULL,
        fish_count INTEGER NOT NULL DEFAULT 1,
        reward     INTEGER NOT NULL,
        started_at INTEGER NOT NULL,
        ready_at   INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'cooking',
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_restaurant_user ON restaurant_orders(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS medals (
        user_id INTEGER NOT NULL,
        medal   TEXT NOT NULL,
        earned_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, medal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_medals_user ON medals(user_id)",
    """
    CREATE TABLE IF NOT EXISTS daily_goals (
        user_id  INTEGER NOT NULL,
        day      TEXT NOT NULL,
        kind     TEXT NOT NULL,
        target   INTEGER NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        reward   INTEGER NOT NULL DEFAULT 0,
        claimed  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, day, kind)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_goals_user ON daily_goals(user_id, day)",
    """
    CREATE TABLE IF NOT EXISTS leader_titles (
        user_id   INTEGER PRIMARY KEY,
        title     TEXT NOT NULL DEFAULT '',
        week      TEXT NOT NULL DEFAULT '',
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fish_species_progress (
        user_id INTEGER NOT NULL,
        species TEXT NOT NULL,
        caught  INTEGER NOT NULL DEFAULT 0,
        best_weight INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, species)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fish_progress_user ON fish_species_progress(user_id)",
    """
    CREATE TABLE IF NOT EXISTS dungeon_runs (
        id           TEXT PRIMARY KEY,
        user_id      INTEGER NOT NULL,
        dungeon      TEXT NOT NULL,
        level        INTEGER NOT NULL DEFAULT 1,
        hp           INTEGER NOT NULL DEFAULT 100,
        max_hp       INTEGER NOT NULL DEFAULT 100,
        gold         INTEGER NOT NULL DEFAULT 0,
        kills        INTEGER NOT NULL DEFAULT 0,
        status       TEXT NOT NULL DEFAULT 'active',
        created_at   INTEGER NOT NULL,
        finished_at  INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dungeon_user ON dungeon_runs(user_id, status)",
    """
    CREATE TABLE IF NOT EXISTS gifts (
        id         TEXT PRIMARY KEY,
        from_id    INTEGER NOT NULL,
        to_id      INTEGER NOT NULL,
        gift       TEXT NOT NULL,
        note       TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        status     TEXT NOT NULL DEFAULT 'pending'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gifts_to ON gifts(to_id, status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS pvp_rooms (
        id          TEXT PRIMARY KEY,
        owner_id    INTEGER NOT NULL,
        game        TEXT NOT NULL,
        bet         INTEGER NOT NULL,
        guest_id    INTEGER,
        status      TEXT NOT NULL DEFAULT 'waiting',
        owner_roll  INTEGER,
        guest_roll  INTEGER,
        winner_id   INTEGER,
        created_at  INTEGER NOT NULL,
        started_at  INTEGER,
        finished_at INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pvp_rooms_status ON pvp_rooms(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_pvp_rooms_owner ON pvp_rooms(owner_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_pvp_rooms_guest ON pvp_rooms(guest_id, status)",
    """
    CREATE TABLE IF NOT EXISTS workers (
        user_id    INTEGER PRIMARY KEY,
        worker     TEXT NOT NULL DEFAULT '',
        hired_at   INTEGER NOT NULL,
        last_pay   INTEGER NOT NULL,
        total_earned INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_recipes (
        worker TEXT PRIMARY KEY,
        cost   INTEGER NOT NULL,
        income INTEGER NOT NULL,
        period INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS farm_plots (
        user_id     INTEGER NOT NULL,
        plot        INTEGER NOT NULL,
        crop        TEXT NOT NULL DEFAULT '',
        planted_at  INTEGER NOT NULL DEFAULT 0,
        ready_at    INTEGER NOT NULL DEFAULT 0,
        collected   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, plot)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_farm_plots_user ON farm_plots(user_id)",
    """
    CREATE TABLE IF NOT EXISTS farm_layouts (
        user_id INTEGER PRIMARY KEY,
        layout  TEXT NOT NULL DEFAULT '[]',
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS battlepass (
        user_id  INTEGER PRIMARY KEY,
        level    INTEGER NOT NULL DEFAULT 0,
        xp       INTEGER NOT NULL DEFAULT 0,
        premium  INTEGER NOT NULL DEFAULT 0,
        rewards  TEXT NOT NULL DEFAULT '[]',
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS battlepass_config (
        id       INTEGER PRIMARY KEY CHECK (id = 1),
        season   TEXT NOT NULL DEFAULT 'Сезон 1',
        levels   TEXT NOT NULL DEFAULT '[]',
        ends_at  INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reward_calendar (
        user_id  INTEGER NOT NULL,
        day      INTEGER NOT NULL,
        claimed_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, day)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reward_calendar_user ON reward_calendar(user_id)",
    """
    CREATE TABLE IF NOT EXISTS news_items (
        id         TEXT PRIMARY KEY,
        title      TEXT NOT NULL,
        body       TEXT NOT NULL,
        icon       TEXT NOT NULL DEFAULT '📰',
        priority   INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_created ON news_items(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS news_read (
        user_id   INTEGER NOT NULL,
        news_id   TEXT NOT NULL,
        read_at   INTEGER NOT NULL,
        PRIMARY KEY (user_id, news_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ref_levels (
        level        INTEGER PRIMARY KEY,
        title        TEXT NOT NULL,
        reward_bonus REAL NOT NULL DEFAULT 0,
        min_children INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ref_children (
        parent_id    INTEGER NOT NULL,
        child_id     INTEGER NOT NULL,
        child_active INTEGER NOT NULL DEFAULT 0,
        joined_at    INTEGER NOT NULL,
        PRIMARY KEY (parent_id, child_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ref_children_parent ON ref_children(parent_id)",
    """
    CREATE TABLE IF NOT EXISTS economy_accounts (
        user_id       INTEGER PRIMARY KEY,
        cash_balance  INTEGER NOT NULL DEFAULT 0,
        bank_balance  INTEGER NOT NULL DEFAULT 0,
        credits       INTEGER NOT NULL DEFAULT 0,
        gems          INTEGER NOT NULL DEFAULT 0,
        energy        INTEGER NOT NULL DEFAULT 100,
        energy_max    INTEGER NOT NULL DEFAULT 100,
        energy_at     INTEGER NOT NULL DEFAULT 0,
        updated_at    INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deposit_plans (
        user_id      INTEGER NOT NULL,
        plan_id      TEXT NOT NULL,
        principal    INTEGER NOT NULL DEFAULT 0,
        interest_pct REAL NOT NULL DEFAULT 0,
        term_days    INTEGER NOT NULL DEFAULT 1,
        started_at   INTEGER NOT NULL,
        PRIMARY KEY (user_id, plan_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS currency_rates (
        currency     TEXT PRIMARY KEY,
        rate_to_gold REAL NOT NULL DEFAULT 1,
        updated_at   INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_market (
        symbol      TEXT PRIMARY KEY,
        company     TEXT NOT NULL,
        price       REAL NOT NULL DEFAULT 1,
        base_price  REAL NOT NULL DEFAULT 1,
        volatility  REAL NOT NULL DEFAULT 0.05,
        trend       REAL NOT NULL DEFAULT 0,
        updated_at  INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_portfolio (
        user_id  INTEGER NOT NULL,
        symbol   TEXT NOT NULL,
        shares   INTEGER NOT NULL DEFAULT 0,
        invested INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tax_rates (
        tax_key  TEXT PRIMARY KEY,
        rate_pct REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS economy_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        action     TEXT NOT NULL,
        amount     INTEGER NOT NULL DEFAULT 0,
        currency   TEXT NOT NULL DEFAULT 'gold',
        balance_after INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_economy_log_user ON economy_log(user_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS guild_buildings (
        clan_id   TEXT NOT NULL,
        building  TEXT NOT NULL,
        level     INTEGER NOT NULL DEFAULT 1,
        resources INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (clan_id, building)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guild_resources (
        clan_id  TEXT PRIMARY KEY,
        wood     INTEGER NOT NULL DEFAULT 0,
        stone    INTEGER NOT NULL DEFAULT 0,
        iron     INTEGER NOT NULL DEFAULT 0,
        gold     INTEGER NOT NULL DEFAULT 0,
        food     INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guild_tax_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        clan_id    TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL DEFAULT 0,
        tax_type   TEXT NOT NULL DEFAULT 'trade',
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_guild_tax_log_clan ON guild_tax_log(clan_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS map_provinces (
        province_id  TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        region       TEXT NOT NULL,
        base_income  INTEGER NOT NULL DEFAULT 100,
        x            INTEGER NOT NULL DEFAULT 0,
        y            INTEGER NOT NULL DEFAULT 0,
        owner_clan   TEXT,
        owner_user   INTEGER,
        captured_at  INTEGER NOT NULL DEFAULT 0,
        defense      INTEGER NOT NULL DEFAULT 100
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS map_capture_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        province_id TEXT NOT NULL,
        clan_id     TEXT NOT NULL,
        user_id     INTEGER NOT NULL,
        result      TEXT NOT NULL,
        amount      INTEGER NOT NULL DEFAULT 0,
        created_at  INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS map_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        province_id TEXT NOT NULL,
        event_type  TEXT NOT NULL,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL DEFAULT '',
        active      INTEGER NOT NULL DEFAULT 1,
        created_at  INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_map_capture ON map_capture_log(province_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_seasons (
        season_id   TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        game        TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'qualify',
        started_at  INTEGER NOT NULL,
        ends_at     INTEGER NOT NULL,
        prize_pool  INTEGER NOT NULL DEFAULT 0,
        max_participants INTEGER NOT NULL DEFAULT 16
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_participants (
        season_id  TEXT NOT NULL,
        user_id    INTEGER NOT NULL,
        score      REAL NOT NULL DEFAULT 0,
        qualified  INTEGER NOT NULL DEFAULT 0,
        seed       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (season_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_matches (
        match_id   TEXT PRIMARY KEY,
        season_id  TEXT NOT NULL,
        round      INTEGER NOT NULL,
        bracket    TEXT NOT NULL,
        user_a     INTEGER,
        user_b     INTEGER,
        score_a    REAL NOT NULL DEFAULT 0,
        score_b    REAL NOT NULL DEFAULT 0,
        winner_id  INTEGER,
        finished   INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_prizes (
        season_id TEXT NOT NULL,
        place     INTEGER NOT NULL,
        prize     INTEGER NOT NULL DEFAULT 0,
        title     TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (season_id, place)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS street_properties (
        user_id     INTEGER NOT NULL,
        prop_type   TEXT NOT NULL,
        level       INTEGER NOT NULL DEFAULT 1,
        income_rate INTEGER NOT NULL DEFAULT 10,
        purchased_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, prop_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS street_jobs (
        user_id    INTEGER PRIMARY KEY,
        job_key    TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        last_collect INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jackpot_pool (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        pool       INTEGER NOT NULL DEFAULT 0,
        last_winner INTEGER,
        last_win_at INTEGER NOT NULL DEFAULT 0,
        last_win_amt INTEGER NOT NULL DEFAULT 0,
        next_draw  INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jackpot_tickets (
        ticket_id  TEXT PRIMARY KEY,
        user_id    INTEGER NOT NULL,
        amount     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS street_work_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        job_key    TEXT NOT NULL,
        reward     INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )
    """,
]

DEFAULT_SETTINGS = {
    "min_bet": "10",
    "max_bet": "100000",
    "min_mines": "1",
    "max_mines": "24",
    "daily_bonus": "1000",
    "hourly_bonus": "500",
    "chat_url": "",
    "maintenance": "0",
    "update_version": "0",
    "weekly_reward_week": "",
    "game_mines": "1",
    "game_dice": "1",
    "game_wheel": "1",
    "game_crash": "1",
    "game_roulette": "1",
    "game_slots": "1",
    "game_coinflip": "1",
    "game_blackjack": "1",
    "game_basket": "1",
    "game_fishing": "1",
    "game_darts": "1",
}


class Database:
    def __init__(self, path: str = "data/saper.db", dsn: str | None = None):
        self._lock = threading.RLock()
        self._settings_cache: tuple[float, dict] = (0.0, {})
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
            ("role", "TEXT NOT NULL DEFAULT 'user'"),
            ("gmpoint", "INTEGER NOT NULL DEFAULT 0"),
            ("prefix", "TEXT NOT NULL DEFAULT ''"),
            ("last_seen", "INTEGER NOT NULL DEFAULT 0"),
            ("avatar_key", "TEXT NOT NULL DEFAULT 'letter'"),
            ("bg_key", "TEXT NOT NULL DEFAULT 'default'"),
            ("game_bg_key", "TEXT NOT NULL DEFAULT ''"),
            ("daily_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("last_daily_day", "TEXT NOT NULL DEFAULT ''"),
            ("rod_key", "TEXT NOT NULL DEFAULT ''"),
            ("prestige", "INTEGER NOT NULL DEFAULT 0"),
            ("prestige_xp", "INTEGER NOT NULL DEFAULT 0"),
            ("prestige_best", "REAL NOT NULL DEFAULT 1.0"),
            ("energy", "INTEGER NOT NULL DEFAULT 100"),
            ("energy_max", "INTEGER NOT NULL DEFAULT 100"),
            ("energy_at", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in present:
                self._exec(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        if "auto_target" not in self._table_columns("rounds"):
            self._exec(
                "ALTER TABLE rounds ADD COLUMN auto_target REAL NOT NULL DEFAULT 0")
        if "currency" not in self._table_columns("promo_codes"):
            self._exec(
                "ALTER TABLE promo_codes ADD COLUMN currency TEXT NOT NULL DEFAULT 'mcoin'")
        if "pet_inventory" in [r["name"] for r in self._rows(
                "SELECT name FROM sqlite_master WHERE type='table'")]:
            if "last_play_at" not in self._table_columns("pet_inventory"):
                self._exec(
                    "ALTER TABLE pet_inventory ADD COLUMN "
                    "last_play_at INTEGER NOT NULL DEFAULT 0")
        if "mining" in [r["name"] for r in self._rows(
                "SELECT name FROM sqlite_master WHERE type='table'")]:
            mining_cols = self._table_columns("mining")
            if "btc" not in mining_cols:
                self._exec(
                    "ALTER TABLE mining ADD COLUMN btc REAL NOT NULL DEFAULT 0")
            if "power_until" not in mining_cols:
                self._exec(
                    "ALTER TABLE mining ADD COLUMN "
                    "power_until INTEGER NOT NULL DEFAULT 0")
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
                    "photo_url = COALESCE(?, photo_url), last_seen = ? WHERE user_id = ?",
                    (username, first_name, photo_url, int(time.time()), user_id),
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
                       server_seed, server_seed_hash, client_seed, referred_by, photo_url,
                       last_seen)
                   VALUES (?, ?, ?, 1000, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, now, seed, seed_hash, client_seed,
                 referrer, photo_url or "", now),
            )
            return self.user(user_id)

    def user(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def account(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM accounts WHERE user_id = ?", (user_id,))

    def account_by_login(self, login: str) -> dict | None:
        return self._row("SELECT * FROM accounts WHERE LOWER(login) = LOWER(?)",
                         ((login or "").strip(),))

    def set_account(self, user_id: int, login: str, password_hash: str,
                    password_salt: str) -> None:
        now = int(time.time())
        self._exec(
            """INSERT INTO accounts (user_id, login, password_hash, password_salt,
                                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET
                   login = excluded.login,
                   password_hash = excluded.password_hash,
                   password_salt = excluded.password_salt,
                   updated_at = excluded.updated_at""",
            (user_id, login, password_hash, password_salt, now, now))

    def set_account_password(self, user_id: int, password_hash: str,
                             password_salt: str) -> None:
        self._exec(
            "UPDATE accounts SET password_hash = ?, password_salt = ?, updated_at = ? "
            "WHERE user_id = ?",
            (password_hash, password_salt, int(time.time()), user_id))

    def set_account_token(self, user_id: int, token_hash: str, expires: int) -> None:
        self._exec(
            "UPDATE accounts SET token_hash = ?, token_expires = ?, updated_at = ? "
            "WHERE user_id = ?",
            (token_hash, int(expires), int(time.time()), user_id))

    def user_by_token(self, token_hash: str, now: int) -> dict | None:
        return self._row(
            """SELECT u.* FROM accounts a JOIN users u ON u.user_id = a.user_id
               WHERE a.token_hash = ? AND a.token_expires > ?""",
            (token_hash, int(now)))

    def clear_account_token(self, user_id: int) -> None:
        self._exec(
            "UPDATE accounts SET token_hash = NULL, token_expires = 0, updated_at = ? "
            "WHERE user_id = ?",
            (int(time.time()), user_id))

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

    def add_gmpoint(self, user_id: int, delta: int) -> int | None:
        with self._lock:
            if delta < 0:
                changed = self._exec(
                    "UPDATE users SET gmpoint = gmpoint + ? "
                    "WHERE user_id = ? AND gmpoint >= ?",
                    (delta, user_id, -delta))
                if not changed:
                    return None
            else:
                self._exec(
                    "UPDATE users SET gmpoint = gmpoint + ? WHERE user_id = ?",
                    (delta, user_id))
            row = self._row("SELECT gmpoint FROM users WHERE user_id = ?", (user_id,))
            return int(row["gmpoint"]) if row else None

    def set_gmpoint(self, user_id: int, value: int) -> int:
        value = max(0, int(value))
        self._exec("UPDATE users SET gmpoint = ? WHERE user_id = ?", (value, user_id))
        return value

    def spend_gmpoint(self, user_id: int, amount: int) -> bool:
        if amount <= 0:
            return True
        changed = self._exec(
            "UPDATE users SET gmpoint = gmpoint - ? "
            "WHERE user_id = ? AND gmpoint >= ?",
            (amount, user_id, amount))
        return bool(changed)

    def log_gmpoint(self, user_id: int, amount: int, reason: str,
                    admin_id: int | None = None) -> None:
        self._exec(
            "INSERT INTO gmpoint_log (id, user_id, amount, reason, admin_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, user_id, int(amount), reason, admin_id, int(time.time())))

    def level_claims(self, user_id: int) -> set[int]:
        rows = self._rows("SELECT level FROM level_claims WHERE user_id = ?", (user_id,))
        return {int(row["level"]) for row in rows}

    def claim_level(self, user_id: int, level: int, coins: int, gmpoint: int = 0,
                    lootbox: int = 0, prefix: str = "") -> bool:
        with self._lock:
            changed = self._exec(
                "INSERT INTO level_claims (user_id, level, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id, level) DO NOTHING",
                (user_id, int(level), int(time.time())))
            if not changed:
                return False
            if coins:
                self._exec("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                           (int(coins), user_id))
            if gmpoint:
                self._exec("UPDATE users SET gmpoint = gmpoint + ? WHERE user_id = ?",
                           (int(gmpoint), user_id))
                self.log_gmpoint(user_id, int(gmpoint), f"level:{level}")
            if lootbox:
                self.add_item(user_id, "lootbox", int(lootbox))
            if prefix:
                self.add_prefix(user_id, prefix)
            return True

    def user_prefixes(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT prefix_key FROM user_prefixes WHERE user_id = ?",
                          (user_id,))
        return {row["prefix_key"] for row in rows}

    def custom_prefixes(self) -> list[dict]:
        return self._rows("SELECT key, title, color, color2, style, bonus "
                          "FROM custom_prefixes ORDER BY created_at DESC")

    def get_custom_prefix(self, key: str) -> dict | None:
        return self._row("SELECT key, title, color, color2, style, bonus "
                         "FROM custom_prefixes WHERE key = ?", (key,))

    def upsert_custom_prefix(self, key: str, title: str, color: str, color2: str,
                             style: str, bonus: float) -> None:
        self._exec(
            """INSERT INTO custom_prefixes (key, title, color, color2, style, bonus, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (key) DO UPDATE SET
                   title = excluded.title, color = excluded.color,
                   color2 = excluded.color2, style = excluded.style,
                   bonus = excluded.bonus""",
            (key, title, color, color2, style, bonus, int(time.time())))

    def delete_custom_prefix(self, key: str) -> None:
        self._exec("DELETE FROM custom_prefixes WHERE key = ?", (key,))

    def add_prefix(self, user_id: int, prefix_key: str) -> bool:
        changed = self._exec(
            "INSERT INTO user_prefixes (user_id, prefix_key, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, prefix_key) DO NOTHING",
            (user_id, prefix_key, int(time.time())))
        return bool(changed)

    def has_prefix(self, user_id: int, prefix_key: str) -> bool:
        row = self._row(
            "SELECT 1 AS ok FROM user_prefixes WHERE user_id = ? AND prefix_key = ?",
            (user_id, prefix_key))
        return bool(row)

    def set_prefix(self, user_id: int, prefix_key: str) -> bool:
        if prefix_key and not self.has_prefix(user_id, prefix_key):
            return False
        self._exec("UPDATE users SET prefix = ? WHERE user_id = ?",
                   (prefix_key or "", user_id))
        return True

    def equip_prefix(self, user_id: int, prefix_key: str) -> bool:
        """Надеть купленный префикс; пустая строка — снять оформление."""
        prefix_key = (prefix_key or "").strip()
        if prefix_key:
            if not self.has_prefix(user_id, prefix_key):
                return False
            self._exec("UPDATE users SET prefix = ? WHERE user_id = ?",
                       (prefix_key, user_id))
            return True
        self._exec("UPDATE users SET prefix = '' WHERE user_id = ?", (user_id,))
        return True

    def set_cosmetic(self, user_id: int, kind: str, key: str) -> bool:
        """kind: avatar | background. Возвращает False для неизвестного вида."""
        column = {"avatar": "avatar_key", "background": "bg_key"}.get(kind)
        if not column:
            return False
        self._exec(f"UPDATE users SET {column} = ? WHERE user_id = ?",
                   ((key or "").strip(), user_id))
        return True

    def set_game_background(self, user_id: int, key: str) -> None:
        self._exec("UPDATE users SET game_bg_key = ? WHERE user_id = ?",
                   ((key or "").strip(), user_id))

    def set_rod(self, user_id: int, key: str) -> None:
        self._exec("UPDATE users SET rod_key = ? WHERE user_id = ?",
                   ((key or "").strip(), user_id))

    def set_user_background(self, user_id: int, mime: str, data: str) -> None:
        self._exec(
            """INSERT INTO user_backgrounds (user_id, mime, data, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET
                   mime = excluded.mime,
                   data = excluded.data,
                   updated_at = excluded.updated_at""",
            (user_id, mime, data, int(time.time())))

    def user_background(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT user_id, mime, data, updated_at FROM user_backgrounds "
            "WHERE user_id = ?", (user_id,))

    def set_user_avatar(self, user_id: int, mime: str, data: str) -> None:
        """Ставит пользовательское фото на место аватара."""
        self._exec(
            """INSERT INTO user_avatars (user_id, mime, data, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET
                   mime = excluded.mime,
                   data = excluded.data,
                   updated_at = excluded.updated_at""",
            (user_id, mime, data, int(time.time())))
        self.set_custom_avatar_key(user_id)

    def set_custom_avatar_key(self, user_id: int) -> None:
        self._exec("UPDATE users SET avatar_key = ? WHERE user_id = ?",
                   ("custom", user_id))

    def user_avatar(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT user_id, mime, data, updated_at FROM user_avatars "
            "WHERE user_id = ?", (user_id,))

    def delete_user_avatar(self, user_id: int) -> None:
        self._exec("DELETE FROM user_avatars WHERE user_id = ?", (user_id,))

    def delete_user_background(self, user_id: int) -> None:
        self._exec("DELETE FROM user_backgrounds WHERE user_id = ?", (user_id,))

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

    def count_unique_games(self, user_id: int) -> int:
        row = self._row(
            "SELECT COUNT(DISTINCT game) AS c FROM plays WHERE user_id = ?",
            (user_id,))
        return int(row["c"]) if row else 0

    def count_quests_claimed(self, user_id: int) -> int:
        day = self._row("SELECT COUNT(*) AS c FROM quest_claims WHERE user_id = ?",
                        (user_id,))
        hour = self._row(
            "SELECT COUNT(*) AS c FROM hour_quest_claims WHERE user_id = ?",
            (user_id,))
        return (int(day["c"]) if day else 0) + (int(hour["c"]) if hour else 0)

    def count_items_owned(self, user_id: int) -> int:
        row = self._row(
            "SELECT COALESCE(SUM(qty), 0) AS c FROM inventory WHERE user_id = ?",
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

    def pending_duel_for(self, user_id: int, now: int | None = None,
                         ttl: int = 0) -> dict | None:
        if ttl > 0:
            self.expire_duels(int(now or time.time()), ttl)
        return self._row(
            """SELECT * FROM duels WHERE status = 'pending'
               AND (challenger_id = ? OR opponent_id = ?)
               ORDER BY created_at DESC LIMIT 1""", (user_id, user_id))

    def expire_duels(self, now: int, ttl: int) -> list[dict]:
        """Просроченные вызовы закрываем и возвращаем ставку автору."""
        if ttl <= 0:
            return []
        with self._lock:
            stale = self._rows(
                """SELECT id, challenger_id, bet FROM duels
                   WHERE status = 'pending' AND created_at < ?""",
                (int(now) - int(ttl),))
            expired = []
            for row in stale:
                changed = self._exec(
                    "UPDATE duels SET status = 'expired', finished_at = ? "
                    "WHERE id = ? AND status = 'pending'",
                    (int(now), row["id"]))
                if not changed:
                    continue
                self._exec("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                           (int(row["bet"]), int(row["challenger_id"])))
                expired.append(row)
            return expired

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

    def expire_round(self, round_id: str) -> int:
        """Закрывает зависшую партию и возвращает ставку (или 0)."""
        row = self._row("SELECT bet FROM rounds WHERE id = ? AND status = 'active'",
                        (round_id,))
        if not row:
            return 0
        bet = int(row["bet"])
        self._exec(
            "UPDATE rounds SET status = 'expired', payout = ? "
            "WHERE id = ? AND status = 'active'", (bet, round_id))
        check = self._row("SELECT status FROM rounds WHERE id = ?", (round_id,))
        return bet if check and check["status"] == "expired" else 0

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
                      best_multiplier, games_played, prefix,
                      avatar_key, bg_key, last_seen
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

    def top_by_level(self, limit: int = 10) -> list[dict]:
        return self._rows(
            """SELECT user_id, username, first_name, photo_url, xp, games_won, prefix,
                      avatar_key, bg_key, last_seen
               FROM users ORDER BY xp DESC, games_won DESC, created_at ASC LIMIT ?""",
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

    def referral_share(self, user_id: int, payout: int, rate: float) -> int:
        """5% от выигрыша приглашённого переводим тому, кто его позвал."""
        if payout <= 0 or rate <= 0:
            return 0
        with self._lock:
            me = self.user(user_id)
            if not me or not me.get("referred_by"):
                return 0
            ref_id = int(me["referred_by"])
            if ref_id == int(user_id):
                return 0
            ref = self.user(ref_id)
            if not ref or ref.get("is_banned"):
                return 0
            amount = int(round(int(payout) * float(rate)))
            amount = min(amount, max(0, int(me["balance"])))
            if amount <= 0:
                return 0
            self._exec("UPDATE users SET balance = balance - ? WHERE user_id = ?",
                       (amount, user_id))
            self._exec("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                       (amount, ref_id))
            return amount

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

    def claim_daily_progressive(self, user_id: int, now: int, cooldown: int,
                                today: str, base: int, step: int, cap_streak: int,
                                max_amount: int) -> dict | None:
        """Ежедневный бонус с серией: каждый следующий день серии дороже."""
        with self._lock:
            me = self.user(user_id)
            if not me or now - int(me["last_daily"]) < cooldown:
                return None
            last_day = me.get("last_daily_day") or ""
            streak = int(me.get("daily_streak") or 0)
            if last_day == today:
                streak = max(1, streak)
            else:
                diff = 9999
                try:
                    from datetime import date

                    diff = (date.fromisoformat(today)
                            - date.fromisoformat(last_day)).days
                except (TypeError, ValueError):
                    diff = 9999
                streak = streak + 1 if diff == 1 else 1
            streak = max(1, min(int(cap_streak), streak))
            amount = min(int(max_amount), int(base) + (streak - 1) * int(step))
            self._exec(
                "UPDATE users SET last_daily = ?, daily_streak = ?, "
                "last_daily_day = ?, balance = balance + ? WHERE user_id = ?",
                (now, streak, today, amount, user_id))
            return {"amount": amount, "streak": streak}

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
        cached_at, cached = self._settings_cache
        if cached and time.time() - cached_at < 5:
            return dict(cached)
        values = dict(DEFAULT_SETTINGS)
        for row in self._rows("SELECT key, value FROM settings"):
            values[row["key"]] = row["value"]
        result = {}
        for key, raw in values.items():
            try:
                result[key] = int(raw)
            except (TypeError, ValueError):
                result[key] = raw
        self._settings_cache = (time.time(), dict(result))
        return result

    def set_settings(self, updates: dict) -> dict:
        with self._lock:
            for key, value in updates.items():
                if key not in DEFAULT_SETTINGS:
                    continue
                self._exec("UPDATE settings SET value = ? WHERE key = ?", (str(value), key))
            self._settings_cache = (0.0, {})
        return self.settings()

    # --- admin -----------------------------------------------------------
    ADMIN_USER_FIELDS = (
        "user_id, username, first_name, balance, gmpoint, xp, role, prefix, "
        "games_played, games_won, total_wagered, total_won, best_multiplier, "
        "is_banned, created_at"
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

    def admin_players(self, page: int = 1, per_page: int = 10) -> dict:
        page = max(1, int(page))
        per_page = max(1, min(50, int(per_page)))
        total_row = self._row("SELECT COUNT(*) AS c FROM users")
        total = int(total_row["c"]) if total_row else 0
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        offset = (page - 1) * per_page
        rows = self._rows(
            f"""SELECT {self.ADMIN_USER_FIELDS},
                       MAX(COALESCE((SELECT MAX(r.created_at) FROM rounds r
                                     WHERE r.user_id = users.user_id), 0),
                           COALESCE((SELECT MAX(p.created_at) FROM plays p
                                     WHERE p.user_id = users.user_id), 0)) AS last_played
                FROM users
                ORDER BY last_played DESC, created_at DESC
                LIMIT ? OFFSET ?""",
            (per_page, offset),
        )
        return {"items": rows, "total": total, "page": page,
                "per_page": per_page, "pages": pages}

    def admin_set_balance(self, user_id: int, value: int) -> int:
        with self._lock:
            self._exec("UPDATE users SET balance = ? WHERE user_id = ?",
                       (max(0, int(value)), user_id))
            row = self._row("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            return row["balance"] if row else 0

    def admin_set_ban(self, user_id: int, banned: bool) -> None:
        self._exec("UPDATE users SET is_banned = ? WHERE user_id = ?",
                   (1 if banned else 0, user_id))

    def admin_set_role(self, user_id: int, role: str) -> None:
        self._exec("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))

    def admin_exists(self) -> bool:
        """Есть ли в базе хоть один админ или модератор."""
        row = self._row(
            "SELECT COUNT(*) AS c FROM users WHERE role IN ('admin', 'moderator')")
        return bool(row and int(row["c"]) > 0)

    def admin_reset_cooldowns(self, user_id: int) -> None:
        """Сбросить бонусы и колесо, чтобы админ мог выдать их повторно."""
        self._exec(
            "UPDATE users SET last_daily = 0, last_hourly = 0, last_spin = 0 "
            "WHERE user_id = ?", (user_id,))

    def admin_set_energy(self, user_id: int, value: int) -> int:
        value = max(0, int(value))
        self._exec("UPDATE users SET energy = ?, energy_at = ? WHERE user_id = ?",
                   (value, int(time.time()), user_id))
        return value

    def admin_log(self, admin_id: int, target_id: int | None, action: str,
                  detail: dict | None = None) -> None:
        self._exec(
            "INSERT INTO admin_actions (id, admin_id, target_id, action, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, admin_id, target_id, action,
             json.dumps(detail or {}, ensure_ascii=False), int(time.time())))

    def admin_actions(self, limit: int = 30) -> list[dict]:
        return self._rows(
            """SELECT a.*, ua.username AS admin_username,
                      ut.username AS target_username
               FROM admin_actions a
               LEFT JOIN users ua ON ua.user_id = a.admin_id
               LEFT JOIN users ut ON ut.user_id = a.target_id
               ORDER BY a.created_at DESC LIMIT ?""",
            (int(limit),),
        )

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

    def user_game_stats(self, user_id: int) -> list[dict]:
        rows: list[dict] = []
        mine_row = self._row(
            """SELECT COUNT(*) AS rounds,
                      COALESCE(SUM(bet), 0) AS wagered,
                      COALESCE(SUM(payout), 0) AS paid,
                      COALESCE(SUM(CASE WHEN payout > 0 THEN 1 ELSE 0 END), 0) AS wins
               FROM rounds WHERE user_id = ? AND status != 'active'""",
            (user_id,))
        if mine_row and mine_row["rounds"]:
            rows.append({
                "game": "mines", "title": "Сапёр", "icon": "💣",
                "rounds": mine_row["rounds"], "wagered": mine_row["wagered"],
                "paid": mine_row["paid"], "wins": mine_row["wins"],
            })
        for row in self._rows(
                """SELECT game, COUNT(*) AS rounds,
                          COALESCE(SUM(bet), 0) AS wagered,
                          COALESCE(SUM(payout), 0) AS paid,
                          COALESCE(SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END), 0) AS wins
                   FROM plays WHERE user_id = ? GROUP BY game""",
                (user_id,)):
            rows.append({
                "game": row["game"],
                "title": self.GAME_TITLES.get(row["game"], row["game"]),
                "icon": {"dice": "🎲", "wheel": "🎡", "crash": "📈"}.get(row["game"], "🎮"),
                "rounds": row["rounds"], "wagered": row["wagered"],
                "paid": row["paid"], "wins": row["wins"],
            })
        for row in rows:
            row["rtp"] = round((row["paid"] / row["wagered"]) * 100, 1) if row["wagered"] else 0.0
            row["winrate"] = round((row["wins"] / row["rounds"]) * 100, 1) if row["rounds"] else 0.0
        order = ["mines", "dice", "wheel", "crash"]
        rows.sort(key=lambda item: order.index(item["game"]) if item["game"] in order else 99)
        return rows

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

    def broadcast_ids(self) -> list[int]:
        rows = self._rows("SELECT user_id FROM users WHERE is_banned = 0")
        return [int(row["user_id"]) for row in rows]

    def admin_economy(self) -> dict:
        players = self._row("SELECT COUNT(*) AS c FROM users")
        balance = self._row("SELECT COALESCE(SUM(balance), 0) AS s FROM users")
        banned = self._row(
            "SELECT COUNT(*) AS c FROM users WHERE is_banned = 1")
        deposits = self._row(
            "SELECT COUNT(*) AS c, COALESCE(SUM(amount), 0) AS s FROM deposits "
            "WHERE status = 'active'")
        duels = self._row("SELECT COUNT(*) AS c FROM duels")
        duels_done = self._row(
            "SELECT COUNT(*) AS c FROM duels WHERE status = 'finished'")
        achievements = self._row("SELECT COUNT(*) AS c FROM user_achievements")
        return {
            "players": int(players["c"]) if players else 0,
            "balance": int(balance["s"]) if balance else 0,
            "banned": int(banned["c"]) if banned else 0,
            "deposits_count": int(deposits["c"]) if deposits else 0,
            "deposits_locked": int(deposits["s"]) if deposits else 0,
            "duels": int(duels["c"]) if duels else 0,
            "duels_finished": int(duels_done["c"]) if duels_done else 0,
            "achievements": int(achievements["c"]) if achievements else 0,
            "rates": self.currency_rates(),
            "taxes": {t: self.tax_rate(t) for t in
                      ("trade", "guild_market", "premium", "withdraw")},
        }

    def admin_emit(self, user_id: int, amount: int, currency: str,
                   reason: str = "admin") -> int:
        col = {"gold": "cash_balance", "bank": "bank_balance",
               "credits": "credits", "gems": "gems"}.get(currency)
        if col is None:
            return 0
        self._ensure_economy_account(user_id)
        self.economy_transfer(user_id, currency, amount,
                              f"admin_emit:{reason}")
        return self.economy_balance(user_id, currency)

    def admin_set_rate(self, currency: str, rate: float) -> None:
        self.set_currency_rate(currency, max(0.01, rate))

    def admin_set_commission(self, tax_key: str, rate_pct: float) -> None:
        self.set_tax_rate(tax_key, max(0.0, min(50.0, rate_pct)))

    def admin_inflation(self, pct: float) -> dict:
        rates = self.currency_rates()
        changed = {}
        for cur, info in rates.items():
            if cur == "gold":
                continue
            new_rate = max(0.01, float(info["rate"]) * (1.0 - pct / 100.0))
            self.set_currency_rate(cur, new_rate)
            changed[cur] = new_rate
        return changed

    def admin_stock_volatility(self, symbol: str, vol: float) -> None:
        self._exec(
            "UPDATE stock_market SET volatility = ? WHERE symbol = ?",
            (max(0.01, min(0.5, vol)), symbol))

    def admin_grant_tokens(self, user_id: int, amount: int, reason: str) -> int:
        self.add_tokens(user_id, amount)
        self.token_log(user_id, amount, f"admin grant: {reason}")
        return self.tokens(user_id)

    def admin_action_ban(self, user_id: int, action: str | None = None) -> None:
        config = self._row("SELECT * FROM settings WHERE key = 'action_ban'")
        import json as _json
        bans = _json.loads(config["value"]) if config else {}
        if action is None:
            bans.pop(str(user_id), None)
        else:
            bans[str(user_id)] = action
        self._exec(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('action_ban', ?)",
            (_json.dumps(bans),))

    def admin_action_bans(self) -> dict:
        config = self._row("SELECT * FROM settings WHERE key = 'action_ban'")
        import json as _json
        return _json.loads(config["value"]) if config else {}

    def admin_is_action_banned(self, user_id: int, action: str) -> bool:
        bans = self.admin_action_bans()
        cur = bans.get(str(user_id))
        return bool(cur and cur == action)

    def admin_duels(self, limit: int = 8) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM duels ORDER BY created_at DESC LIMIT ?", (int(limit),))
        for row in rows:
            challenger = self.user(row["challenger_id"])
            opponent = self.user(row["opponent_id"])
            row["challenger"] = (challenger["username"] or challenger["first_name"]
                                 if challenger else str(row["challenger_id"]))
            row["opponent"] = (opponent["username"] or opponent["first_name"]
                               if opponent else str(row["opponent_id"]))
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
        if payout <= 0 and bet > 0:
            loss_amt = max(1, bet // 100)
            self.add_treasury(loss_amt)
            self.treasury_log("loss", user_id, loss_amt)

    # --- казна -----------------------------------------------------------
    def treasury(self) -> int:
        row = self._row("SELECT value FROM settings WHERE key = 'treasury'")
        try:
            return int(row["value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    def add_treasury(self, delta: int) -> int:
        if delta == 0:
            return self.treasury()
        self._exec(
            "INSERT INTO settings (key, value) VALUES ('treasury', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = "
            "CAST(CAST(settings.value AS INTEGER) + ? AS TEXT)",
            (str(max(0, delta)), delta))
        return self.treasury()

    def take_treasury(self) -> int:
        total = self.treasury()
        if total <= 0:
            return 0
        self._exec("UPDATE settings SET value = '0' WHERE key = 'treasury'")
        return total

    def treasury_log(self, kind: str, user_id: int | None, amount: int) -> None:
        self._exec(
            "INSERT INTO treasury_history (kind, user_id, amount, created_at) "
            "VALUES (?, ?, ?, ?)", (kind, user_id, amount, int(time.time())))

    def treasury_history(self, limit: int = 30) -> list[dict]:
        return self._rows(
            "SELECT th.kind, th.user_id, th.amount, th.created_at, "
            "u.username, u.first_name "
            "FROM treasury_history th LEFT JOIN users u ON u.user_id = th.user_id "
            "ORDER BY th.id DESC LIMIT ?", (int(limit),))

    def treasury_contributors(self, limit: int = 10) -> list[dict]:
        return self._rows(
            "SELECT th.user_id, SUM(th.amount) AS total, "
            "MAX(u.username) AS username, MAX(u.first_name) AS first_name "
            "FROM treasury_history th LEFT JOIN users u ON u.user_id = th.user_id "
            "WHERE th.kind IN ('loss', 'donate') AND th.user_id IS NOT NULL "
            "GROUP BY th.user_id ORDER BY total DESC LIMIT ?", (int(limit),))

    def treasury_losers(self, limit: int = 10) -> list[dict]:
        return self._rows(
            "SELECT p.user_id, SUM(p.bet) AS total_lost, COUNT(*) AS plays, "
            "MAX(u.username) AS username, MAX(u.first_name) AS first_name "
            "FROM plays p LEFT JOIN users u ON u.user_id = p.user_id "
            "WHERE p.win = 0 GROUP BY p.user_id "
            "ORDER BY total_lost DESC LIMIT ?", (int(limit),))

    def giveaways(self) -> list[dict]:
        return self._rows("SELECT user_id, amount, created_at "
                          "FROM giveaway_entries ORDER BY amount DESC")

    def giveaway_add(self, user_id: int, amount: int) -> bool:
        changed = self._exec(
            """INSERT INTO giveaway_entries (user_id, amount, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET amount = amount + ?""",
            (user_id, amount, int(time.time()), amount))
        return bool(changed)

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

    def hour_claimed_quests(self, user_id: int, hour: str) -> set[str]:
        rows = self._rows(
            "SELECT quest FROM hour_quest_claims WHERE user_id = ? AND hour = ?",
            (user_id, hour))
        return {row["quest"] for row in rows}

    def claim_hour_quest(self, user_id: int, hour: str, quest: str) -> bool:
        changed = self._exec(
            """INSERT INTO hour_quest_claims (user_id, hour, quest, created_at)
               VALUES (?, ?, ?, ?) ON CONFLICT (user_id, hour, quest) DO NOTHING""",
            (user_id, hour, quest, int(time.time())),
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

    # --- блэкджек --------------------------------------------------------
    def create_bj(self, round_id: str, user_id: int, bet: int, deck: list[dict],
                  player: list[dict], dealer: list[dict]) -> None:
        self._exec(
            """INSERT INTO bj_rounds (id, user_id, bet, deck, player, dealer,
                   status, doubled, payout, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', 0, 0, ?)""",
            (round_id, user_id, bet, json.dumps(deck), json.dumps(player),
             json.dumps(dealer), int(time.time())))

    def bj_round(self, round_id: str) -> dict | None:
        return self._hydrate_bj(
            self._row("SELECT * FROM bj_rounds WHERE id = ?", (round_id,)))

    def active_bj(self, user_id: int) -> dict | None:
        return self._hydrate_bj(self._row(
            "SELECT * FROM bj_rounds WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1", (user_id,)))

    def expire_bj(self, round_id: str) -> int:
        """Закрывает зависшую партию «21» и возвращает ставку (или 0)."""
        row = self._row("SELECT bet FROM bj_rounds WHERE id = ? AND status = 'active'",
                        (round_id,))
        if not row:
            return 0
        bet = int(row["bet"])
        self._exec(
            "UPDATE bj_rounds SET status = 'expired', payout = ?, finished_at = ? "
            "WHERE id = ? AND status = 'active'", (bet, int(time.time()), round_id))
        check = self._row("SELECT status FROM bj_rounds WHERE id = ?", (round_id,))
        return bet if check and check["status"] == "expired" else 0

    @staticmethod
    def _hydrate_bj(row: dict | None) -> dict | None:
        if not row:
            return None
        for key in ("deck", "player", "dealer"):
            row[key] = json.loads(row[key])
        row["doubled"] = bool(row.get("doubled"))
        return row

    def update_bj(self, round_id: str, player: list[dict], dealer: list[dict],
                  status: str, payout: int, doubled: bool = False) -> None:
        finished = int(time.time()) if status != "active" else None
        self._exec(
            """UPDATE bj_rounds SET player = ?, dealer = ?, status = ?, payout = ?,
                   doubled = ?, finished_at = ? WHERE id = ?""",
            (json.dumps(player), json.dumps(dealer), status, payout,
             1 if doubled else 0, finished, round_id))

    # --- переводы --------------------------------------------------------
    def make_transfer(self, transfer_id: str, from_id: int, to_id: int,
                      amount: int) -> None:
        self._exec(
            """INSERT INTO transfers (id, from_id, to_id, amount, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (transfer_id, from_id, to_id, amount, int(time.time())))
        self.add_balance(from_id, -amount)
        self.add_balance(to_id, amount)

    def transfers(self, user_id: int, limit: int = 10) -> list[dict]:
        return self._rows(
            """SELECT * FROM transfers WHERE from_id = ? OR to_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, user_id, limit))

    def daily_transfer_sent(self, user_id: int) -> int:
        start = int(time.time()) // 86400 * 86400
        row = self._row(
            """SELECT COALESCE(SUM(amount), 0) AS total
               FROM transfers WHERE from_id = ? AND created_at >= ?""",
            (user_id, start))
        return int(row["total"] or 0) if row else 0

    # --- промокоды -------------------------------------------------------
    def create_promo(self, code: str, amount: int, max_uses: int = 0,
                     budget: int = 0, per_user: int = 1,
                     expires_at: int | None = None, note: str = "",
                     currency: str = "mcoin") -> None:
        self._exec(
            """INSERT INTO promo_codes (code, amount, max_uses, used, budget, spent,
                   per_user, active, expires_at, note, currency, created_at)
               VALUES (?, ?, ?, 0, ?, 0, ?, 1, ?, ?, ?, ?)""",
            (code, amount, max_uses, budget, per_user, expires_at, note,
             currency, int(time.time())))

    def promo(self, code: str) -> dict | None:
        return self._row("SELECT * FROM promo_codes WHERE code = ?", (code,))

    def promos(self, limit: int = 20) -> list[dict]:
        return self._rows(
            "SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT ?", (limit,))

    def promo_deactivate(self, code: str) -> bool:
        return bool(self._exec(
            "UPDATE promo_codes SET active = 0 WHERE code = ?", (code,)))

    def delete_promo(self, code: str) -> bool:
        self._exec("DELETE FROM promo_claims WHERE code = ?", (code,))
        return bool(self._exec("DELETE FROM promo_codes WHERE code = ?", (code,)))

    def promo_user_claims(self, code: str, user_id: int) -> int:
        row = self._row(
            "SELECT COUNT(*) AS c FROM promo_claims WHERE code = ? AND user_id = ?",
            (code, user_id))
        return int(row["c"]) if row else 0

    def claim_promo(self, code: str, user_id: int, now: int) -> tuple[str, int]:
        promo = self.promo(code)
        if not promo:
            return "not_found", 0
        if not int(promo["active"]):
            return "inactive", 0
        if promo["expires_at"] and int(promo["expires_at"]) < now:
            return "expired", 0
        amount = int(promo["amount"])
        if self.promo_user_claims(code, user_id) >= max(1, int(promo["per_user"])):
            return "already", 0

        sql = ("UPDATE promo_codes SET used = used + 1, spent = spent + ? "
               "WHERE code = ? AND active = 1")
        params: list = [amount, code]
        if int(promo["max_uses"]) > 0:
            sql += " AND used < max_uses"
        if int(promo["budget"]) > 0:
            sql += " AND spent + ? <= budget"
            params.append(amount)
        if not self._exec(sql, tuple(params)):
            return "exhausted", 0

        try:
            self._exec(
                """INSERT INTO promo_claims (code, user_id, amount, created_at)
                   VALUES (?, ?, ?, ?)""",
                (code, user_id, amount, now))
        except Exception:
            self._exec(
                "UPDATE promo_codes SET used = used - 1, spent = spent - ? "
                "WHERE code = ?", (amount, code))
            return "already", 0

        currency = str(promo.get("currency") or "mcoin")
        if currency == "gmpoint":
            self.add_gmpoint(user_id, amount)
        else:
            self.add_balance(user_id, amount)
        return "ok", amount

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

    # --- рыбалка ---------------------------------------------------------
    def _fish_table(self) -> None:
        if getattr(self, "_fish_ready", False):
            return
        self._exec(
            """CREATE TABLE IF NOT EXISTS fish (
                   id         TEXT PRIMARY KEY,
                   user_id    INTEGER NOT NULL,
                   species    TEXT NOT NULL,
                   name       TEXT NOT NULL,
                   rarity     TEXT NOT NULL,
                   weight_g   INTEGER NOT NULL,
                   price      INTEGER NOT NULL,
                   sold       INTEGER NOT NULL DEFAULT 0,
                   created_at INTEGER NOT NULL
               )""")
        self._exec("CREATE INDEX IF NOT EXISTS idx_fish_user ON fish(user_id, sold)")
        self._fish_ready = True

    def add_fish(self, fish_id: str, user_id: int, fish: dict) -> None:
        self._fish_table()
        self._exec(
            """INSERT INTO fish (id, user_id, species, name, rarity, weight_g,
                   price, sold, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (fish_id, user_id, fish["key"], fish["name"], fish["rarity"],
             int(fish["weight_g"]), int(fish["price"]), int(time.time())))

    def fish_list(self, user_id: int, sold: int = 0) -> list[dict]:
        self._fish_table()
        return self._rows(
            "SELECT * FROM fish WHERE user_id = ? AND sold = ? "
            "ORDER BY created_at DESC", (user_id, sold))

    def fish_stats(self, user_id: int) -> dict:
        self._fish_table()
        row = self._row(
            "SELECT COUNT(*) AS c, COALESCE(MAX(weight_g), 0) AS w "
            "FROM fish WHERE user_id = ?", (user_id,))
        return {"count": int(row["c"]) if row else 0,
                "best_weight": int(row["w"]) if row else 0}

    def sell_fish(self, user_id: int, fish_id: str) -> int | None:
        self._fish_table()
        row = self._row(
            "SELECT price FROM fish WHERE id = ? AND user_id = ? AND sold = 0",
            (fish_id, user_id))
        if not row:
            return None
        if not self._exec(
                "UPDATE fish SET sold = 1 WHERE id = ? AND user_id = ? AND sold = 0",
                (fish_id, user_id)):
            return None
        price = int(row["price"])
        self.add_balance(user_id, price)
        return price

    def sell_all_fish(self, user_id: int) -> tuple[int, int]:
        self._fish_table()
        rows = self.fish_list(user_id, 0)
        if not rows:
            return 0, 0
        total = sum(int(item["price"]) for item in rows)
        self._exec("UPDATE fish SET sold = 1 WHERE user_id = ? AND sold = 0",
                   (user_id,))
        self.add_balance(user_id, total)
        return total, len(rows)

    # --- автомобили ------------------------------------------------------
    def car_add(self, user_id: int, model: str, price: int, fuel_max: int) -> int:
        """Купить машину: списать price и вернуть id новой записи (0 при нехватке средств)."""
        balance = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
        if not balance or int(balance["balance"]) < price:
            return 0
        self.add_balance(user_id, -price)
        self._exec(
            """INSERT INTO cars (user_id, model, fuel, fuel_max, rent_until, bought_at)
               VALUES (?, ?, 0, ?, 0, ?)""",
            (user_id, model, int(fuel_max), int(time.time())))
        row = self._row("SELECT MAX(id) AS id FROM cars WHERE user_id = ?",
                        (user_id,))
        return int(row["id"]) if row and row["id"] else 0

    def cars(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM cars WHERE user_id = ? ORDER BY id ASC", (user_id,))

    def car(self, user_id: int, car_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM cars WHERE id = ? AND user_id = ?", (car_id, user_id))

    def car_fuel(self, car_id: int, user_id: int, qty: int, price: int) -> bool:
        """Заправить машину: списать цену топлива, вернуть True при успехе."""
        balance = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
        if not balance or int(balance["balance"]) < price:
            return False
        self.add_balance(user_id, -price)
        self._exec(
            "UPDATE cars SET fuel = MAX(0, MIN(fuel + ?, fuel_max)) "
            "WHERE id = ? AND user_id = ?",
            (qty, car_id, user_id))
        return True

    def car_set_rent(self, car_id: int, user_id: int, until: int) -> bool:
        self._exec(
            "UPDATE cars SET rent_until = ? WHERE id = ? AND user_id = ?",
            (until, car_id, user_id))
        return True

    def car_sell(self, car_id: int, user_id: int, refund: int) -> bool:
        row = self._row("SELECT model FROM cars WHERE id = ? AND user_id = ?",
                        (car_id, user_id))
        if not row:
            return False
        self._exec("DELETE FROM cars WHERE id = ? AND user_id = ?",
                   (car_id, user_id))
        self.add_balance(user_id, refund)
        return True

    # --- яхты -------------------------------------------------------------
    def yacht_add(self, user_id: int, model: str, price: int, fuel_max: int) -> int:
        """Купить яхту: списать price и вернуть id новой записи (0 при нехватке средств)."""
        balance = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
        if not balance or int(balance["balance"]) < price:
            return 0
        self.add_balance(user_id, -price)
        self._exec(
            """INSERT INTO yachts (user_id, model, fuel, fuel_max,
                   cruise_until, fish_at, bought_at)
               VALUES (?, ?, 0, ?, 0, 0, ?)""",
            (user_id, model, int(fuel_max), int(time.time())))
        row = self._row("SELECT MAX(id) AS id FROM yachts WHERE user_id = ?",
                        (user_id,))
        return int(row["id"]) if row and row["id"] else 0

    def yachts(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM yachts WHERE user_id = ? ORDER BY id ASC", (user_id,))

    def yacht(self, user_id: int, yacht_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM yachts WHERE id = ? AND user_id = ?",
            (yacht_id, user_id))

    def yacht_fuel(self, yacht_id: int, user_id: int, qty: int, price: int) -> bool:
        """Заправить яхту: списать стоимость топлива."""
        balance = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
        if not balance or int(balance["balance"]) < price:
            return False
        if price:
            self.add_balance(user_id, -price)
        self._exec(
            "UPDATE yachts SET fuel = MAX(0, MIN(fuel + ?, fuel_max)) "
            "WHERE id = ? AND user_id = ?", (qty, yacht_id, user_id))
        return True

    def yacht_set_cruise(self, yacht_id: int, user_id: int, until: int) -> None:
        self._exec(
            "UPDATE yachts SET cruise_until = ? WHERE id = ? AND user_id = ?",
            (until, yacht_id, user_id))

    def yacht_set_fish(self, yacht_id: int, user_id: int, at: int) -> None:
        self._exec(
            "UPDATE yachts SET fish_at = ? WHERE id = ? AND user_id = ?",
            (at, yacht_id, user_id))

    def yacht_sell(self, yacht_id: int, user_id: int, refund: int) -> bool:
        row = self._row("SELECT model FROM yachts WHERE id = ? AND user_id = ?",
                        (yacht_id, user_id))
        if not row:
            return False
        self._exec("DELETE FROM yachts WHERE id = ? AND user_id = ?",
                   (yacht_id, user_id))
        self.add_balance(user_id, refund)
        return True

    # --- бизнесы ----------------------------------------------------------
    def business_add(self, user_id: int, model: str, price: int) -> int:
        """Купить бизнес: вернуть id записи (0 при нехватке средств)."""
        balance = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
        if not balance or int(balance["balance"]) < price:
            return 0
        self.add_balance(user_id, -price)
        self._exec(
            """INSERT INTO businesses (user_id, model, last_collect, bought_at)
               VALUES (?, ?, 0, ?)""",
            (user_id, model, int(time.time())))
        row = self._row("SELECT MAX(id) AS id FROM businesses WHERE user_id = ?",
                        (user_id,))
        return int(row["id"]) if row and row["id"] else 0

    def businesses(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM businesses WHERE user_id = ? ORDER BY id ASC",
            (user_id,))

    def business(self, user_id: int, biz_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM businesses WHERE id = ? AND user_id = ?",
            (biz_id, user_id))

    def business_set_collect(self, biz_id: int, user_id: int, ts: int) -> None:
        self._exec(
            "UPDATE businesses SET last_collect = ? WHERE id = ? AND user_id = ?",
            (ts, biz_id, user_id))

    def business_sell(self, biz_id: int, user_id: int, refund: int) -> bool:
        row = self._row("SELECT model FROM businesses WHERE id = ? AND user_id = ?",
                        (biz_id, user_id))
        if not row:
            return False
        self._exec("DELETE FROM businesses WHERE id = ? AND user_id = ?",
                   (biz_id, user_id))
        self.add_balance(user_id, refund)
        return True

    # --- майнинг-ферма ----------------------------------------------------
    def mining(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM mining WHERE user_id = ?", (user_id,))

    def mining_ensure(self, user_id: int, slots: int, now: int) -> dict:
        row = self.mining(user_id)
        if row:
            return row
        self._exec(
            """INSERT OR IGNORE INTO mining
               (user_id, gpus, slots, last_collect, bought_at)
               VALUES (?, 0, ?, ?, ?)""",
            (user_id, slots, now, now))
        return self.mining(user_id)

    def mining_set_time(self, user_id: int, ts: int) -> None:
        self._exec("UPDATE mining SET last_collect = ? WHERE user_id = ?",
                   (ts, user_id))

    def mining_set_btc(self, user_id: int, btc: float, ts: int) -> None:
        self._exec("UPDATE mining SET btc = ?, last_collect = ? WHERE user_id = ?",
                   (float(btc), ts, user_id))

    def mining_set_power(self, user_id: int, until: int, ts: int) -> None:
        self._exec(
            "UPDATE mining SET power_until = ?, last_collect = ? WHERE user_id = ?",
            (int(until), ts, user_id))

    def clan_bonus(self, user_id: int) -> int:
        """Процент к прибыли фермы за членство в клане."""
        row = self._row("SELECT 1 AS ok FROM clan_members WHERE user_id = ?",
                        (user_id,))
        return 3 if row else 0

    def mining_buy_gpu(self, user_id: int, price: int, now: int) -> str:
        row = self.mining(user_id)
        if not row:
            return "no"
        if int(row["gpus"]) >= int(row["slots"]):
            return "slots"
        bal = self._row("SELECT balance FROM users WHERE user_id = ?",
                        (user_id,))
        if not bal or int(bal["balance"]) < price:
            return "money"
        self.add_balance(user_id, -price)
        self._exec(
            "UPDATE mining SET gpus = gpus + 1, last_collect = ? WHERE user_id = ?",
            (now, user_id))
        return "ok"

    def mining_buy_slots(self, user_id: int, add: int, price: int, cap: int,
                         now: int) -> str:
        row = self.mining(user_id)
        if not row:
            return "no"
        if int(row["slots"]) >= cap:
            return "max"
        bal = self._row("SELECT balance FROM users WHERE user_id = ?",
                        (user_id,))
        if not bal or int(bal["balance"]) < price:
            return "money"
        new_slots = min(int(row["slots"]) + add, cap)
        self.add_balance(user_id, -price)
        self._exec("UPDATE mining SET slots = ?, last_collect = ? WHERE user_id = ?",
                   (new_slots, now, user_id))
        return "ok"

    # --- мини-игра «рыбалка» ---------------------------------------------
    def fish_game_start(self, user_id: int, yacht_id: int, cell: int,
                        now: int) -> None:
        self._exec(
            """INSERT INTO fish_game (user_id, yacht_id, cell, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET
                   yacht_id = excluded.yacht_id,
                   cell = excluded.cell,
                   created_at = excluded.created_at""",
            (user_id, yacht_id, cell, now))

    def fish_game_get(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM fish_game WHERE user_id = ?",
                         (user_id,))

    def fish_game_clear(self, user_id: int) -> None:
        self._exec("DELETE FROM fish_game WHERE user_id = ?", (user_id,))

    # --- кланы -----------------------------------------------------------
    def create_clan(self, clan_id: str, name: str, tag: str, owner_id: int,
                    description: str = "", logo: str = "") -> bool:
        try:
            self._exec(
                """INSERT INTO clans (id, name, tag, owner_id, description, logo,
                       xp, level, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?)""",
                (clan_id, name, tag, owner_id, description, logo, int(time.time())))
        except Exception:
            return False
        try:
            self._exec(
                """INSERT INTO clan_members (clan_id, user_id, role, joined_at)
                   VALUES (?, ?, 'owner', ?)""",
                (clan_id, owner_id, int(time.time())))
        except Exception:
            return False
        return True

    def clan(self, clan_id: str) -> dict | None:
        return self._row("SELECT * FROM clans WHERE id = ?", (clan_id,))

    def clan_by_name(self, name: str) -> dict | None:
        return self._row("SELECT * FROM clans WHERE lower(name) = lower(?)",
                         (name,))

    def user_clan(self, user_id: int) -> dict | None:
        return self._row(
            """SELECT c.*, m.role AS my_role FROM clans c
               JOIN clan_members m ON m.clan_id = c.id
               WHERE m.user_id = ? LIMIT 1""", (user_id,))

    def clan_members(self, clan_id: str, limit: int = 100) -> list[dict]:
        return self._rows(
            """SELECT m.*, u.username, u.first_name, u.balance, u.xp
               FROM clan_members m
               LEFT JOIN users u ON u.user_id = m.user_id
               WHERE m.clan_id = ? ORDER BY
                 CASE m.role WHEN 'owner' THEN 0 WHEN 'officer' THEN 1 ELSE 2 END,
                 m.joined_at ASC LIMIT ?""", (clan_id, limit))

    def clan_count(self, clan_id: str) -> int:
        row = self._row("SELECT COUNT(*) AS c FROM clan_members WHERE clan_id = ?",
                        (clan_id,))
        return int(row["c"]) if row else 0

    def add_clan_member(self, clan_id: str, user_id: int, role: str = "member") -> bool:
        try:
            self._exec(
                """INSERT INTO clan_members (clan_id, user_id, role, joined_at)
                   VALUES (?, ?, ?, ?)""",
                (clan_id, user_id, role, int(time.time())))
            return True
        except Exception:
            return False

    def remove_clan_member(self, clan_id: str, user_id: int) -> None:
        self._exec("DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?",
                   (clan_id, user_id))

    def set_clan_role(self, clan_id: str, user_id: int, role: str) -> None:
        self._exec("UPDATE clan_members SET role = ? WHERE clan_id = ? AND user_id = ?",
                   (role, clan_id, user_id))

    def update_clan(self, clan_id: str, description: str | None = None,
                    logo: str | None = None) -> None:
        if description is not None:
            self._exec("UPDATE clans SET description = ? WHERE id = ?",
                       (description, clan_id))
        if logo is not None:
            self._exec("UPDATE clans SET logo = ? WHERE id = ?", (logo, clan_id))

    def add_clan_xp(self, clan_id: str, amount: int) -> None:
        self._exec("UPDATE clans SET xp = xp + ? WHERE id = ?", (amount, clan_id))

    def delete_clan(self, clan_id: str) -> None:
        self._exec("DELETE FROM clan_messages WHERE clan_id = ?", (clan_id,))
        self._exec("DELETE FROM clan_requests WHERE clan_id = ?", (clan_id,))
        self._exec("DELETE FROM clan_invites WHERE clan_id = ?", (clan_id,))
        self._exec("DELETE FROM clan_members WHERE clan_id = ?", (clan_id,))
        self._exec("DELETE FROM clans WHERE id = ?", (clan_id,))

    def clan_request(self, clan_id: str, user_id: int) -> bool:
        try:
            self._exec(
                """INSERT INTO clan_requests (clan_id, user_id, message, created_at)
                   VALUES (?, ?, '', ?)""",
                (clan_id, user_id, int(time.time())))
            return True
        except Exception:
            return False

    def clan_requests(self, clan_id: str) -> list[dict]:
        return self._rows(
            """SELECT r.*, u.username, u.first_name FROM clan_requests r
               LEFT JOIN users u ON u.user_id = r.user_id
               WHERE r.clan_id = ? ORDER BY r.created_at ASC""", (clan_id,))

    def clan_request_by_user(self, clan_id: str, user_id: int) -> bool:
        row = self._row(
            "SELECT 1 AS x FROM clan_requests WHERE clan_id = ? AND user_id = ?",
            (clan_id, user_id))
        return bool(row)

    def remove_clan_request(self, clan_id: str, user_id: int) -> None:
        self._exec("DELETE FROM clan_requests WHERE clan_id = ? AND user_id = ?",
                   (clan_id, user_id))

    def clan_invite(self, clan_id: str, user_id: int) -> bool:
        try:
            self._exec(
                """INSERT INTO clan_invites (clan_id, user_id, created_at)
                   VALUES (?, ?, ?)""",
                (clan_id, user_id, int(time.time())))
            return True
        except Exception:
            return False

    def clan_invites_for(self, user_id: int) -> list[dict]:
        return self._rows(
            """SELECT i.*, c.name AS clan_name, c.tag AS clan_tag
               FROM clan_invites i JOIN clans c ON c.id = i.clan_id
               WHERE i.user_id = ? ORDER BY i.created_at DESC""", (user_id,))

    def remove_clan_invite(self, clan_id: str, user_id: int) -> None:
        self._exec("DELETE FROM clan_invites WHERE clan_id = ? AND user_id = ?",
                   (clan_id, user_id))

    def clan_message(self, msg_id: str, clan_id: str, user_id: int, text: str) -> None:
        self._exec(
            """INSERT INTO clan_messages (id, clan_id, user_id, text, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (msg_id, clan_id, user_id, text, int(time.time())))

    def clan_messages(self, clan_id: str, limit: int = 50) -> list[dict]:
        return self._rows(
            """SELECT m.*, u.username, u.first_name FROM clan_messages m
               LEFT JOIN users u ON u.user_id = m.user_id
               WHERE m.clan_id = ? ORDER BY m.created_at DESC LIMIT ?""",
            (clan_id, limit))

    def top_clans(self, limit: int = 20) -> list[dict]:
        return self._rows(
            """SELECT c.*, COUNT(m.user_id) AS members
               FROM clans c LEFT JOIN clan_members m ON m.clan_id = c.id
               GROUP BY c.id ORDER BY c.xp DESC LIMIT ?""", (limit,))

    # --- друзья ----------------------------------------------------------
    def friends(self, user_id: int) -> list[dict]:
        rows = self._rows(
            """SELECT f.friend_id AS user_id, 'friend' AS rel, u.username, u.first_name,
                      u.balance, u.xp
               FROM friends f JOIN users u ON u.user_id = f.friend_id
               WHERE f.user_id = ? AND f.status = 'accepted'""", (user_id,))
        rows += self._rows(
            """SELECT f.user_id AS user_id, 'friend' AS rel, u.username, u.first_name,
                      u.balance, u.xp
               FROM friends f JOIN users u ON u.user_id = f.user_id
               WHERE f.friend_id = ? AND f.status = 'accepted'""", (user_id,))
        seen: set[int] = set()
        out: list[dict] = []
        for row in rows:
            if row["user_id"] in seen:
                continue
            seen.add(row["user_id"])
            out.append(row)
        return out

    def are_friends(self, a: int, b: int) -> bool:
        row = self._row(
            "SELECT 1 AS x FROM friends WHERE status = 'accepted' AND "
            "((user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?))",
            (a, b, b, a))
        return bool(row)

    def add_friend(self, a: int, b: int) -> bool:
        try:
            self._exec(
                """INSERT INTO friends (user_id, friend_id, status, created_at, updated_at)
                   VALUES (?, ?, 'accepted', ?, ?)""",
                (a, b, int(time.time()), int(time.time())))
            self._exec(
                """INSERT INTO friends (user_id, friend_id, status, created_at, updated_at)
                   VALUES (?, ?, 'accepted', ?, ?)""",
                (b, a, int(time.time()), int(time.time())))
            return True
        except Exception:
            return False

    def remove_friend(self, a: int, b: int) -> None:
        self._exec("DELETE FROM friends WHERE user_id = ? AND friend_id = ?", (a, b))
        self._exec("DELETE FROM friends WHERE user_id = ? AND friend_id = ?", (b, a))

    def friend_request(self, from_id: int, to_id: int) -> bool:
        try:
            self._exec(
                """INSERT INTO friend_requests (from_id, to_id, created_at)
                   VALUES (?, ?, ?)""",
                (from_id, to_id, int(time.time())))
            return True
        except Exception:
            return False

    def friend_requests(self, user_id: int) -> list[dict]:
        return self._rows(
            """SELECT r.from_id, r.created_at, u.username, u.first_name
               FROM friend_requests r JOIN users u ON u.user_id = r.from_id
               WHERE r.to_id = ? ORDER BY r.created_at DESC""", (user_id,))

    def has_friend_request(self, from_id: int, to_id: int) -> bool:
        row = self._row(
            "SELECT 1 AS x FROM friend_requests WHERE from_id = ? AND to_id = ?",
            (from_id, to_id))
        return bool(row)

    def remove_friend_request(self, from_id: int, to_id: int) -> None:
        self._exec(
            "DELETE FROM friend_requests WHERE from_id = ? AND to_id = ?",
            (from_id, to_id))

    # --- маркетплейс -----------------------------------------------------
    def create_market_lot(self, lot_id: str, seller_id: int, item_type: str,
                          item: str, qty: int, price: int,
                          currency: str = "mcoin") -> None:
        self._exec(
            """INSERT INTO market_lots (id, seller_id, item_type, item, qty, price,
                   currency, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (lot_id, seller_id, item_type, item, qty, price, currency,
             int(time.time())))

    def market_lots(self, status: str = "active", limit: int = 50) -> list[dict]:
        return self._rows(
            """SELECT l.*, u.username AS seller_name FROM market_lots l
               LEFT JOIN users u ON u.user_id = l.seller_id
               WHERE l.status = ? ORDER BY l.created_at DESC LIMIT ?""",
            (status, limit))

    def market_lot(self, lot_id: str) -> dict | None:
        return self._row(
            """SELECT l.*, u.username AS seller_name FROM market_lots l
               LEFT JOIN users u ON u.user_id = l.seller_id
               WHERE l.id = ?""", (lot_id,))

    def close_market_lot(self, lot_id: str, buyer_id: int) -> bool:
        changed = self._exec(
            """UPDATE market_lots SET status = 'sold', buyer_id = ?, sold_at = ?
               WHERE id = ? AND status = 'active'""",
            (buyer_id, int(time.time()), lot_id))
        return bool(changed)

    def cancel_market_lot(self, lot_id: str, seller_id: int) -> bool:
        return bool(self._exec(
            "UPDATE market_lots SET status = 'cancelled' "
            "WHERE id = ? AND seller_id = ? AND status = 'active'",
            (lot_id, seller_id)))

    def market_history(self, limit: int = 30) -> list[dict]:
        return self._rows(
            """SELECT * FROM market_history ORDER BY created_at DESC LIMIT ?""",
            (limit,))

    def add_market_history(self, h_id: str, lot_id: str, seller_id: int,
                           buyer_id: int, item_type: str, item: str, qty: int,
                           price: int, currency: str) -> None:
        self._exec(
            """INSERT INTO market_history (id, lot_id, seller_id, buyer_id, item_type,
                   item, qty, price, currency, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (h_id, lot_id, seller_id, buyer_id, item_type, item, qty, price,
             currency, int(time.time())))

    # --- аукцион ---------------------------------------------------------
    def create_auction(self, lot_id: str, seller_id: int, item_type: str,
                       item: str, qty: int, start_price: int, min_step: int,
                       ends_at: int) -> None:
        self._exec(
            """INSERT INTO auction_lots (id, seller_id, item_type, item, qty,
                   start_price, min_step, ends_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (lot_id, seller_id, item_type, item, qty, start_price, min_step,
             ends_at, int(time.time())))

    def auction_lots(self, status: str = "active", limit: int = 50) -> list[dict]:
        return self._rows(
            """SELECT a.*, u.username AS seller_name FROM auction_lots a
               LEFT JOIN users u ON u.user_id = a.seller_id
               WHERE a.status = ? AND a.ends_at > ?
               ORDER BY a.ends_at ASC LIMIT ?""",
            (status, int(time.time()), limit))

    def auction_lot(self, lot_id: str) -> dict | None:
        return self._row(
            """SELECT a.*, u.username AS seller_name FROM auction_lots a
               LEFT JOIN users u ON u.user_id = a.seller_id
               WHERE a.id = ?""", (lot_id,))

    def place_bid(self, lot_id: str, user_id: int, amount: int) -> tuple[bool, str]:
        with self._lock:
            lot = self.auction_lot(lot_id)
            if not lot or lot["status"] != "active":
                return False, "not_found"
            if int(lot["ends_at"]) <= int(time.time()):
                return False, "ended"
            if user_id == int(lot["seller_id"]):
                return False, "self"
            current = int(lot["current_bid"] or lot["start_price"])
            min_step = int(lot["min_step"])
            if amount < current + min_step:
                return False, "low_bid"
            if self.user(user_id) and int(self.user(user_id) or {}).get("balance", 0) < amount:
                return False, "no_balance"
            self._exec(
                """UPDATE auction_lots SET current_bid = ?, bidder_id = ?,
                       bids = ? WHERE id = ? AND status = 'active'""",
                (amount, user_id,
                 json.dumps(json.loads(lot["bids"] or "[]") + [
                     {"user_id": user_id, "amount": amount,
                      "at": int(time.time())}]),
                 lot_id))
            prev = int(lot.get("bidder_id") or 0)
            if prev and prev != user_id:
                self.add_balance(prev, int(lot["current_bid"]))
            self.add_balance(user_id, -amount)
            return True, "ok"

    def close_auction(self, lot_id: str) -> dict | None:
        lot = self.auction_lot(lot_id)
        if not lot:
            return None
        if lot["status"] != "active":
            return lot
        if int(lot["current_bid"]) > 0 and int(lot.get("bidder_id") or 0):
            self._exec(
                """UPDATE auction_lots SET status = 'sold', finished_at = ?
                   WHERE id = ? AND status = 'active'""",
                (int(time.time()), lot_id))
        else:
            self._exec(
                """UPDATE auction_lots SET status = 'expired', finished_at = ?
                   WHERE id = ? AND status = 'active'""",
                (int(time.time()), lot_id))
        return self.auction_lot(lot_id)

    def expire_auctions(self, now: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM auction_lots WHERE status = 'active' AND ends_at <= ?",
            (now,))
        for lot in rows:
            self.close_auction(lot["id"])
        return rows

    # --- сезоны и лиги ---------------------------------------------------
    def create_season(self, season_id: str, name: str, starts_at: int,
                      ends_at: int) -> None:
        self._exec(
            """INSERT INTO seasons (id, name, starts_at, ends_at, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (season_id, name, starts_at, ends_at, int(time.time())))

    def current_season(self, now: int) -> dict | None:
        return self._row(
            """SELECT * FROM seasons WHERE status != 'finished'
               ORDER BY starts_at DESC LIMIT 1""", ())

    def create_league(self, league_id: str, season_id: str, name: str, icon: str,
                      min_xp: int, reward: int) -> None:
        self._exec(
            """INSERT INTO leagues (id, season_id, name, icon, min_xp, reward,
                   created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (league_id, season_id, name, icon, min_xp, reward, int(time.time())))

    def leagues(self, season_id: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM leagues WHERE season_id = ? ORDER BY min_xp ASC",
            (season_id,))

    def set_league_member(self, season_id: str, user_id: int, league_id: str) -> None:
        try:
            self._exec(
                """INSERT INTO league_members (season_id, user_id, league_id, points,
                       updated_at) VALUES (?, ?, ?, 0, ?)""",
                (season_id, user_id, league_id, int(time.time())))
        except Exception:
            pass

    def league_member(self, season_id: str, user_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM league_members WHERE season_id = ? AND user_id = ?",
            (season_id, user_id))

    def add_league_points(self, season_id: str, user_id: int, points: int) -> None:
        self._exec(
            "UPDATE league_members SET points = points + ?, updated_at = ? "
            "WHERE season_id = ? AND user_id = ?",
            (points, int(time.time()), season_id, user_id))

    def league_top(self, league_id: str, limit: int = 20) -> list[dict]:
        return self._rows(
            """SELECT m.*, u.username, u.first_name FROM league_members m
               LEFT JOIN users u ON u.user_id = m.user_id
               WHERE m.league_id = ? ORDER BY m.points DESC LIMIT ?""",
            (league_id, limit))

    def league_reward_claimed(self, season_id: str, user_id: int) -> bool:
        row = self._row(
            "SELECT 1 AS x FROM user_season_rewards WHERE season_id = ? AND user_id = ?",
            (season_id, user_id))
        return bool(row)

    def claim_league_reward(self, season_id: str, user_id: int, league_id: str) -> bool:
        try:
            self._exec(
                """INSERT INTO user_season_rewards (user_id, season_id, league_id,
                       claimed_at) VALUES (?, ?, ?, ?)""",
                (user_id, season_id, league_id, int(time.time())))
            return True
        except Exception:
            return False

    # --- достижения: прогресс --------------------------------------------
    def achievement_progress(self, user_id: int) -> dict:
        rows = self._rows(
            "SELECT * FROM achievement_progress WHERE user_id = ?", (user_id,))
        return {row["key"]: int(row["progress"]) for row in rows}

    def bump_achievement(self, user_id: int, key: str, delta: int = 1) -> int:
        with self._lock:
            self._exec(
                """INSERT INTO achievement_progress (user_id, key, progress, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (user_id, key)
                   DO UPDATE SET progress = achievement_progress.progress + ?,
                                 updated_at = ?""",
                (user_id, key, delta, int(time.time()), delta, int(time.time())))
            row = self._row(
                "SELECT progress FROM achievement_progress WHERE user_id = ? AND key = ?",
                (user_id, key))
            return int(row["progress"]) if row else delta

    # --- автоигра --------------------------------------------------------
    def create_auto_round(self, round_id: str, user_id: int, game: str,
                          strategy: str, bet: int, rounds_max: int,
                          target: float) -> None:
        self._exec(
            """INSERT INTO auto_rounds (id, user_id, game, strategy, bet,
                   rounds_done, rounds_max, target, status, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'active', ?)""",
            (round_id, user_id, game, strategy, bet, rounds_max, target,
             int(time.time())))

    def auto_rounds(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM auto_rounds WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 20", (user_id,))

    def auto_round(self, round_id: str) -> dict | None:
        return self._row("SELECT * FROM auto_rounds WHERE id = ?", (round_id,))

    def bump_auto_round(self, round_id: str) -> None:
        self._exec(
            "UPDATE auto_rounds SET rounds_done = rounds_done + 1 WHERE id = ?",
            (round_id,))

    def stop_auto_round(self, round_id: str, finished: bool = True) -> None:
        self._exec(
            "UPDATE auto_rounds SET status = ?, finished_at = ? WHERE id = ?",
            ("finished" if finished else "cancelled", int(time.time()), round_id))

    # --- турниры ---------------------------------------------------------
    def create_tournament(self, tour_id: str, name: str, kind: str, prize: int,
                          entry_fee: int, min_bet: int, starts_at: int,
                          ends_at: int) -> None:
        self._exec(
            """INSERT INTO tournaments (id, name, kind, prize, entry_fee, min_bet,
                   starts_at, ends_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (tour_id, name, kind, prize, entry_fee, min_bet, starts_at, ends_at,
             int(time.time())))

    def tournaments(self, status: str | None = None, limit: int = 20) -> list[dict]:
        if status:
            return self._rows(
                "SELECT * FROM tournaments WHERE status = ? "
                "ORDER BY ends_at ASC LIMIT ?", (status, limit))
        return self._rows(
            "SELECT * FROM tournaments WHERE status != 'finished' "
            "ORDER BY ends_at ASC LIMIT ?", (limit,))

    def tournament(self, tour_id: str) -> dict | None:
        return self._row("SELECT * FROM tournaments WHERE id = ?", (tour_id,))

    def join_tournament(self, tour_id: str, user_id: int) -> bool:
        try:
            self._exec(
                """INSERT INTO tournament_players (tournament_id, user_id, score,
                       best_bet, joined_at) VALUES (?, ?, 0, 0, ?)""",
                (tour_id, user_id, int(time.time())))
            return True
        except Exception:
            return False

    def tournament_players(self, tour_id: str, limit: int = 50) -> list[dict]:
        return self._rows(
            """SELECT p.*, u.username, u.first_name FROM tournament_players p
               LEFT JOIN users u ON u.user_id = p.user_id
               WHERE p.tournament_id = ? ORDER BY p.score DESC LIMIT ?""",
            (tour_id, limit))

    def tournament_bump(self, tour_id: str, user_id: int, delta: int,
                        best_bet: int) -> None:
        self._exec(
            """UPDATE tournament_players SET score = score + ?, best_bet = ?,
                   finished_at = ? WHERE tournament_id = ? AND user_id = ?""",
            (delta, best_bet, int(time.time()), tour_id, user_id))

    # --- уведомления -----------------------------------------------------
    def notify(self, user_id: int, kind: str, title: str, text: str = "",
               meta: dict | None = None) -> None:
        self._exec(
            """INSERT INTO notifications (id, user_id, kind, title, text, meta,
                   is_read, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (str(uuid.uuid4()), user_id, kind, title, text,
             json.dumps(meta or {}), int(time.time())))

    def notifications(self, user_id: int, limit: int = 30) -> list[dict]:
        return self._rows(
            "SELECT * FROM notifications WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    def unread_notifications(self, user_id: int) -> int:
        row = self._row(
            "SELECT COUNT(*) AS c FROM notifications "
            "WHERE user_id = ? AND is_read = 0", (user_id,))
        return int(row["c"]) if row else 0

    def read_notifications(self, user_id: int) -> None:
        self._exec("UPDATE notifications SET is_read = 1 WHERE user_id = ?",
                   (user_id,))

    # --- виртуальные фишки (демо-режим) ---------------------------------
    def virtual_chips(self, user_id: int) -> int:
        row = self._row("SELECT chips FROM virtual_chips WHERE user_id = ?",
                        (user_id,))
        return int(row["chips"]) if row else 0

    def add_virtual_chips(self, user_id: int, delta: int) -> int:
        self._exec(
            """INSERT INTO virtual_chips (user_id, chips, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (user_id)
               DO UPDATE SET chips = virtual_chips.chips + ?, updated_at = ?""",
            (user_id, delta, int(time.time()), delta, int(time.time())))
        return self.virtual_chips(user_id)

    # --- боты-профили ----------------------------------------------------
    def bot_profiles(self) -> list[dict]:
        return self._rows("SELECT * FROM bot_profiles ORDER BY balance DESC")

    def ensure_bots(self) -> None:
        if self.bot_profiles():
            return
        seeds = [
            ("bot_alex", "Alex", "🔥", 14, 82000, 0.5, "high"),
            ("bot_mila", "Mila", "🦊", 9, 41000, 0.4, "medium"),
            ("bot_igor", "Igor", "⚙️", 21, 155000, 0.55, "high"),
            ("bot_kate", "Kate", "🎀", 6, 22000, 0.3, "low"),
            ("bot_roma", "Roma", "🐺", 18, 118500, 0.5, "high"),
            ("bot_lisa", "Lisa", "🪄", 11, 54000, 0.35, "medium"),
            ("bot_dan", "Dan", "🚀", 27, 232000, 0.6, "high"),
            ("bot_sonya", "Sonya", "🌙", 8, 33500, 0.3, "low"),
        ]
        for bot_id, name, avatar, level, balance, chance, risk in seeds:
            self._exec(
                """INSERT INTO bot_profiles (id, username, first_name, avatar,
                       level, balance, play_chance, risk)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (bot_id, name.lower(), name, avatar, level, balance, chance, risk))

    # --- клановые войны --------------------------------------------------
    def create_war(self, war_id: str, clan_a: str, clan_b: str,
                   prize_a: int, prize_b: int, now: int, duration: int) -> None:
        self._exec(
            """INSERT INTO clan_wars (id, clan_a, clan_b, prize_a, prize_b,
                   score_a, score_b, starts_at, ends_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, 'active', ?)""",
            (war_id, clan_a, clan_b, prize_a, prize_b, now, now + duration, now))

    def active_war(self, clan_id: str) -> dict | None:
        return self._row(
            """SELECT * FROM clan_wars WHERE status = 'active' AND ends_at > ?
               AND (clan_a = ? OR clan_b = ?) LIMIT 1""",
            (int(time.time()), clan_id, clan_id))

    def war(self, war_id: str) -> dict | None:
        return self._row("SELECT * FROM clan_wars WHERE id = ?", (war_id,))

    def wars(self, limit: int = 30) -> list[dict]:
        return self._rows(
            """SELECT * FROM clan_wars WHERE status = 'active' AND ends_at > ?
               ORDER BY ends_at ASC LIMIT ?""", (int(time.time()), limit))

    def war_bet(self, war_id: str, user_id: int, clan_id: str, amount: int) -> bool:
        try:
            self._exec(
                """INSERT INTO clan_war_bets (war_id, user_id, clan_id, amount,
                       created_at) VALUES (?, ?, ?, ?, ?)""",
                (war_id, user_id, clan_id, amount, int(time.time())))
            return True
        except Exception:
            return False

    def war_bets(self, war_id: str) -> dict:
        rows = self._rows(
            "SELECT clan_id, COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n "
            "FROM clan_war_bets WHERE war_id = ? GROUP BY clan_id", (war_id,))
        return {row["clan_id"]: {"total": int(row["total"] or 0),
                                 "bets": int(row["n"] or 0)} for row in rows}

    def war_add_score(self, war_id: str, clan_id: str, delta: int) -> None:
        if delta > 0:
            self._exec(
                "UPDATE clan_wars SET score_a = score_a + ? "
                "WHERE id = ? AND clan_a = ?", (delta, war_id, clan_id))
            self._exec(
                "UPDATE clan_wars SET score_b = score_b + ? "
                "WHERE id = ? AND clan_b = ?", (delta, war_id, clan_id))
        else:
            self._exec(
                "UPDATE clan_wars SET score_a = score_a - ? "
                "WHERE id = ? AND clan_a = ?", (-delta, war_id, clan_id))
            self._exec(
                "UPDATE clan_wars SET score_b = score_b - ? "
                "WHERE id = ? AND clan_b = ?", (-delta, war_id, clan_id))

    def close_war(self, war_id: str, winner_id: str | None) -> dict | None:
        self._exec(
            "UPDATE clan_wars SET status = 'finished', winner_id = ? "
            "WHERE id = ? AND status = 'active'", (winner_id, war_id))
        return self.war(war_id)

    def expire_wars(self, now: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM clan_wars WHERE status = 'active' AND ends_at <= ?",
            (now,))
        for war in rows:
            a = int(war["score_a"]); b = int(war["score_b"])
            winner = war["clan_a"] if a > b else (war["clan_b"] if b > a else None)
            self.close_war(war["id"], winner)
        return rows

    # --- клановые рейды --------------------------------------------------
    def create_raid(self, raid_id: str, clan_id: str, boss: str, hp: int,
                    reward: int, now: int, duration: int) -> None:
        self._exec(
            """INSERT INTO clan_raids (id, clan_id, boss, hp, max_hp, reward,
                   starts_at, ends_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (raid_id, clan_id, boss, hp, hp, reward, now, now + duration, now))

    def active_raid(self, clan_id: str) -> dict | None:
        return self._row(
            "SELECT * FROM clan_raids WHERE clan_id = ? AND status = 'active' "
            "AND ends_at > ? LIMIT 1", (clan_id, int(time.time())))

    def raid(self, raid_id: str) -> dict | None:
        return self._row("SELECT * FROM clan_raids WHERE id = ?", (raid_id,))

    def raid_hit(self, hit_id: str, raid_id: str, user_id: int, damage: int) -> None:
        self._exec(
            """INSERT INTO clan_raid_hits (id, raid_id, user_id, damage, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (hit_id, raid_id, user_id, damage, int(time.time())))
        self._exec("UPDATE clan_raids SET hp = hp - ? WHERE id = ?",
                   (damage, raid_id))

    def raid_hits(self, raid_id: str) -> list[dict]:
        return self._rows(
            """SELECT h.user_id, u.username, u.first_name, SUM(h.damage) AS damage
               FROM clan_raid_hits h LEFT JOIN users u ON u.user_id = h.user_id
               WHERE h.raid_id = ? GROUP BY h.user_id ORDER BY damage DESC""",
            (raid_id,))

    def close_raid(self, raid_id: str, killed: bool) -> None:
        self._exec(
            "UPDATE clan_raids SET status = ? WHERE id = ? AND status = 'active'",
            ("killed" if killed else "failed", raid_id))

    def expire_raids(self, now: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM clan_raids WHERE status = 'active' AND ends_at <= ?",
            (now,))
        for raid in rows:
            self.close_raid(raid["id"], False)
        return rows

    # --- кредиты ---------------------------------------------------------
    def create_loan(self, loan_id: str, user_id: int, amount: int,
                    rate_bps: int, term_days: int, now: int) -> None:
        self._exec(
            """INSERT INTO loans (id, user_id, amount, rate_bps, term_days,
                   take_at, due_at, paid, status, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'active', NULL)""",
            (loan_id, user_id, amount, rate_bps, term_days, now,
             now + term_days * 86400))

    def loans(self, user_id: int, status: str = "active") -> list[dict]:
        return self._rows(
            "SELECT * FROM loans WHERE user_id = ? AND status = ? "
            "ORDER BY due_at ASC", (user_id, status))

    def loan(self, loan_id: str) -> dict | None:
        return self._row("SELECT * FROM loans WHERE id = ?", (loan_id,))

    def loan_owed(self, loan: dict, now: int) -> int:
        amount = int(loan["amount"])
        rate = int(loan["rate_bps"]) / 10000.0
        days = max(1, (now - int(loan["take_at"])) // 86400)
        interest = int(amount * rate * days)
        return amount + interest - int(loan["paid"])

    def loan_pay(self, loan_id: str, user_id: int, amount: int,
                 now: int) -> tuple[bool, int]:
        with self._lock:
            loan = self.loan(loan_id)
            if not loan or int(loan["user_id"]) != user_id:
                return False, 0
            if loan["status"] != "active":
                return False, 0
            owed = self.loan_owed(loan, now)
            pay = min(amount, owed)
            row = self._row("SELECT balance FROM users WHERE user_id = ?",
                            (user_id,))
            if not row or int(row["balance"]) < pay:
                return False, 0
            self.add_balance(user_id, -pay)
            new_paid = int(loan["paid"]) + pay
            if new_paid >= owed:
                self._exec(
                    "UPDATE loans SET paid = ?, status = 'closed', closed_at = ? "
                    "WHERE id = ?", (new_paid, now, loan_id))
            else:
                self._exec("UPDATE loans SET paid = ? WHERE id = ?",
                           (new_paid, loan_id))
            return True, pay

    # --- стрики ----------------------------------------------------------
    def streak_today(self, user_id: int, day: str) -> dict | None:
        return self._row(
            "SELECT * FROM streak_log WHERE user_id = ? AND day = ?",
            (user_id, day))

    def last_streak(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM streak_log WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 1", (user_id,))

    def set_streak(self, user_id: int, day: str, streak: int,
                   rewards: dict) -> None:
        self._exec(
            """INSERT INTO streak_log (user_id, day, streak, rewards, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (user_id, day)
               DO UPDATE SET streak = ?, rewards = ?""",
            (user_id, day, streak, json.dumps(rewards), int(time.time()),
             streak, json.dumps(rewards)))

    # --- рыбалка: уровни -------------------------------------------------
    def fish_level(self, user_id: int) -> dict:
        self._fish_table()
        try:
            self._exec(
                """INSERT INTO fish_levels (user_id, xp, level, total_caught,
                       best_weight, updated_at) VALUES (?, 0, 1, 0, 0, ?)""",
                (user_id, int(time.time())))
        except Exception:
            pass
        row = self._row("SELECT * FROM fish_levels WHERE user_id = ?", (user_id,))
        if not row:
            return {"level": 1, "xp": 0, "total_caught": 0, "best_weight": 0}
        return {"level": int(row["level"]), "xp": int(row["xp"]),
                "total_caught": int(row["total_caught"]),
                "best_weight": int(row["best_weight"])}

    def add_fish_xp(self, user_id: int, xp: int, weight: int = 0,
                    caught: bool = False) -> int:
        with self._lock:
            self._exec(
                """INSERT INTO fish_levels (user_id, xp, level, total_caught,
                       best_weight, updated_at) VALUES (?, ?, 1, ?, ?, ?)
                   ON CONFLICT (user_id)
                   DO UPDATE SET xp = fish_levels.xp + ?,
                       total_caught = fish_levels.total_caught + ?,
                       best_weight = MAX(fish_levels.best_weight, ?),
                       updated_at = ?""",
                (user_id, xp, 1 if caught else 0, weight, int(time.time()),
                 xp, 1 if caught else 0, weight, int(time.time())))
            row = self._row("SELECT xp, level FROM fish_levels WHERE user_id = ?",
                            (user_id,))
            if not row:
                return 1
            xp_now = int(row["xp"]); level = int(row["level"])
            while xp_now >= 200 * level * level:
                level += 1
            self._exec(
                "UPDATE fish_levels SET level = ? WHERE user_id = ?",
                (level, user_id))
            return level

    # --- крафт -----------------------------------------------------------
    def add_recipe(self, recipe_id: str, output_key: str, output_qty: int,
                   inputs: dict, cooldown_s: int) -> None:
        self._exec(
            """INSERT INTO craft_recipes (id, output_key, output_qty, inputs,
                   cooldown_s, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (recipe_id, output_key, output_qty, json.dumps(inputs),
             cooldown_s, int(time.time())))

    def recipes(self) -> list[dict]:
        rows = self._rows("SELECT * FROM craft_recipes ORDER BY id")
        out = []
        for r in rows:
            r["inputs"] = json.loads(r["inputs"])
            out.append(r)
        return out

    def recipe(self, recipe_id: str) -> dict | None:
        r = self._row("SELECT * FROM craft_recipes WHERE id = ?", (recipe_id,))
        if not r:
            return None
        r["inputs"] = json.loads(r["inputs"])
        return r

    def craft_job(self, job_id: str) -> dict | None:
        return self._row("SELECT * FROM craft_jobs WHERE id = ?", (job_id,))

    def craft_jobs(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM craft_jobs WHERE user_id = ? "
            "AND status = 'crafting' ORDER BY ends_at ASC", (user_id,))

    def start_craft(self, job_id: str, user_id: int, recipe_id: str,
                    now: int, duration: int) -> None:
        self._exec(
            """INSERT INTO craft_jobs (id, user_id, recipe_id, started_at,
                   ends_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'crafting', ?)""",
            (job_id, user_id, recipe_id, now, now + duration, now))

    def finish_craft(self, job_id: str) -> bool:
        return bool(self._exec(
            "UPDATE craft_jobs SET status = 'done' WHERE id = ? "
            "AND status = 'crafting' AND ends_at <= ?",
            (job_id, int(time.time()))))

    def claim_craft(self, job_id: str, user_id: int) -> dict | None:
        with self._lock:
            job = self.craft_job(job_id)
            if not job or int(job["user_id"]) != user_id:
                return None
            if job["status"] != "crafting":
                return None
            if int(job["ends_at"]) > int(time.time()):
                return None
            self._exec(
                "UPDATE craft_jobs SET status = 'done' WHERE id = ?",
                (job_id,))
            recipe = self.recipe(job["recipe_id"])
            if not recipe:
                return None
            self.add_item(user_id, recipe["output_key"],
                          int(recipe["output_qty"]))
            return {"output": recipe["output_key"],
                    "qty": int(recipe["output_qty"])}

    def ensure_recipes(self) -> None:
        if self.recipes():
            return
        seeds = [
            ("rod_v2", "удочка «Волна»", 680, {"fish_cheap": 6}, 3600),
            ("lootbox", "кейс удачи", 600, {"fish_common": 4}, 7200),
            ("charm", "талисман", 420, {"fish_rare": 2}, 5400),
            ("gold_pick", "золотая кирка", 1800, {"fish_epic": 3}, 0),
        ]
        for key, _title, qty, inputs, cooldown in seeds:
            self.add_recipe(key, key, qty, inputs, cooldown)

    # --- сундуки миссий --------------------------------------------------
    def chest_state(self, user_id: int, chest: str) -> dict | None:
        return self._row(
            "SELECT * FROM mission_chests WHERE user_id = ? AND chest = ?",
            (user_id, chest))

    def chest_open(self, user_id: int, chest: str, next_in: int) -> bool:
        try:
            self._exec(
                """INSERT INTO mission_chests (user_id, chest, opened_at, next_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, chest, int(time.time()), int(time.time()) + next_in))
            return True
        except Exception:
            return False

    # --- корабли ---------------------------------------------------------
    def user_ships(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT ship FROM user_ships WHERE user_id = ?",
                          (user_id,))
        return {row["ship"] for row in rows}

    def unlock_ship(self, user_id: int, ship: str) -> bool:
        try:
            self._exec(
                """INSERT INTO user_ships (user_id, ship, unlocked_at)
                   VALUES (?, ?, ?)""",
                (user_id, ship, int(time.time())))
            return True
        except Exception:
            return False

    # --- награды турниров ------------------------------------------------
    def set_tournament_rewards(self, tour_id: str, rewards: dict) -> None:
        for place, amount in rewards.items():
            self._exec(
                """INSERT INTO tournament_rewards (tournament_id, place, reward,
                       claimed_by) VALUES (?, ?, ?, NULL)
                   ON CONFLICT (tournament_id, place)
                   DO UPDATE SET reward = ?""",
                (tour_id, int(place), int(amount), int(amount)))

    def tournament_rewards(self, tour_id: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM tournament_rewards WHERE tournament_id = ? "
            "ORDER BY place ASC", (tour_id,))

    def claim_tournament_reward(self, tour_id: str, user_id: int,
                                place: int) -> bool:
        try:
            self._exec(
                """INSERT INTO tournament_claims (tournament_id, user_id, place,
                       reward, claimed_at)
                   SELECT ?, ?, place, reward, ?
                   FROM tournament_rewards WHERE tournament_id = ? AND place = ?""",
                (tour_id, user_id, int(time.time()), tour_id, place))
            return True
        except Exception:
            return False

    def tournament_claimed(self, tour_id: str, user_id: int) -> int | None:
        row = self._row(
            "SELECT place FROM tournament_claims "
            "WHERE tournament_id = ? AND user_id = ?", (tour_id, user_id))
        return row["place"] if row else None

    # --- жетоны и обменный пункт ----------------------------------------
    def tokens(self, user_id: int) -> int:
        row = self._row("SELECT value FROM tokens WHERE user_id = ?",
                        (user_id,))
        return int(row["value"]) if row else 0

    def add_tokens(self, user_id: int, delta: int) -> int:
        with self._lock:
            self._exec(
                """INSERT INTO tokens (user_id, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT (user_id)
                   DO UPDATE SET value = tokens.value + ?, updated_at = ?""",
                (user_id, delta, int(time.time()), delta, int(time.time())))
            return self.tokens(user_id)

    def spend_tokens(self, user_id: int, amount: int) -> bool:
        with self._lock:
            if self.tokens(user_id) < amount:
                return False
            self._exec(
                "UPDATE tokens SET value = value - ?, updated_at = ? "
                "WHERE user_id = ? AND value >= ?",
                (amount, int(time.time()), user_id, amount))
            return True

    def token_log(self, user_id: int, delta: int, reason: str) -> None:
        self._exec(
            """INSERT INTO token_log (id, user_id, delta, reason, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, delta, reason, int(time.time())))

    def token_history(self, user_id: int, limit: int = 20) -> list[dict]:
        return self._rows(
            "SELECT * FROM token_log WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    # --- ежедневные ротации в магазине ----------------------------------
    def shop_rotation(self, key: str) -> dict | None:
        return self._row(
            "SELECT * FROM shop_rotations WHERE key = ?", (key,))

    def set_shop_rotation(self, key: str, items: dict, until: int) -> None:
        self._exec(
            """INSERT INTO shop_rotations (key, items, until, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (key)
               DO UPDATE SET items = ?, until = ?, updated_at = ?""",
            (key, json.dumps(items), until, int(time.time()),
             json.dumps(items), until, int(time.time())))

    # --- коллекционные карточки -----------------------------------------
    def cards(self, user_id: int) -> dict:
        rows = self._rows(
            "SELECT card, qty FROM player_cards WHERE user_id = ?",
            (user_id,))
        return {row["card"]: int(row["qty"]) for row in rows}

    def add_card(self, user_id: int, card: str, qty: int = 1) -> None:
        self._exec(
            """INSERT INTO player_cards (user_id, card, qty, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id, card)
               DO UPDATE SET qty = player_cards.qty + ?, updated_at = ?""",
            (user_id, card, qty, int(time.time()), qty, int(time.time())))

    def take_card(self, user_id: int, card: str, qty: int = 1) -> bool:
        with self._lock:
            if self.cards(user_id).get(card, 0) < qty:
                return False
            self._exec(
                "UPDATE player_cards SET qty = qty - ? "
                "WHERE user_id = ? AND card = ? AND qty >= ?",
                (qty, user_id, card, qty))
            return True

    def card_album(self) -> list[dict]:
        return self._rows(
            "SELECT * FROM card_album ORDER BY set_key, number")

    def card_progress(self, user_id: int) -> dict:
        self.cards(user_id)
        self.card_album()
        rows = self._rows(
            "SELECT c.set_key, COUNT(*) AS total, "
            "SUM(CASE WHEN pc.qty > 0 THEN 1 ELSE 0 END) AS owned "
            "FROM card_album c LEFT JOIN player_cards pc "
            "ON pc.card = c.card AND pc.user_id = ? "
            "GROUP BY c.set_key", (user_id,))
        return {"sets": [{"set_key": r["set_key"], "total": int(r["total"]),
                          "owned": int(r["owned"])} for r in rows]}

    # --- обмен и дубликаты карточек --------------------------------------
    def card_duplicates(self, user_id: int) -> int:
        cards = self.cards(user_id)
        return sum(int(q) - 1 for q in cards.values() if int(q) > 1)

    def card_dismantle(self, user_id: int, card: str, qty: int = 1) -> int:
        if self.cards(user_id).get(card, 0) <= 1:
            return 0
        album = {c["card"]: c for c in self.card_album()}
        spec = album.get(card)
        if not spec:
            return 0
        rarity_values = {"common": 5, "uncommon": 15, "rare": 40,
                         "epic": 120, "legendary": 400}
        gain = int(rarity_values.get(spec["rarity"], 5)) * qty
        if not self.take_card(user_id, card, qty):
            return 0
        self.add_tokens(user_id, gain)
        return gain

    def card_dust(self, user_id: int) -> int:
        row = self._row(
            "SELECT SUM(CASE rarity WHEN 'common' THEN 5 WHEN 'uncommon' THEN 15 "
            "WHEN 'rare' THEN 40 WHEN 'epic' THEN 120 WHEN 'legendary' THEN 400 "
            "ELSE 5 END * (qty - 1)) AS dust "
            "FROM player_cards pc JOIN card_album c ON c.card = pc.card "
            "WHERE pc.user_id = ? AND pc.qty > 1", (user_id,))
        return int(row["dust"]) if row and row["dust"] else 0

    def card_market_offers(self, user_id: int | None = None, limit: int = 20) -> list[dict]:
        if user_id is None:
            return self._rows(
                "SELECT * FROM card_offers ORDER BY created_at DESC LIMIT ?",
                (limit,))
        return self._rows(
            "SELECT * FROM card_offers WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    def card_offer_create(self, offer_id: str, user_id: int, card: str,
                          price: int, qty: int = 1) -> bool:
        if self.cards(user_id).get(card, 0) < qty:
            return False
        self.take_card(user_id, card, qty)
        self._exec(
            """INSERT OR REPLACE INTO card_offers
               (offer_id, user_id, card, price, qty, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (offer_id, user_id, card, price, qty, int(time.time())))
        return True

    def card_offer_buy(self, offer_id: str, buyer_id: int) -> bool:
        offer = self._row("SELECT * FROM card_offers WHERE offer_id = ?",
                          (offer_id,))
        if not offer or int(offer["qty"]) <= 0 or int(offer["user_id"]) == buyer_id:
            return False
        price = int(offer["price"])
        if not self.spend_tokens(buyer_id, price):
            return False
        self.add_tokens(int(offer["user_id"]), price)
        self._exec(
            "UPDATE card_offers SET qty = qty - 1 WHERE offer_id = ?",
            (offer_id,))
        self._exec("DELETE FROM card_offers WHERE offer_id = ? AND qty <= 0",
                   (offer_id,))
        self.add_card(buyer_id, offer["card"], 1)
        return True

    def card_offer_cancel(self, offer_id: str, user_id: int) -> bool:
        offer = self._row("SELECT * FROM card_offers WHERE offer_id = ?",
                          (offer_id,))
        if not offer or int(offer["user_id"]) != user_id:
            return False
        self._exec("DELETE FROM card_offers WHERE offer_id = ?", (offer_id,))
        self.add_card(user_id, offer["card"], int(offer["qty"]))
        return True

    # --- энергия --------------------------------------------------------
    def energy(self, user_id: int) -> dict:
        row = self._row(
            "SELECT energy, energy_max, energy_at FROM users WHERE user_id = ?",
            (user_id,))
        if not row:
            return {"energy": 100, "max": 100, "regen_in": 0}
        now = int(time.time())
        energy = int(row["energy"] or 0)
        max_e = int(row["energy_max"] or 100)
        at = int(row["energy_at"] or now)
        gained = (now - at) // 60
        energy = min(max_e, energy + gained)
        if energy < max_e:
            next_at = at + (now - at) // 60 * 60 + 60
            regen_in = max(0, next_at - now)
        else:
            regen_in = 0
        if gained:
            self._exec(
                "UPDATE users SET energy = ?, energy_at = ? WHERE user_id = ?",
                (energy, now, user_id))
        return {"energy": energy, "max": max_e, "regen_in": regen_in}

    def spend_energy(self, user_id: int, amount: int) -> bool:
        with self._lock:
            st = self.energy(user_id)
            if st["energy"] < amount:
                return False
            self._exec(
                "UPDATE users SET energy = energy - ?, energy_at = ? "
                "WHERE user_id = ?", (amount, int(time.time()), user_id))
            return True

    def add_energy(self, user_id: int, amount: int) -> int:
        self._exec("UPDATE users SET energy = MIN(energy + ?, energy_max) "
                   "WHERE user_id = ?", (amount, user_id))
        return self.energy(user_id)["energy"]

    # --- арена (параллельные дуэли) -------------------------------------
    def arena_stats(self, user_id: int) -> dict:
        row = self._row(
            "SELECT duels_played, duels_won FROM users WHERE user_id = ?",
            (user_id,))
        return {"played": int(row["duels_played"] or 0) if row else 0,
                "won": int(row["duels_won"] or 0) if row else 0}

    def arena_rating(self, user_id: int) -> int:
        row = self._row(
            "SELECT rating FROM arena_ratings WHERE user_id = ?", (user_id,))
        if row:
            return int(row["rating"])
        self._exec(
            "INSERT INTO arena_ratings (user_id, rating, updated_at) "
            "VALUES (?, 1200, ?) ON CONFLICT DO NOTHING",
            (user_id, int(time.time())))
        return 1200

    def update_arena_rating(self, user_id: int, delta: int) -> int:
        self._exec(
            """INSERT INTO arena_ratings (user_id, rating, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (user_id)
               DO UPDATE SET rating = MAX(100, arena_ratings.rating + ?),
                             updated_at = ?""",
            (user_id, 1200 + delta, int(time.time()), delta, int(time.time())))
        return self.arena_rating(user_id)

    def arena_calendar(self, user_id: int) -> dict:
        rows = self._rows(
            "SELECT * FROM arena_matches WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 10", (user_id,))
        return {"matches": [{
            "id": m["id"], "opponent": m["opponent"], "bet": m["bet"],
            "result": m["result"], "payout": m["payout"],
            "created_at": m["created_at"],
        } for m in rows]}

    def add_arena_match(self, match_id: str, user_id: int, opponent: str,
                        bet: int, result: str, payout: int) -> None:
        self._exec(
            """INSERT INTO arena_matches (id, user_id, opponent, bet, result,
                   payout, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (match_id, user_id, opponent, bet, result, payout,
             int(time.time())))

    # --- бинго ----------------------------------------------------------
    def bingo_boards(self, user_id: int) -> int:
        rows = self._rows("SELECT id FROM bingo_games WHERE user_id = ?",
                          (user_id,))
        return len(rows)

    def create_bingo(self, game_id: str, user_id: int, bet: int,
                     board: list[int]) -> None:
        self._exec(
            """INSERT INTO bingo_games (id, user_id, bet, board, numbers,
                   marks, status, payout, created_at)
               VALUES (?, ?, ?, ?, '[]', '[]', 'active', 0, ?)""",
            (game_id, user_id, bet, json.dumps(board), int(time.time())))

    def bingo_game(self, game_id: str) -> dict | None:
        row = self._row("SELECT * FROM bingo_games WHERE id = ?", (game_id,))
        if not row:
            return None
        row["board"] = json.loads(row["board"])
        row["numbers"] = json.loads(row["numbers"])
        row["marks"] = json.loads(row["marks"])
        return row

    def active_bingo(self, user_id: int) -> dict | None:
        row = self._row(
            "SELECT * FROM bingo_games WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1", (user_id,))
        if not row:
            return None
        row["board"] = json.loads(row["board"])
        row["numbers"] = json.loads(row["numbers"])
        row["marks"] = json.loads(row["marks"])
        return row

    def bingo_mark(self, game_id: str, number: int,
                   marks: list[bool]) -> tuple[bool, int]:
        row = self._row(
            "SELECT * FROM bingo_games WHERE id = ? AND status = 'active'",
            (game_id,))
        if not row:
            return False, 0
        numbers = json.loads(row["numbers"]) + [number]
        self._exec(
            "UPDATE bingo_games SET numbers = ?, marks = ? WHERE id = ?",
            (json.dumps(numbers), json.dumps(marks), game_id))
        return True, int(row["bet"])

    def bingo_finish(self, game_id: str, status: str, payout: int) -> bool:
        return bool(self._exec(
            "UPDATE bingo_games SET status = ?, payout = ? WHERE id = ? "
            "AND status = 'active'", (status, payout, game_id)))

    # --- поиск игроков ---------------------------------------------------
    def search_users(self, query: str, limit: int = 20) -> list[dict]:
        q = f"%{query.strip()}%"
        return self._rows(
            """SELECT user_id, username, first_name, balance, xp, last_seen
               FROM users
               WHERE is_banned = 0
                 AND (username LIKE ? OR first_name LIKE ? OR CAST(user_id AS TEXT) LIKE ?)
               ORDER BY balance DESC LIMIT ?""",
            (q, q, q, limit))

    # --- престиж --------------------------------------------------------
    def prestige(self, user_id: int) -> dict:
        row = self._row(
            "SELECT prestige, prestige_xp, prestige_best, xp, balance FROM users "
            "WHERE user_id = ?", (user_id,))
        if not row:
            return {"prestige": 0, "xp": 0, "best": 1.0}
        return {"prestige": int(row["prestige"] or 0),
                "xp": int(row["prestige_xp"] or 0),
                "best": float(row["prestige_best"] or 1.0),
                "level_xp": int(row["xp"] or 0),
                "balance": int(row["balance"] or 0)}

    def set_prestige(self, user_id: int, prestige: int, xp: int,
                     best: float) -> None:
        self._exec(
            "UPDATE users SET prestige = ?, prestige_xp = ?, prestige_best = ? "
            "WHERE user_id = ?", (prestige, xp, best, user_id))

    def reset_xp(self, user_id: int) -> None:
        self._exec("UPDATE users SET xp = 0 WHERE user_id = ?", (user_id,))

    # --- заказы (крупные контракты) ------------------------------------
    def create_order(self, order_id: str, user_id: int, kind: str,
                     target: int, reward: int, now: int, expires_in: int,
                     extra: dict) -> None:
        self._exec(
            """INSERT INTO orders (id, user_id, kind, target, progress, reward,
                   expires_at, status, extra, created_at)
               VALUES (?, ?, ?, ?, 0, ?, ?, 'active', ?, ?)""",
            (order_id, user_id, kind, target, reward, now + expires_in,
             json.dumps(extra), now))

    def orders(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM orders WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at ASC", (user_id,))

    def bump_order(self, user_id: int, kind: str, delta: int = 1) -> None:
        self._exec(
            "UPDATE orders SET progress = progress + ? "
            "WHERE user_id = ? AND kind = ? AND status = 'active'",
            (delta, user_id, kind))

    def order_done(self, order_id: str) -> bool:
        return bool(self._exec(
            "UPDATE orders SET status = 'done' WHERE id = ? AND status = 'active'",
            (order_id,)))

    def finish_order(self, order_id: str, user_id: int) -> dict | None:
        with self._lock:
            row = self._row(
                "SELECT * FROM orders WHERE id = ? AND user_id = ? "
                "AND status = 'done'", (order_id, user_id))
            if not row:
                return None
            self._exec("UPDATE orders SET status = 'claimed' WHERE id = ?",
                       (order_id,))
            return row

    # --- живые ставки ---------------------------------------------------
    def create_live_session(self, session_id: str, game: str, host_id: int,
                            bet: int) -> None:
        self._exec(
            """INSERT INTO live_sessions (id, game, host_id, bet, seed,
                   outcome, status, created_at)
               VALUES (?, ?, ?, ?, ?, 0, 'active', ?)""",
            (session_id, game, host_id, bet, str(uuid.uuid4()),
             int(time.time())))

    def live_sessions(self, limit: int = 10) -> list[dict]:
        return self._rows(
            "SELECT * FROM live_sessions WHERE status = 'active' "
            "ORDER BY created_at DESC LIMIT ?", (limit,))

    def live_session(self, session_id: str) -> dict | None:
        return self._row(
            "SELECT * FROM live_sessions WHERE id = ?", (session_id,))

    def finish_live_session(self, session_id: str, outcome: float) -> None:
        self._exec(
            "UPDATE live_sessions SET outcome = ?, status = 'finished', "
            "finished_at = ? WHERE id = ? AND status = 'active'",
            (outcome, int(time.time()), session_id))

    def place_live_bet(self, bet_id: str, user_id: int, session_id: str,
                       game: str, bet: int, odds: float) -> bool:
        try:
            self._exec(
                """INSERT INTO live_bets (id, user_id, session_id, game, bet,
                       odds, outcome, payout, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)""",
                (bet_id, user_id, session_id, game, bet, odds, int(time.time())))
            return True
        except Exception:
            return False

    def live_bets(self, session_id: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM live_bets WHERE session_id = ?", (session_id,))

    def settle_live_bets(self, session_id: str, outcome: float) -> None:
        bets = self.live_bets(session_id)
        for b in bets:
            won = (outcome >= 2.0 and outcome < 100.0) or (outcome < 1.5)
            payout = int(b["bet"] * b["odds"]) if won else 0
            self._exec(
                "UPDATE live_bets SET outcome = ?, payout = ? WHERE id = ?",
                ("won" if won else "lost", payout, b["id"]))
            if payout:
                self.add_balance(int(b["user_id"]), payout)

    # --- сезонные события -----------------------------------------------
    def create_event(self, event_id: str, key: str, title: str,
                     desc_text: str, starts_at: int, ends_at: int,
                     prize: int) -> None:
        self._exec(
            """INSERT INTO season_events (id, key, title, desc_text,
                   starts_at, ends_at, prize, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, key, title, desc_text, starts_at, ends_at, prize,
             int(time.time())))

    def active_events(self, now: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM season_events WHERE starts_at <= ? AND ends_at >= ? "
            "ORDER BY ends_at ASC", (now, now))

    def event_claimed(self, event_id: str, user_id: int) -> bool:
        row = self._row(
            "SELECT 1 AS x FROM event_claims WHERE event_id = ? AND user_id = ?",
            (event_id, user_id))
        return bool(row)

    def claim_event(self, event_id: str, user_id: int) -> bool:
        try:
            self._exec(
                """INSERT INTO event_claims (event_id, user_id, claimed_at)
                   VALUES (?, ?, ?)""",
                (event_id, user_id, int(time.time())))
            return True
        except Exception:
            return False

    def ensure_events(self) -> None:
        if self.active_events(int(time.time())):
            return
        now = int(time.time())
        self.create_event(str(uuid.uuid4()), "weekend", "Выходной бонус",
                          "Играйте в любую игру и получайте за каждый час "
                          "игры бонус к награде.", now - 3600,
                          now + 2 * 86400, 5000)

    # --- ресторан -------------------------------------------------------
    def restaurant_orders(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM restaurant_orders WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 10", (user_id,))

    def create_restaurant_order(self, order_id: str, user_id: int, dish: str,
                                fish_key: str, fish_count: int, reward: int,
                                now: int, cook_time: int) -> None:
        self._exec(
            """INSERT INTO restaurant_orders (id, user_id, dish, fish_key,
                   fish_count, reward, started_at, ready_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'cooking', ?)""",
            (order_id, user_id, dish, fish_key, fish_count, reward, now,
             now + cook_time, now))

    def finish_restaurant_order(self, order_id: str, user_id: int) -> dict | None:
        with self._lock:
            row = self._row(
                "SELECT * FROM restaurant_orders WHERE id = ? AND user_id = ? "
                "AND status = 'cooking' AND ready_at <= ?",
                (order_id, user_id, int(time.time())))
            if not row:
                return None
            self._exec(
                "UPDATE restaurant_orders SET status = 'done' WHERE id = ?",
                (order_id,))
            return row

    def cancel_restaurant_order(self, order_id: str, user_id: int) -> None:
        self._exec(
            "UPDATE restaurant_orders SET status = 'cancelled' "
            "WHERE id = ? AND user_id = ? AND status = 'cooking'",
            (order_id, user_id))

    # --- медали ---------------------------------------------------------
    def medals(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT medal FROM medals WHERE user_id = ?",
                          (user_id,))
        return {row["medal"] for row in rows}

    def award_medal(self, user_id: int, medal: str) -> bool:
        try:
            self._exec(
                """INSERT INTO medals (user_id, medal, earned_at)
                   VALUES (?, ?, ?)""",
                (user_id, medal, int(time.time())))
            return True
        except Exception:
            return False

    # --- цели дня -------------------------------------------------------
    def daily_goals(self, user_id: int, day: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM daily_goals WHERE user_id = ? AND day = ?",
            (user_id, day))

    def set_daily_goal(self, user_id: int, day: str, kind: str, target: int,
                       reward: int) -> None:
        self._exec(
            """INSERT INTO daily_goals (user_id, day, kind, target, progress,
                   reward, claimed) VALUES (?, ?, ?, ?, 0, ?, 0)
               ON CONFLICT (user_id, day, kind) DO NOTHING""",
            (user_id, day, kind, target, reward))

    def bump_daily_goal(self, user_id: int, day: str, kind: str,
                        delta: int = 1) -> None:
        self._exec(
            "UPDATE daily_goals SET progress = progress + ? "
            "WHERE user_id = ? AND day = ? AND kind = ? AND claimed = 0",
            (delta, user_id, day, kind))

    def claim_daily_goal(self, user_id: int, day: str, kind: str) -> dict | None:
        with self._lock:
            row = self._row(
                "SELECT * FROM daily_goals WHERE user_id = ? AND day = ? "
                "AND kind = ? AND claimed = 0 AND progress >= target",
                (user_id, day, kind))
            if not row:
                return None
            self._exec(
                "UPDATE daily_goals SET claimed = 1 "
                "WHERE user_id = ? AND day = ? AND kind = ?",
                (user_id, day, kind))
            return row

    def ensure_daily_goals(self, user_id: int, day: str) -> None:
        goals = self.daily_goals(user_id, day)
        if goals:
            return
        self.set_daily_goal(user_id, day, "games", 10, 2000)
        self.set_daily_goal(user_id, day, "wins", 5, 3000)
        self.set_daily_goal(user_id, day, "fishing", 3, 2500)

    # --- титул лидера недели --------------------------------------------
    def leader_title(self, user_id: int) -> dict:
        row = self._row(
            "SELECT * FROM leader_titles WHERE user_id = ?", (user_id,))
        return {"title": row["title"] if row else "", "week": row["week"] if row else ""}

    def set_leader_title(self, user_id: int, title: str, week: str) -> None:
        self._exec(
            """INSERT INTO leader_titles (user_id, title, week, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id)
               DO UPDATE SET title = ?, week = ?, updated_at = ?""",
            (user_id, title, week, int(time.time()), title, week,
             int(time.time())))

    # --- прогресс по видам рыб ------------------------------------------
    def fish_species_progress(self, user_id: int) -> dict:
        self._fish_table()
        rows = self._rows(
            "SELECT * FROM fish_species_progress WHERE user_id = ?",
            (user_id,))
        return {row["species"]: {"caught": int(row["caught"]),
                                 "best": int(row["best_weight"])}
                for row in rows}

    def record_fish_species(self, user_id: int, species: str,
                            weight: int) -> None:
        self._exec(
            """INSERT INTO fish_species_progress (user_id, species, caught,
                   best_weight) VALUES (?, ?, 1, ?)
               ON CONFLICT (user_id, species)
               DO UPDATE SET caught = fish_species_progress.caught + 1,
                   best_weight = MAX(fish_species_progress.best_weight, ?)""",
            (user_id, species, weight, weight))

    # --- данж-экспедиции ------------------------------------------------
    def create_dungeon(self, run_id: str, user_id: int, dungeon: str,
                       level: int) -> None:
        self._exec(
            """INSERT INTO dungeon_runs (id, user_id, dungeon, level, hp,
                   max_hp, gold, kills, status, created_at)
               VALUES (?, ?, ?, ?, 100, 100, 0, 0, 'active', ?)""",
            (run_id, user_id, dungeon, level, int(time.time())))

    def active_dungeon(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM dungeon_runs WHERE user_id = ? AND status = 'active' "
            "LIMIT 1", (user_id,))

    def dungeon_run(self, run_id: str) -> dict | None:
        return self._row("SELECT * FROM dungeon_runs WHERE id = ?", (run_id,))

    def dungeon_fight(self, run_id: str, hp: int, gold: int,
                      kills: int) -> None:
        self._exec(
            "UPDATE dungeon_runs SET hp = ?, gold = ?, kills = ? WHERE id = ?",
            (hp, gold, kills, run_id))

    def finish_dungeon(self, run_id: str, status: str) -> None:
        self._exec(
            "UPDATE dungeon_runs SET status = ?, finished_at = ? WHERE id = ? "
            "AND status = 'active'", (status, int(time.time()), run_id))

    def dungeon_best(self, user_id: int) -> dict:
        row = self._row(
            "SELECT * FROM dungeon_runs WHERE user_id = ? AND status = 'finished' "
            "ORDER BY kills DESC LIMIT 1", (user_id,))
        if not row:
            return {"kills": 0, "gold": 0}
        return {"kills": int(row["kills"]), "gold": int(row["gold"]),
                "dungeon": row["dungeon"]}

    # --- подарки --------------------------------------------------------
    def send_gift(self, gift_id: str, from_id: int, to_id: int, gift: str,
                  note: str) -> None:
        self._exec(
            """INSERT INTO gifts (id, from_id, to_id, gift, note, created_at,
                   status) VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (gift_id, from_id, to_id, gift, note, int(time.time())))

    def gifts_to(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM gifts WHERE to_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC", (user_id,))

    def gift(self, gift_id: str) -> dict | None:
        return self._row("SELECT * FROM gifts WHERE id = ?", (gift_id,))

    def accept_gift(self, gift_id: str, user_id: int) -> bool:
        return bool(self._exec(
            "UPDATE gifts SET status = 'accepted' WHERE id = ? AND to_id = ? "
            "AND status = 'pending'", (gift_id, user_id)))

    # --- PvP-комнаты ----------------------------------------------------
    def create_pvp_room(self, room_id: str, owner_id: int, game: str,
                        bet: int) -> None:
        self._exec(
            """INSERT INTO pvp_rooms (id, owner_id, game, bet, guest_id,
                   status, created_at) VALUES (?, ?, ?, ?, NULL, 'waiting', ?)""",
            (room_id, owner_id, game, bet, int(time.time())))

    def pvp_rooms(self, game: str | None = None, limit: int = 20) -> list[dict]:
        if game:
            return self._rows(
                "SELECT * FROM pvp_rooms WHERE status = 'waiting' AND game = ? "
                "ORDER BY created_at DESC LIMIT ?", (game, limit))
        return self._rows(
            "SELECT * FROM pvp_rooms WHERE status = 'waiting' "
            "ORDER BY created_at DESC LIMIT ?", (limit,))

    def pvp_room(self, room_id: str) -> dict | None:
        return self._row("SELECT * FROM pvp_rooms WHERE id = ?", (room_id,))

    def pvp_join(self, room_id: str, guest_id: int, roll: int) -> bool:
        return bool(self._exec(
            "UPDATE pvp_rooms SET guest_id = ?, guest_roll = ?, "
            "status = 'started', started_at = ? "
            "WHERE id = ? AND status = 'waiting'",
            (guest_id, roll, int(time.time()), room_id)))

    def pvp_room_owner_roll(self, room_id: str, roll: int) -> bool:
        return bool(self._exec(
            "UPDATE pvp_rooms SET owner_roll = ? WHERE id = ?",
            (roll, room_id)))

    def pvp_finish(self, room_id: str, winner_id: int, finished_at: int) -> None:
        self._exec(
            "UPDATE pvp_rooms SET status = 'finished', winner_id = ?, "
            "finished_at = ? WHERE id = ?", (winner_id, finished_at, room_id))

    def pvp_active_room(self, user_id: int) -> dict | None:
        return self._row(
            "SELECT * FROM pvp_rooms WHERE (owner_id = ? OR guest_id = ?) "
            "AND status IN ('waiting', 'started') LIMIT 1",
            (user_id, user_id))

    def expire_pvp(self, now: int, ttl: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM pvp_rooms WHERE status = 'waiting' AND created_at <= ?",
            (now - ttl,))
        for room in rows:
            self._exec("UPDATE pvp_rooms SET status = 'expired' WHERE id = ?",
                       (room["id"],))
        return rows

    # --- рабочие (пассивный доход) --------------------------------------
    def worker_recipes(self) -> list[dict]:
        rows = self._rows("SELECT * FROM worker_recipes ORDER BY cost")
        if not rows:
            seeds = [
                ("fisher", 5000, 60, 3600),
                ("farmer", 15000, 180, 3600),
                ("miner", 40000, 500, 3600),
                ("engineer", 100000, 1200, 3600),
                ("scientist", 250000, 3000, 3600),
            ]
            for worker, cost, income, period in seeds:
                self._exec(
                    "INSERT INTO worker_recipes (worker, cost, income, period) "
                    "VALUES (?, ?, ?, ?)", (worker, cost, income, period))
            rows = self._rows("SELECT * FROM worker_recipes ORDER BY cost")
        return rows

    def worker(self, user_id: int) -> dict | None:
        return self._row("SELECT * FROM workers WHERE user_id = ?", (user_id,))

    def hire_worker(self, user_id: int, worker: str) -> bool:
        try:
            self._exec(
                """INSERT INTO workers (user_id, worker, hired_at, last_pay,
                       total_earned) VALUES (?, ?, ?, ?, 0)""",
                (user_id, worker, int(time.time()), int(time.time())))
            return True
        except Exception:
            return False

    def collect_worker(self, user_id: int) -> int:
        with self._lock:
            w = self.worker(user_id)
            if not w:
                return 0
            recipe = self._row(
                "SELECT * FROM worker_recipes WHERE worker = ?", (w["worker"],))
            if not recipe:
                return 0
            period = int(recipe["period"])
            now = int(time.time())
            cycles = (now - int(w["last_pay"])) // period
            if cycles <= 0:
                return 0
            earned = cycles * int(recipe["income"])
            self._exec(
                "UPDATE workers SET last_pay = last_pay + ? * ?, "
                "total_earned = total_earned + ? WHERE user_id = ?",
                (period, cycles, earned, user_id))
            return earned

    # --- ферма ----------------------------------------------------------
    def farm_plots(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM farm_plots WHERE user_id = ? "
            "ORDER BY plot ASC", (user_id,))

    def farm_plot(self, user_id: int, plot: int) -> dict | None:
        return self._row(
            "SELECT * FROM farm_plots WHERE user_id = ? AND plot = ?",
            (user_id, plot))

    def plant_crop(self, user_id: int, plot: int, crop: str,
                   now: int, grow_time: int) -> bool:
        try:
            self._exec(
                """INSERT INTO farm_plots (user_id, plot, crop, planted_at,
                       ready_at, collected) VALUES (?, ?, ?, ?, ?, 0)""",
                (user_id, plot, crop, now, now + grow_time))
            return True
        except Exception:
            return False

    def collect_crop(self, user_id: int, plot: int) -> dict | None:
        with self._lock:
            row = self._row(
                "SELECT * FROM farm_plots WHERE user_id = ? AND plot = ? "
                "AND collected = 0 AND ready_at <= ?",
                (user_id, plot, int(time.time())))
            if not row:
                return None
            self._exec(
                "UPDATE farm_plots SET collected = 1 WHERE user_id = ? AND plot = ?",
                (user_id, plot))
            return row

    def farm_layout(self, user_id: int) -> list[int]:
        row = self._row(
            "SELECT layout FROM farm_layouts WHERE user_id = ?", (user_id,))
        if not row:
            return [1, 2, 3]
        try:
            return json.loads(row["layout"])
        except Exception:
            return [1, 2, 3]

    def set_farm_layout(self, user_id: int, layout: list[int]) -> None:
        self._exec(
            """INSERT INTO farm_layouts (user_id, layout, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT (user_id)
               DO UPDATE SET layout = ?, updated_at = ?""",
            (user_id, json.dumps(layout), int(time.time()),
             json.dumps(layout), int(time.time())))

    # --- battle pass ----------------------------------------------------
    def bp_config(self) -> dict:
        row = self._row(
            "SELECT * FROM battlepass_config WHERE id = 1", ())
        if not row:
            levels = json.dumps([
                {"level": 1, "free": 500, "premium": 1500},
                {"level": 2, "free": 0, "premium": 2500},
                {"level": 3, "free": 800, "premium": 4000},
                {"level": 4, "free": 0, "premium": 6000},
                {"level": 5, "free": 1500, "premium": 10000},
            ])
            self._exec(
                """INSERT INTO battlepass_config (id, season, levels, ends_at)
                   VALUES (1, 'Сезон 1', ?, ?)""",
                (levels, int(time.time()) + 30 * 86400))
            row = self._row("SELECT * FROM battlepass_config WHERE id = 1", ())
        row["levels"] = json.loads(row["levels"])
        return row

    def bp_get(self, user_id: int) -> dict:
        try:
            self._exec(
                """INSERT INTO battlepass (user_id, level, xp, premium,
                       rewards, updated_at) VALUES (?, 0, 0, 0, '[]', ?)""",
                (user_id, int(time.time())))
        except Exception:
            pass
        row = self._row("SELECT * FROM battlepass WHERE user_id = ?",
                        (user_id,))
        return {"level": int(row["level"]), "xp": int(row["xp"]),
                "premium": int(row["premium"]),
                "rewards": json.loads(row["rewards"])}

    def bp_add_xp(self, user_id: int, amount: int) -> int:
        with self._lock:
            self._exec("UPDATE battlepass SET xp = xp + ? WHERE user_id = ?",
                       (amount, user_id))
            row = self._row("SELECT xp, level FROM battlepass WHERE user_id = ?",
                            (user_id,))
            xp = int(row["xp"]); level = int(row["level"])
            while xp >= 100 * (level + 1):
                level += 1
            self._exec("UPDATE battlepass SET level = ? WHERE user_id = ?",
                       (level, user_id))
            return level

    def bp_buy_premium(self, user_id: int, cost: int) -> bool:
        return bool(self._exec(
            "UPDATE battlepass SET premium = 1 WHERE user_id = ? AND premium = 0",
            (user_id,)))

    def bp_claim_reward(self, user_id: int, level: int, is_premium: bool) -> bool:
        row = self._row(
            "SELECT * FROM battlepass WHERE user_id = ?", (user_id,))
        if not row:
            return False
        if is_premium and not int(row["premium"]):
            return False
        if int(row["level"]) < level:
            return False
        rewards = json.loads(row["rewards"])
        tag = f"{'p' if is_premium else 'f'}{level}"
        if tag in rewards:
            return False
        rewards.append(tag)
        self._exec(
            "UPDATE battlepass SET rewards = ? WHERE user_id = ?",
            (json.dumps(rewards), user_id))
        return True

    # --- календарь наград -----------------------------------------------
    def calendar_claimed(self, user_id: int) -> set[int]:
        rows = self._rows(
            "SELECT day FROM reward_calendar WHERE user_id = ?", (user_id,))
        return {int(row["day"]) for row in rows}

    def calendar_claim_day(self, user_id: int, day: int) -> bool:
        try:
            self._exec(
                """INSERT INTO reward_calendar (user_id, day, claimed_at)
                   VALUES (?, ?, ?)""",
                (user_id, day, int(time.time())))
            return True
        except Exception:
            return False

    # --- новости --------------------------------------------------------
    def news_items(self, limit: int = 20) -> list[dict]:
        return self._rows(
            "SELECT * FROM news_items ORDER BY priority DESC, created_at DESC "
            "LIMIT ?", (limit,))

    def news_read_ids(self, user_id: int) -> set[str]:
        rows = self._rows("SELECT news_id FROM news_read WHERE user_id = ?",
                          (user_id,))
        return {row["news_id"] for row in rows}

    def mark_news_read(self, user_id: int, news_id: str) -> None:
        try:
            self._exec(
                """INSERT INTO news_read (user_id, news_id, read_at)
                   VALUES (?, ?, ?)""",
                (user_id, news_id, int(time.time())))
        except Exception:
            pass

    def add_news(self, news_id: str, title: str, body: str, icon: str,
                 priority: int = 0) -> None:
        self._exec(
            """INSERT INTO news_items (id, title, body, icon, priority,
                   created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (news_id, title, body, icon, priority, int(time.time())))

    def ensure_news(self) -> None:
        if self.news_items(1):
            return
        self.add_news("welcome", "Добро пожаловать в игру!",
                      "Забирай ежедневные бонусы, выполняй цели и следи "
                      "за новостями. Удачи!", "🎉", 100)

    # --- партнёрская программа v2 --------------------------------------
    def ref_levels(self) -> list[dict]:
        rows = self._rows("SELECT * FROM ref_levels ORDER BY level")
        if not rows:
            seeds = [
                (1, "Новичок", 0.0, 0),
                (2, "Партнёр", 0.05, 3),
                (3, "Продвинутый", 0.10, 8),
                (4, "Эксперт", 0.15, 20),
                (5, "Лидер", 0.25, 50),
            ]
            for level, title, bonus, min_children in seeds:
                self._exec(
                    "INSERT INTO ref_levels (level, title, reward_bonus, "
                    "min_children) VALUES (?, ?, ?, ?)",
                    (level, title, bonus, min_children))
            rows = self._rows("SELECT * FROM ref_levels ORDER BY level")
        return rows

    def ref_child_active(self, parent_id: int, child_id: int) -> None:
        self._exec(
            "UPDATE ref_children SET child_active = 1 "
            "WHERE parent_id = ? AND child_id = ?", (parent_id, child_id))

    def ref_children_count(self, parent_id: int) -> int:
        row = self._row(
            "SELECT COUNT(*) AS c FROM ref_children WHERE parent_id = ? "
            "AND child_active = 1", (parent_id,))
        return int(row["c"]) if row else 0

    def ref_add_child(self, parent_id: int, child_id: int) -> None:
        try:
            self._exec(
                """INSERT INTO ref_children (parent_id, child_id, child_active,
                       joined_at) VALUES (?, ?, 0, ?)""",
                (parent_id, child_id, int(time.time())))
        except Exception:
            pass

    def ref_stats(self, user_id: int) -> dict:
        children = self._rows(
            "SELECT child_id, child_active, joined_at FROM ref_children "
            "WHERE parent_id = ? ORDER BY joined_at DESC", (user_id,))
        active = sum(1 for c in children if int(c["child_active"]))
        level = 1
        for lv in self.ref_levels():
            if active >= int(lv["min_children"]):
                level = int(lv["level"])
        lv_row = next((l for l in self.ref_levels() if int(l["level"]) == level),
                      self.ref_levels()[0])
        return {"children": children, "active": active, "level": level,
                "title": lv_row["title"], "bonus": float(lv_row["reward_bonus"])}

    # ==================== ЭКОНОМИКА V2 ====================

    def _ensure_economy_account(self, user_id: int) -> None:
        self._exec(
            """INSERT OR IGNORE INTO economy_accounts
               (user_id, cash_balance, bank_balance, credits, gems, energy,
                energy_max, energy_at, updated_at)
               VALUES (?, 0, 0, 0, 0, 100, 100, ?, ?)""",
            (user_id, int(time.time()), int(time.time())))

    def economy_account(self, user_id: int) -> dict:
        self._ensure_economy_account(user_id)
        row = self._row(
            "SELECT * FROM economy_accounts WHERE user_id = ?", (user_id,))
        if not row:
            return {"user_id": user_id, "cash_balance": 0, "bank_balance": 0,
                    "credits": 0, "gems": 0, "energy": 100, "energy_max": 100,
                    "energy_at": int(time.time()), "updated_at": int(time.time())}
        return dict(row)

    def economy_transfer(self, user_id: int, currency: str, amount: int,
                         action: str = "transfer") -> int:
        self._ensure_economy_account(user_id)
        col = {"gold": "cash_balance", "bank": "bank_balance",
               "credits": "credits", "gems": "gems"}.get(currency)
        if col is None:
            return 0
        self._exec(
            f"UPDATE economy_accounts SET {col} = {col} + ?, updated_at = ? "
            "WHERE user_id = ?", (amount, int(time.time()), user_id))
        row = self._row(f"SELECT {col} AS b FROM economy_accounts WHERE user_id = ?",
                        (user_id,))
        self._exec(
            """INSERT INTO economy_log (user_id, action, amount, currency,
                   balance_after, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, action, amount, currency,
             int(row["b"]) if row else 0, int(time.time())))
        return int(row["b"]) if row else 0

    def economy_balance(self, user_id: int, currency: str) -> int:
        self._ensure_economy_account(user_id)
        col = {"gold": "cash_balance", "bank": "bank_balance",
               "credits": "credits", "gems": "gems"}.get(currency)
        if col is None:
            return 0
        row = self._row(f"SELECT {col} AS b FROM economy_accounts WHERE user_id = ?",
                        (user_id,))
        return int(row["b"]) if row else 0

    def economy_log(self, user_id: int, limit: int = 30) -> list[dict]:
        return self._rows(
            "SELECT * FROM economy_log WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?", (user_id, limit))

    def deposit_plan(self, user_id: int, plan_id: str) -> dict | None:
        row = self._row(
            "SELECT * FROM deposit_plans WHERE user_id = ? AND plan_id = ?",
            (user_id, plan_id))
        return dict(row) if row else None

    def open_deposit(self, user_id: int, plan_id: str, principal: int,
                     interest_pct: float, term_days: int) -> None:
        self._exec(
            """INSERT OR REPLACE INTO deposit_plans
               (user_id, plan_id, principal, interest_pct, term_days,
                started_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, plan_id, principal, interest_pct, term_days,
             int(time.time())))

    def close_deposit(self, user_id: int, plan_id: str) -> dict | None:
        plan = self.deposit_plan(user_id, plan_id)
        if not plan:
            return None
        self._exec("DELETE FROM deposit_plans WHERE user_id = ? AND plan_id = ?",
                   (user_id, plan_id))
        return plan

    def active_deposits(self, user_id: int) -> list[dict]:
        return self._rows("SELECT * FROM deposit_plans WHERE user_id = ?",
                          (user_id,))

    def currency_rates(self) -> dict:
        rows = self._rows("SELECT * FROM currency_rates")
        if not rows:
            seeds = [("gold", 1.0), ("gem", 100.0), ("credit", 10.0),
                     ("token", 50.0), ("energy", 5.0)]
            for cur, rate in seeds:
                self._exec(
                    "INSERT OR IGNORE INTO currency_rates "
                    "(currency, rate_to_gold, updated_at) VALUES (?, ?, ?)",
                    (cur, rate, int(time.time())))
            rows = self._rows("SELECT * FROM currency_rates")
        return {r["currency"]: {"rate": float(r["rate_to_gold"]),
                                "updated_at": int(r["updated_at"])} for r in rows}

    def set_currency_rate(self, currency: str, rate: float) -> None:
        self._exec(
            "INSERT OR REPLACE INTO currency_rates "
            "(currency, rate_to_gold, updated_at) VALUES (?, ?, ?)",
            (currency, rate, int(time.time())))

    def stock_symbols(self) -> list[dict]:
        rows = self._rows("SELECT * FROM stock_market ORDER BY symbol")
        if not rows:
            seeds = [
                ("GOLD", "Золотая жила", 100.0, 0.03),
                ("REDM", "Красная шахта", 85.0, 0.06),
                ("SAPR", "Сапёр Индастриз", 120.0, 0.05),
                ("FISH", "Рыболовный трест", 60.0, 0.04),
                ("MINE", "Майнинг Групп", 45.0, 0.08),
                ("CRYP", "КриптоДобыча", 200.0, 0.10),
            ]
            for sym, comp, price, vol in seeds:
                self._exec(
                    """INSERT OR IGNORE INTO stock_market
                       (symbol, company, price, base_price, volatility, trend,
                        updated_at) VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (sym, comp, price, price, vol, int(time.time())))
            rows = self._rows("SELECT * FROM stock_market ORDER BY symbol")
        return [dict(r) for r in rows]

    def stock_price(self, symbol: str) -> float:
        row = self._row("SELECT price FROM stock_market WHERE symbol = ?",
                        (symbol,))
        return float(row["price"]) if row else 1.0

    def stock_tick(self) -> None:
        import random
        for sym in self.stock_symbols():
            vol = float(sym["volatility"])
            trend = float(sym["trend"])
            delta = random.gauss(trend, vol)
            new_price = max(1.0, float(sym["price"]) * (1.0 + delta))
            self._exec(
                "UPDATE stock_market SET price = ?, trend = ?, updated_at = ? "
                "WHERE symbol = ?",
                (new_price, trend + (random.random() - 0.5) * vol,
                 int(time.time()), sym["symbol"]))

    def stock_trends(self) -> list[dict]:
        rows = self._rows("SELECT * FROM stock_market ORDER BY price DESC")
        return [dict(r) for r in rows]

    def stock_buy(self, user_id: int, symbol: str, shares: int) -> bool:
        if shares <= 0:
            return False
        price = self.stock_price(symbol)
        cost = int(price * shares)
        if self.economy_balance(user_id, "gold") < cost:
            return False
        self.economy_transfer(user_id, "gold", -cost, "stock_buy")
        row = self._row(
            "SELECT shares, invested FROM stock_portfolio "
            "WHERE user_id = ? AND symbol = ?", (user_id, symbol))
        if row:
            self._exec(
                "UPDATE stock_portfolio SET shares = shares + ?, "
                "invested = invested + ? WHERE user_id = ? AND symbol = ?",
                (shares, cost, user_id, symbol))
        else:
            self._exec(
                "INSERT INTO stock_portfolio (user_id, symbol, shares, invested) "
                "VALUES (?, ?, ?, ?)", (user_id, symbol, shares, cost))
        return True

    def stock_sell(self, user_id: int, symbol: str, shares: int) -> bool:
        if shares <= 0:
            return False
        row = self._row(
            "SELECT shares FROM stock_portfolio WHERE user_id = ? AND symbol = ?",
            (user_id, symbol))
        if not row or int(row["shares"]) < shares:
            return False
        price = self.stock_price(symbol)
        proceeds = int(price * shares)
        self._exec(
            "UPDATE stock_portfolio SET shares = shares - ? "
            "WHERE user_id = ? AND symbol = ?", (shares, user_id, symbol))
        self._exec(
            "DELETE FROM stock_portfolio WHERE user_id = ? AND symbol = ? "
            "AND shares <= 0", (user_id, symbol))
        self.economy_transfer(user_id, "gold", proceeds, "stock_sell")
        return True

    def stock_portfolio(self, user_id: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM stock_portfolio WHERE user_id = ? ORDER BY symbol",
            (user_id,))
        out = []
        for r in rows:
            price = self.stock_price(r["symbol"])
            out.append({**dict(r), "price": price,
                        "value": int(price * int(r["shares"]))})
        return out

    def tax_rate(self, tax_key: str) -> float:
        row = self._row("SELECT rate_pct FROM tax_rates WHERE tax_key = ?",
                        (tax_key,))
        return float(row["rate_pct"]) if row else 0.0

    def set_tax_rate(self, tax_key: str, rate_pct: float) -> None:
        self._exec(
            "INSERT OR REPLACE INTO tax_rates (tax_key, rate_pct) VALUES (?, ?)",
            (tax_key, rate_pct))

    def economy_summary(self, user_id: int) -> dict:
        acc = self.economy_account(user_id)
        stocks = self.stock_portfolio(user_id)
        stock_value = sum(int(s["value"]) for s in stocks)
        deposits = self.active_deposits(user_id)
        dep_value = sum(int(d["principal"]) for d in deposits)
        return {
            **acc,
            "stock_value": stock_value,
            "deposit_value": dep_value,
            "total_wealth": (int(acc["cash_balance"]) + int(acc["bank_balance"])
                             + int(acc["credits"]) * 10 + int(acc["gems"]) * 100
                             + stock_value + dep_value),
        }

    # ==================== ГИЛЬДИИ-ЗДАНИЯ ====================

    BUILDING_SPECS = {
        "town_hall": {"name": "Ратуша", "cost_wood": 200, "cost_stone": 100,
                      "cost_iron": 50, "max_level": 10,
                      "desc": "Центр гильдии: +1 к лимиту членов за уровень"},
        "warehouse": {"name": "Склад", "cost_wood": 150, "cost_stone": 80,
                      "cost_iron": 30, "max_level": 10,
                      "desc": "Увеличивает лимит ресурсов на 500 за уровень"},
        "smelter": {"name": "Плавильня", "cost_wood": 100, "cost_stone": 120,
                    "cost_iron": 80, "max_level": 10,
                    "desc": "+4% к добыче железа за уровень"},
        "farm_g": {"name": "Ферма", "cost_wood": 90, "cost_stone": 60,
                   "cost_iron": 20, "max_level": 10,
                   "desc": "+5 еды в час за уровень"},
        "barracks": {"name": "Казармы", "cost_wood": 180, "cost_stone": 90,
                     "cost_iron": 100, "max_level": 10,
                     "desc": "+6% к силе в войнах за уровень"},
        "bank_g": {"name": "Банк", "cost_wood": 220, "cost_stone": 140,
                   "cost_iron": 120, "max_level": 10,
                   "desc": "+0.3% к процентам вкладов участников за уровень"},
        "market_g": {"name": "Рынок", "cost_wood": 130, "cost_stone": 90,
                     "cost_iron": 40, "max_level": 10,
                     "desc": "Снижает налог на сделки на 0.4% за уровень"},
        "tower": {"name": "Башня", "cost_wood": 160, "cost_stone": 200,
                  "cost_iron": 60, "max_level": 10,
                  "desc": "+1 шпионская операция в день за уровень"},
    }

    def guild_buildings(self, clan_id: str) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM guild_buildings WHERE clan_id = ?", (clan_id,))
        existing = {r["building"]: int(r["level"]) for r in rows}
        out = []
        for key, spec in self.BUILDING_SPECS.items():
            lvl = existing.get(key, 0)
            out.append({
                "key": key, "level": lvl, **spec,
                "next_cost": self._building_cost(key, lvl + 1),
            })
        return out

    def _building_cost(self, building: str, target_level: int) -> dict:
        spec = self.BUILDING_SPECS.get(building, {})
        mult = 1.0 + (target_level - 1) * 0.5
        return {
            "wood": int(spec.get("cost_wood", 100) * mult),
            "stone": int(spec.get("cost_stone", 80) * mult),
            "iron": int(spec.get("cost_iron", 40) * mult),
        }

    def guild_resources(self, clan_id: str) -> dict:
        row = self._row("SELECT * FROM guild_resources WHERE clan_id = ?",
                        (clan_id,))
        if not row:
            return {"clan_id": clan_id, "wood": 0, "stone": 0, "iron": 0,
                    "gold": 0, "food": 0, "updated_at": int(time.time())}
        return dict(row)

    def _ensure_guild_resources(self, clan_id: str) -> None:
        self._exec(
            "INSERT OR IGNORE INTO guild_resources (clan_id, wood, stone, "
            "iron, gold, food, updated_at) VALUES (?, 0, 0, 0, 0, 0, ?)",
            (clan_id, int(time.time())))

    def guild_add_resource(self, clan_id: str, resource: str, amount: int) -> None:
        self._ensure_guild_resources(clan_id)
        allowed = {"wood", "stone", "iron", "gold", "food"}
        if resource not in allowed:
            return
        self._exec(
            f"UPDATE guild_resources SET {resource} = {resource} + ?, "
            "updated_at = ? WHERE clan_id = ?",
            (amount, int(time.time()), clan_id))

    def guild_spend_resources(self, clan_id: str, costs: dict) -> bool:
        self._ensure_guild_resources(clan_id)
        res = self.guild_resources(clan_id)
        for key, val in costs.items():
            if key not in res or int(res[key]) < int(val):
                return False
        for key, val in costs.items():
            self._exec(
                f"UPDATE guild_resources SET {key} = {key} - ?, "
                "updated_at = ? WHERE clan_id = ?",
                (int(val), int(time.time()), clan_id))
        return True

    def guild_building_level(self, clan_id: str, building: str) -> int:
        row = self._row(
            "SELECT level FROM guild_buildings WHERE clan_id = ? AND building = ?",
            (clan_id, building))
        return int(row["level"]) if row else 0

    def guild_upgrade(self, clan_id: str, building: str) -> dict | None:
        spec = self.BUILDING_SPECS.get(building)
        if not spec:
            return None
        cur = self.guild_building_level(clan_id, building)
        if cur >= int(spec["max_level"]):
            return {"error": "max_level"}
        cost = self._building_cost(building, cur + 1)
        if not self.guild_spend_resources(clan_id, cost):
            return {"error": "no_resources"}
        if cur == 0:
            self._exec(
                "INSERT OR REPLACE INTO guild_buildings "
                "(clan_id, building, level, resources) VALUES (?, ?, 1, 0)",
                (clan_id, building))
        else:
            self._exec(
                "UPDATE guild_buildings SET level = level + 1 "
                "WHERE clan_id = ? AND building = ?", (clan_id, building))
        return {"level": cur + 1, "cost": cost}

    def guild_member_limit(self, clan_id: str) -> int:
        base = 10
        lvl = self.guild_building_level(clan_id, "town_hall")
        return base + lvl

    def guild_storage_limit(self, clan_id: str) -> int:
        base = 1000
        lvl = self.guild_building_level(clan_id, "warehouse")
        return base + lvl * 500

    def guild_production(self, clan_id: str) -> dict:
        self._ensure_guild_resources(clan_id)
        res = self.guild_resources(clan_id)
        limit = self.guild_storage_limit(clan_id)
        prod = {"wood": 2, "stone": 1, "iron": 1, "food": 2}
        smelter = self.guild_building_level(clan_id, "smelter")
        farm_g = self.guild_building_level(clan_id, "farm_g")
        prod["iron"] += smelter
        prod["food"] += farm_g * 5
        out = {}
        for k, v in prod.items():
            capped = min(limit, int(res[k]) + v * 4)
            if capped != int(res[k]):
                self._exec(
                    f"UPDATE guild_resources SET {k} = ?, updated_at = ? "
                    "WHERE clan_id = ?", (capped, int(time.time()), clan_id))
            out[k] = capped
        return {**out, "limit": limit}

    def guild_tax_collect(self, clan_id: str, user_id: int, amount: int,
                          tax_type: str = "trade") -> int:
        market = self.guild_building_level(clan_id, "market_g")
        rate = max(0.0, 5.0 - market * 0.4)
        tax = int(amount * rate / 100.0)
        if tax > 0:
            self._exec(
                "INSERT INTO guild_tax_log (clan_id, user_id, amount, "
                "tax_type, created_at) VALUES (?, ?, ?, ?, ?)",
                (clan_id, user_id, tax, tax_type, int(time.time())))
            self.guild_add_resource(clan_id, "gold", tax)
        return tax

    def guild_tax_history(self, clan_id: str, limit: int = 20) -> list[dict]:
        return self._rows(
            "SELECT * FROM guild_tax_log WHERE clan_id = ? "
            "ORDER BY id DESC LIMIT ?", (clan_id, limit))

    def guild_power(self, clan_id: str) -> int:
        power = 0
        for b in self.guild_buildings(clan_id):
            power += int(b["level"]) * 50
        res = self.guild_resources(clan_id)
        power += int(res["iron"]) + int(res["gold"]) // 2
        return power

    # ==================== ГЛОБАЛЬНАЯ КАРТА ====================

    MAP_REGIONS = [
        ("north", "Северные земли", -150, -100),
        ("forest", "Лесной край", -50, -120),
        ("mountains", "Железные горы", 60, -80),
        ("plains", "Золотые равнины", 0, 0),
        ("swamp", "Туманное болото", -120, 90),
        ("desert", "Пустыня", 90, 100),
        ("cost", "Побережье", -30, 180),
        ("island", "Остров Буян", 160, 160),
    ]

    def _seed_provinces(self) -> None:
        if self._row("SELECT COUNT(*) AS c FROM map_provinces")["c"] > 0:
            return
        seeds = [
            ("north-1", "Ледяная крепость", "north", 150, 2, 1),
            ("north-2", "Волчий форт", "north", 120, 1, 3),
            ("forest-1", "Лесная застава", "forest", 100, 3, 2),
            ("mountains-1", "Рудник Дракона", "mountains", 220, 4, 3),
            ("plains-1", "Золотая долина", "plains", 180, 4, 4),
            ("swamp-1", "Тёмное болото", "swamp", 90, 2, 5),
            ("desert-1", "Песчаный порт", "desert", 130, 5, 5),
            ("cost-1", "Прибрежный бастион", "cost", 110, 3, 6),
            ("island-1", "Островной маяк", "island", 200, 6, 6),
        ]
        for pid, name, region, income, gx, gy in seeds:
            self._exec(
                """INSERT OR IGNORE INTO map_provinces
                   (province_id, name, region, base_income, x, y,
                    owner_clan, owner_user, captured_at, defense)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, 100)""",
                (pid, name, region, income, gx, gy))
            self._exec(
                "INSERT OR IGNORE INTO map_events "
                "(province_id, event_type, title, body, active, created_at) "
                "VALUES (?, 'neutral', 'Нейтральная провинция', "
                "'Провинция ждёт захвата. Доход: ' || ? || ' в час.', 1, ?)",
                (pid, income, int(time.time())))

    def provinces(self) -> list[dict]:
        self._seed_provinces()
        return self._rows("SELECT * FROM map_provinces ORDER BY region, name")

    def province(self, province_id: str) -> dict | None:
        row = self._row("SELECT * FROM map_provinces WHERE province_id = ?",
                        (province_id,))
        return dict(row) if row else None

    def _province_claim_cost(self, province: dict) -> int:
        return 300 + int(province["base_income"]) * 3

    def map_claim(self, province_id: str, clan_id: str, user_id: int) -> dict:
        prov = self.province(province_id)
        if not prov:
            return {"error": "no_province"}
        if prov["owner_clan"]:
            return {"error": "owned"}
        cost = self._province_claim_cost(prov)
        res = self.guild_resources(clan_id)
        if int(res["gold"]) < cost:
            return {"error": "no_resources"}
        self.guild_add_resource(clan_id, "gold", -cost)
        self._exec(
            "UPDATE map_provinces SET owner_clan = ?, owner_user = ?, "
            "captured_at = ?, defense = 150 WHERE province_id = ?",
            (clan_id, user_id, int(time.time()), province_id))
        self._exec(
            "INSERT INTO map_capture_log (province_id, clan_id, user_id, "
            "result, amount, created_at) VALUES (?, ?, ?, 'claim', ?, ?)",
            (province_id, clan_id, user_id, cost, int(time.time())))
        self._exec(
            "INSERT INTO map_events (province_id, event_type, title, body, "
            "active, created_at) VALUES (?, 'capture', 'Провинция захвачена', "
            "?, 1, ?)",
            (province_id, f"Клан [занял провинцию]", int(time.time())))
        return {"ok": True, "cost": cost}

    def map_attack(self, province_id: str, clan_id: str, user_id: int,
                   force: int = 100) -> dict:
        prov = self.province(province_id)
        if not prov:
            return {"error": "no_province"}
        if not prov["owner_clan"] or prov["owner_clan"] == clan_id:
            return {"error": "attacking_own_or_neutral"}
        defense = int(prov["defense"])
        import random
        roll = random.randint(50, 120) + force // 10
        if roll > defense:
            damage = min(defense, roll - defense)
            self._exec(
                "UPDATE map_provinces SET defense = defense - ? "
                "WHERE province_id = ?", (damage, province_id))
            outcome = "damage"
            detail = f"Нанесён урон {damage}. Защита: {max(0, defense - damage)}"
            self._exec(
                "INSERT INTO map_capture_log (province_id, clan_id, user_id, "
                "result, amount, created_at) VALUES (?, ?, ?, 'attack', ?, ?)",
                (province_id, clan_id, user_id, damage, int(time.time())))
        else:
            outcome = "repelled"
            detail = "Атака отбита. Защита невредима."
            self._exec(
                "INSERT INTO map_capture_log (province_id, clan_id, user_id, "
                "result, amount, created_at) VALUES (?, ?, ?, 'repelled', 0, ?)",
                (province_id, clan_id, user_id, int(time.time())))
        return {"outcome": outcome, "detail": detail,
                "defense": max(0, int(prov["defense"]) - (damage if outcome == "damage" else 0))}

    def map_capture(self, province_id: str, clan_id: str, user_id: int) -> dict:
        prov = self.province(province_id)
        if not prov:
            return {"error": "no_province"}
        if not prov["owner_clan"] or prov["owner_clan"] == clan_id:
            return {"error": "inv_target"}
        if int(prov["defense"]) > 0:
            return {"error": "has_defense"}
        cost = self._province_claim_cost(prov) // 2
        res = self.guild_resources(clan_id)
        if int(res["gold"]) < cost:
            return {"error": "no_resources"}
        self.guild_add_resource(clan_id, "gold", -cost)
        old = prov["owner_clan"]
        self._exec(
            "UPDATE map_provinces SET owner_clan = ?, owner_user = ?, "
            "captured_at = ?, defense = 100 WHERE province_id = ?",
            (clan_id, user_id, int(time.time()), province_id))
        self._exec(
            "INSERT INTO map_capture_log (province_id, clan_id, user_id, "
            "result, amount, created_at) VALUES (?, ?, ?, 'capture', ?, ?)",
            (province_id, clan_id, user_id, cost, int(time.time())))
        self._exec(
            "INSERT INTO map_events (province_id, event_type, title, body, "
            "active, created_at) VALUES (?, 'capture', 'Провинция завоёвана', "
            "?, 1, ?)",
            (province_id, f"Клан завоевал провинцию у клана [{old}].",
             int(time.time())))
        return {"ok": True, "cost": cost}

    def map_collect(self, province_id: str, clan_id: str) -> dict:
        prov = self.province(province_id)
        if not prov or prov["owner_clan"] != clan_id:
            return {"error": "not_owner"}
        last = int(prov["captured_at"])
        elapsed = max(0, int(time.time()) - last)
        if elapsed < 3600:
            return {"error": "too_soon", "wait": 3600 - elapsed}
        hours = elapsed // 3600
        income = int(prov["base_income"]) * hours
        self._exec(
            "UPDATE map_provinces SET captured_at = ? WHERE province_id = ?",
            (int(time.time()), province_id))
        self.guild_add_resource(clan_id, "gold", income)
        return {"ok": True, "income": income, "hours": hours}

    def map_events(self, province_id: str, limit: int = 5) -> list[dict]:
        return self._rows(
            "SELECT * FROM map_events WHERE province_id = ? "
            "ORDER BY id DESC LIMIT ?", (province_id, limit))

    def map_event_add(self, province_id: str, event_type: str, title: str,
                      body: str = "") -> None:
        self._exec(
            "INSERT INTO map_events (province_id, event_type, title, body, "
            "active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (province_id, event_type, title, body, int(time.time())))

    def map_stats(self) -> dict:
        self._seed_provinces()
        total = self._rows("SELECT COUNT(*) AS c FROM map_provinces")[0]["c"]
        owned = self._rows(
            "SELECT owner_clan, COUNT(*) AS c FROM map_provinces "
            "WHERE owner_clan IS NOT NULL GROUP BY owner_clan ORDER BY c DESC "
            "LIMIT 10")
        return {"total": int(total), "owned_count": int(
            sum(int(o["c"]) for o in owned)), "leaders": owned}

    # ==================== ТУРНИРНЫЙ СЕЗОН ====================

    def tournament_seasons(self) -> list[dict]:
        return self._rows(
            "SELECT * FROM tournament_seasons ORDER BY started_at DESC LIMIT 5")

    def tournament_season(self, season_id: str) -> dict | None:
        row = self._row(
            "SELECT * FROM tournament_seasons WHERE season_id = ?", (season_id,))
        return dict(row) if row else None

    def create_tournament(self, season_id: str, title: str, game: str,
                          prize_pool: int, days: int = 3,
                          max_participants: int = 16) -> None:
        self._exec(
            """INSERT OR REPLACE INTO tournament_seasons
               (season_id, title, game, status, started_at, ends_at,
                prize_pool, max_participants)
               VALUES (?, ?, ?, 'qualify', ?, ?, ?, ?)""",
            (season_id, title, game, int(time.time()),
             int(time.time()) + days * 86400, prize_pool, max_participants))
        prizes = {
            1: (int(prize_pool * 0.4), "Чемпион"),
            2: (int(prize_pool * 0.25), "Финалист"),
            3: (int(prize_pool * 0.15), "Полуфиналист"),
            4: (int(prize_pool * 0.10), "Полуфиналист"),
        }
        for place, (prize, title_p) in prizes.items():
            self._exec(
                "INSERT OR REPLACE INTO tournament_prizes "
                "(season_id, place, prize, title) VALUES (?, ?, ?, ?)",
                (season_id, place, prize, title_p))

    def tournament_qualify(self, season_id: str, user_id: int,
                           score: float) -> None:
        self._exec(
            """INSERT INTO tournament_participants (season_id, user_id, score,
                   qualified, seed) VALUES (?, ?, ?, 0, 0)
               ON CONFLICT(season_id, user_id) DO UPDATE SET
                   score = MAX(score, excluded.score)""",
            (season_id, user_id, score))

    def tournament_participants(self, season_id: str) -> list[dict]:
        return self._rows(
            "SELECT * FROM tournament_participants WHERE season_id = ? "
            "ORDER BY score DESC LIMIT 50", (season_id,))

    def tournament_qualify_finish(self, season_id: str) -> list[dict]:
        max_p = self.tournament_season(season_id)
        limit = int(max_p["max_participants"]) if max_p else 16
        rows = self._rows(
            "SELECT * FROM tournament_participants WHERE season_id = ? "
            "ORDER BY score DESC LIMIT ?", (season_id, limit))
        for i, r in enumerate(rows):
            self._exec(
                "UPDATE tournament_participants SET qualified = 1, seed = ? "
                "WHERE season_id = ? AND user_id = ?",
                (i + 1, season_id, r["user_id"]))
        self._exec(
            "UPDATE tournament_seasons SET status = 'active' WHERE season_id = ?",
            (season_id,))
        self._build_playoff(season_id)
        return rows

    def _build_playoff(self, season_id: str) -> None:
        sol = self._rows(
            "SELECT * FROM tournament_participants WHERE season_id = ? "
            "AND qualified = 1 ORDER BY seed", (season_id,))
        n = len(sol)
        if n < 2:
            return
        size = 2
        while size < n:
            size *= 2
        for i in range(size // 2):
            a = sol[2 * i]["user_id"] if 2 * i < n else None
            b = sol[2 * i + 1]["user_id"] if 2 * i + 1 < n else None
            self._exec(
                """INSERT OR IGNORE INTO tournament_matches
                   (match_id, season_id, round, bracket, user_a, user_b,
                    score_a, score_b, winner_id, finished, created_at)
                   VALUES (?, ?, 1, ?, ?, ?, 0, 0, NULL, 0, ?)""",
                (f"{season_id}-r1-{i}", season_id, str(i), a, b,
                 int(time.time())))

    def tournament_matches(self, season_id: str, round_no: int | None = None) -> list[dict]:
        if round_no is None:
            return self._rows(
                "SELECT * FROM tournament_matches WHERE season_id = ? "
                "ORDER BY round, bracket", (season_id,))
        return self._rows(
            "SELECT * FROM tournament_matches WHERE season_id = ? AND round = ? "
            "ORDER BY bracket", (season_id, round_no))

    def tournament_play(self, match_id: str, user_id: int,
                        score: float) -> dict:
        match = self._row(
            "SELECT * FROM tournament_matches WHERE match_id = ?", (match_id,))
        if not match:
            return {"error": "no_match"}
        if int(match["finished"]):
            return {"error": "finished"}
        if match["user_a"] == user_id:
            self._exec(
                "UPDATE tournament_matches SET score_a = MAX(score_a, ?) "
                "WHERE match_id = ?", (score, match_id))
            side = "a"
        elif match["user_b"] == user_id:
            self._exec(
                "UPDATE tournament_matches SET score_b = MAX(score_b, ?) "
                "WHERE match_id = ?", (score, match_id))
            side = "b"
        else:
            return {"error": "not_participant"}
        fresh = self._row(
            "SELECT * FROM tournament_matches WHERE match_id = ?", (match_id,))
        if float(fresh["score_a"]) > 0 and float(fresh["score_b"]) > 0:
            winner = fresh["user_a"] if float(fresh["score_a"]) >= float(fresh["score_b"]) else fresh["user_b"]
            self._exec(
                "UPDATE tournament_matches SET winner_id = ?, finished = 1 "
                "WHERE match_id = ?", (winner, match_id))
            self._advance_round(match["season_id"], int(match["round"]))
        return {"side": side, "score": score}

    def _advance_round(self, season_id: str, round_no: int) -> None:
        rounds = self._rows(
            "SELECT DISTINCT round FROM tournament_matches WHERE season_id = ? "
            "ORDER BY round", (season_id,))
        if not rounds:
            return
        cur = [int(r["round"]) for r in rounds]
        pending = self._rows(
            "SELECT COUNT(*) AS c FROM tournament_matches "
            "WHERE season_id = ? AND round = ? AND finished = 0",
            (season_id, round_no))
        if int(pending[0]["c"]) > 0:
            return
        winners = self._rows(
            "SELECT winner_id, bracket FROM tournament_matches "
            "WHERE season_id = ? AND round = ? AND winner_id IS NOT NULL "
            "ORDER BY CAST(bracket AS INTEGER)", (season_id, round_no))
        if len(winners) <= 1:
            self._exec(
                "UPDATE tournament_seasons SET status = 'finished' "
                "WHERE season_id = ?", (season_id,))
            return
        next_round = round_no + 1
        for i in range(0, len(winners), 2):
            a = winners[i]["winner_id"] if i < len(winners) else None
            b = winners[i + 1]["winner_id"] if i + 1 < len(winners) else None
            match_id = f"{season_id}-r{next_round}-{i // 2}"
            if a and b:
                self._exec(
                    """INSERT OR IGNORE INTO tournament_matches
                       (match_id, season_id, round, bracket, user_a, user_b,
                        score_a, score_b, winner_id, finished, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL, 0, ?)""",
                    (match_id, season_id, next_round, str(i // 2), a, b,
                     int(time.time())))
            elif a:
                self._exec(
                    """INSERT OR IGNORE INTO tournament_matches
                       (match_id, season_id, round, bracket, user_a, user_b,
                        score_a, score_b, winner_id, finished, created_at)
                       VALUES (?, ?, ?, ?, ?, NULL, 0, 0, ?, 1, ?)""",
                    (match_id, season_id, next_round, str(i // 2), a, a,
                     int(time.time())))

    def tournament_apply_prizes(self, season_id: str) -> None:
        matches = self._rows(
            "SELECT * FROM tournament_matches WHERE season_id = ? "
            "ORDER BY round DESC LIMIT 1", (season_id,))
        if not matches:
            return
        champ = matches[0]
        if champ["winner_id"] is None:
            return
        winner = int(champ["winner_id"])
        self.db = self
        self._exec(
            "UPDATE users SET balance = balance + 0 WHERE user_id = ?",
            (winner,))
        prizes = self._rows(
            "SELECT * FROM tournament_prizes WHERE season_id = ? ORDER BY place",
            (season_id,))
        if prizes:
            p = prizes[0]
            self._exec(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (int(p["prize"]), winner))

    def tournament_my(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT t.*, p.score, p.qualified, p.seed FROM tournament_seasons t "
            "JOIN tournament_participants p ON p.season_id = t.season_id "
            "WHERE p.user_id = ? ORDER BY t.started_at DESC", (user_id,))

    # ==================== УЛИЦА (Mirage-style) ====================

    STREET_PROPERTIES = {
        "apartment": {"name": "Квартира", "cost": 5000, "income": 20,
                      "per_level": 15, "max_level": 10,
                      "desc": "Базовое жильё: +20/час за уровень"},
        "house": {"name": "Дом", "cost": 20000, "income": 60,
                  "per_level": 40, "max_level": 10,
                  "desc": "Комфортный дом: +60/час за уровень"},
        "car": {"name": "Машина", "cost": 15000, "income": 45,
                "per_level": 25, "max_level": 5,
                "desc": "Личный транспорт: +45/час за уровень"},
        "business": {"name": "Бизнес", "cost": 60000, "income": 150,
                     "per_level": 90, "max_level": 10,
                     "desc": "Свой бизнес: +150/час за уровень"},
        "yacht": {"name": "Яхта", "cost": 150000, "income": 350,
                  "per_level": 200, "max_level": 5,
                  "desc": "Роскошь: +350/час за уровень"},
    }

    STREET_JOBS = {
        "courier": {"name": "Курьер", "exp_req": 0, "reward": 100,
                    "cooldown": 600, "desc": "Развозит заказы. Опыт: 0+"},
        "guard": {"name": "Охранник", "exp_req": 200, "reward": 220,
                  "cooldown": 900, "desc": "Охраняет район. Опыт: 200+"},
        "miner": {"name": "Шахтёр", "exp_req": 500, "reward": 400,
                  "cooldown": 1200, "desc": "Добывает руду. Опыт: 500+"},
        "banker": {"name": "Банковский клерк", "exp_req": 1200, "reward": 700,
                   "cooldown": 1500, "desc": "Работает в банке. Опыт: 1200+"},
        "ceo": {"name": "Директор", "exp_req": 3000, "reward": 1500,
                "cooldown": 1800, "desc": "Руководит компанией. Опыт: 3000+"},
    }

    def street_properties(self, user_id: int) -> list[dict]:
        rows = self._rows(
            "SELECT * FROM street_properties WHERE user_id = ?", (user_id,))
        owned = {r["prop_type"]: r for r in rows}
        out = []
        for key, spec in self.STREET_PROPERTIES.items():
            own = owned.get(key)
            lvl = int(own["level"]) if own else 0
            out.append({"key": key, "level": lvl, **spec,
                        "income": int(spec["income"]) * max(1, lvl) if lvl else 0})
        return out

    def street_buy(self, user_id: int, prop_type: str) -> dict | None:
        spec = self.STREET_PROPERTIES.get(prop_type)
        if not spec:
            return {"error": "bad_type"}
        cur = self._row(
            "SELECT level FROM street_properties WHERE user_id = ? AND prop_type = ?",
            (user_id, prop_type))
        current = int(cur["level"]) if cur else 0
        cost = int(spec["cost"]) * (current + 1)
        if self.economy_balance(user_id, "gold") < cost:
            return {"error": "no_funds"}
        self.economy_transfer(user_id, "gold", -cost, "street_buy:" + prop_type)
        if current == 0:
            self._exec(
                "INSERT OR REPLACE INTO street_properties "
                "(user_id, prop_type, level, income_rate, purchased_at) "
                "VALUES (?, ?, 1, ?, ?)",
                (user_id, prop_type, spec["income"], int(time.time())))
        else:
            self._exec(
                "UPDATE street_properties SET level = level + 1, "
                "income_rate = income_rate + ? WHERE user_id = ? AND prop_type = ?",
                (spec["per_level"], user_id, prop_type))
        return {"level": current + 1, "cost": cost}

    def street_income(self, user_id: int) -> int:
        total = 0
        for p in self.street_properties(user_id):
            total += int(p["income"])
        return total

    def street_jobs(self) -> list[dict]:
        return [{"key": k, **v} for k, v in self.STREET_JOBS.items()]

    def street_my_job(self, user_id: int) -> dict | None:
        row = self._row("SELECT * FROM street_jobs WHERE user_id = ?",
                        (user_id,))
        return dict(row) if row else None

    def street_apply_job(self, user_id: int, job_key: str, exp: int) -> dict:
        spec = self.STREET_JOBS.get(job_key)
        if not spec:
            return {"error": "bad_job"}
        if exp < int(spec["exp_req"]):
            return {"error": "low_exp"}
        self._exec(
            "INSERT OR REPLACE INTO street_jobs (user_id, job_key, started_at, "
            "last_collect) VALUES (?, ?, ?, 0)",
            (user_id, job_key, int(time.time())))
        return {"ok": True, "job": job_key}

    def street_collect_job(self, user_id: int) -> dict:
        job = self.street_my_job(user_id)
        if not job:
            return {"error": "no_job"}
        spec = self.STREET_JOBS.get(job["job_key"])
        if not spec:
            return {"error": "bad_job"}
        now = int(time.time())
        last = int(job["last_collect"] or 0)
        cd = int(spec["cooldown"])
        if now - last < cd:
            return {"error": "cooldown", "wait": cd - (now - last)}
        reward = int(spec["reward"]) + int(job["started_at"]) % 10
        self._exec(
            "UPDATE street_jobs SET last_collect = ? WHERE user_id = ?",
            (now, user_id))
        self.economy_transfer(user_id, "gold", reward, "street_job")
        self._exec(
            "INSERT INTO street_work_log (user_id, job_key, reward, created_at) "
            "VALUES (?, ?, ?, ?)", (user_id, job["job_key"], reward, now))
        return {"ok": True, "reward": reward, "job": job["job_key"]}

    # --- джекпот-розыгрыш (Mirage-style) --------------------------------
    def jackpot(self) -> dict:
        row = self._row("SELECT * FROM jackpot_pool WHERE id = 1")
        if not row:
            self._exec(
                "INSERT INTO jackpot_pool (id, pool, last_winner, last_win_at, "
                "last_win_amt, next_draw) VALUES (1, 0, NULL, 0, 0, ?)",
                (int(time.time()) + 86400,))
            row = self._row("SELECT * FROM jackpot_pool WHERE id = 1")
        return dict(row)

    def jackpot_add(self, user_id: int, amount: int) -> dict:
        if amount <= 0:
            return {"error": "bad_amount"}
        if self.economy_balance(user_id, "gold") < amount:
            return {"error": "no_funds"}
        self.economy_transfer(user_id, "gold", -amount, "jackpot_ticket")
        self._exec(
            "INSERT OR IGNORE INTO jackpot_pool (id, pool, last_winner, "
            "last_win_at, last_win_amt, next_draw) VALUES (1, 0, NULL, 0, 0, ?)",
            (int(time.time()) + 86400,))
        self._exec("UPDATE jackpot_pool SET pool = pool + ? WHERE id = 1",
                   (amount,))
        ticket_id = uuid.uuid4().hex[:16]
        self._exec(
            "INSERT INTO jackpot_tickets (ticket_id, user_id, amount, created_at) "
            "VALUES (?, ?, ?, ?)",
            (ticket_id, user_id, amount, int(time.time())))
        return {"ok": True, "ticket": ticket_id, "amount": amount}

    def jackpot_my_tickets(self, user_id: int) -> int:
        row = self._row(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM jackpot_tickets "
            "WHERE user_id = ?", (user_id,))
        return int(row["s"]) if row else 0

    def jackpot_draw(self) -> dict:
        import random
        pool = self.jackpot()
        tickets = self._rows(
            "SELECT * FROM jackpot_tickets ORDER BY created_at")
        if not tickets:
            return {"ok": False, "reason": "no_tickets"}
        total = sum(int(t["amount"]) for t in tickets)
        roll = random.randint(1, max(1, total))
        acc = 0
        winner = tickets[-1]
        for t in tickets:
            acc += int(t["amount"])
            if roll <= acc:
                winner = t
                break
        prize = int(pool["pool"])
        self.economy_transfer(int(winner["user_id"]), "gold", prize, "jackpot_win")
        self._exec(
            "UPDATE jackpot_pool SET pool = 0, last_winner = ?, "
            "last_win_at = ?, last_win_amt = ?, next_draw = ? WHERE id = 1",
            (int(winner["user_id"]), int(time.time()), prize,
             int(time.time()) + 86400))
        self._exec("DELETE FROM jackpot_tickets")
        return {"ok": True, "winner": int(winner["user_id"]), "prize": prize,
                "tickets": len(tickets)}

    # ==================== ШАХМАТНЫЙ КЛУБ ====================

    CLUB_BOSS_REWARDS = [15, 20, 30, 40, 60, 80, 120]
    CLUB_ENTRY_FEE = 50
    CLUB_WEEK_LIMIT = 1200
    CLUB_PLAYOFF_NET = 170
    CLUB_MAX_ACTIVE = 3
    CLUB_LEVELS = 7

    def club_create_season(self) -> int:
        now = int(time.time())
        self._exec(
            "INSERT INTO club_seasons (started_at, ends_at, status) "
            "VALUES (?, ?, 'open')", (now, now + 7 * 86400))
        row = self._row(
            "SELECT id FROM club_seasons ORDER BY id DESC LIMIT 1")
        return int(row["id"]) if row else 0

    def club_active_season(self) -> dict:
        row = self._row(
            "SELECT id, started_at, ends_at, status, winner_id "
            "FROM club_seasons WHERE status = 'open' ORDER BY id DESC LIMIT 1")
        if row:
            return dict(row)
        sid = self.club_create_season()
        row = self._row(
            "SELECT id, started_at, ends_at, status, winner_id "
            "FROM club_seasons WHERE id = ?", (sid,))
        return dict(row) if row else {}

    def club_season(self, season_id: int) -> dict | None:
        return self._row(
            "SELECT id, started_at, ends_at, status, winner_id "
            "FROM club_seasons WHERE id = ?", (season_id,))

    def club_set_season_status(self, season_id: int, status: str,
                               winner_id: int | None = None) -> None:
        if winner_id is None:
            self._exec(
                "UPDATE club_seasons SET status = ? WHERE id = ?",
                (status, season_id))
        else:
            self._exec(
                "UPDATE club_seasons SET status = ?, winner_id = ? "
                "WHERE id = ?", (status, winner_id, season_id))

    def club_join(self, user_id: int, season_id: int) -> dict | None:
        if user_id < 0:
            return None
        if self.economy_balance(user_id, "gold") < self.CLUB_ENTRY_FEE:
            return None
        existing = self._row(
            "SELECT season_id, user_id, entry_fee, finished_round, total_won "
            "FROM club_entries WHERE season_id = ? AND user_id = ?",
            (season_id, user_id))
        if existing:
            return dict(existing)
        self.economy_transfer(user_id, "gold", -self.CLUB_ENTRY_FEE,
                              "club_join")
        self._exec(
            "INSERT INTO club_entries (season_id, user_id, entry_fee, "
            "finished_round, total_won) VALUES (?, ?, ?, 0, 0)",
            (season_id, user_id, self.CLUB_ENTRY_FEE))
        return self.club_entry(season_id, user_id)

    def club_entry(self, season_id: int, user_id: int) -> dict | None:
        return self._row(
            "SELECT season_id, user_id, entry_fee, finished_round, total_won "
            "FROM club_entries WHERE season_id = ? AND user_id = ?",
            (season_id, user_id))

    def club_active_entries_count(self, user_id: int) -> int:
        row = self._row(
            "SELECT COUNT(*) AS c FROM club_entries e "
            "JOIN club_seasons s ON s.id = e.season_id "
            "WHERE e.user_id = ? AND s.status IN ('open','playoff')",
            (user_id,))
        return int(row["c"]) if row else 0

    def club_update_progress(self, season_id: int, user_id: int,
                             reward: int) -> dict | None:
        entry = self._row(
            "SELECT finished_round, total_won FROM club_entries "
            "WHERE season_id = ? AND user_id = ?", (season_id, user_id))
        if not entry:
            return None
        new_round = int(entry["finished_round"]) + 1
        new_won = int(entry["total_won"]) + reward
        self._exec(
            "UPDATE club_entries SET finished_round = ?, total_won = ? "
            "WHERE season_id = ? AND user_id = ?",
            (new_round, new_won, season_id, user_id))
        return {"finished_round": new_round, "total_won": new_won}

    def club_win_log(self, user_id: int, season_id: int, amount: int) -> None:
        self._exec(
            "INSERT INTO club_win_log (user_id, season_id, amount, at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, season_id, amount, int(time.time())))

    def club_week_won(self, user_id: int) -> int:
        row = self._row(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM club_win_log "
            "WHERE user_id = ? AND at >= ?",
            (user_id, int(time.time()) - 7 * 86400))
        return int(row["total"]) if row else 0

    def club_top_entries(self, season_id: int, limit: int = 8) -> list[dict]:
        return self._rows(
            "SELECT season_id, user_id, entry_fee, finished_round, total_won "
            "FROM club_entries WHERE season_id = ? "
            "ORDER BY finished_round DESC, total_won DESC LIMIT ?",
            (season_id, limit))

    def club_username(self, user_id: int) -> str:
        row = self._row(
            "SELECT username, first_name FROM users WHERE user_id = ?",
            (user_id,))
        if not row:
            return str(user_id)
        return row["username"] or row["first_name"] or str(user_id)

    def club_season_state(self, user_id: int) -> dict:
        season = self.club_active_season()
        entry = self.club_entry(season["id"], user_id)
        my_round = int(entry["finished_round"]) if entry else 0
        week_won = self.club_week_won(user_id)
        levels = [
            {"round": i + 1, "reward": self.CLUB_BOSS_REWARDS[i],
             "status": "done" if my_round > i else
                        ("open" if my_round == i else "closed")}
            for i in range(self.CLUB_LEVELS)
        ]
        playoff = {"top": [], "finished": False, "winner": None}
        if season.get("status") in ("playoff", "finished"):
            top = [dict(r) for r in self.club_top_entries(season["id"], 8)]
            for t in top:
                t["nick"] = self.club_username(int(t["user_id"]))
            playoff = {
                "top": top,
                "finished": season.get("status") == "finished",
                "winner": season.get("winner_id"),
            }
        return {
            "season": {"id": season["id"], "status": season.get("status"),
                       "end_ts": season.get("ends_at"),
                       "number": season["id"]},
            "entry": dict(entry) if entry else None,
            "bosses": [{"round": i + 1, "reward": self.CLUB_BOSS_REWARDS[i]}
                       for i in range(self.CLUB_LEVELS)],
            "my_round": my_round,
            "week_won": week_won,
            "levels": levels,
            "playoff": playoff,
            "week_limit": self.CLUB_WEEK_LIMIT,
            "entry_fee": self.CLUB_ENTRY_FEE,
        }

    # ==================== ПИТОМЦЫ ====================

    PET_TYPES = {
        "cat":   {"name": "Кот",    "emoji": "🐱", "cost": 200,  "income": 5},
        "dog":   {"name": "Пёс",    "emoji": "🐶", "cost": 400,  "income": 10},
        "fox":   {"name": "Лис",    "emoji": "🦊", "cost": 800,  "income": 20},
        "owl":   {"name": "Сова",   "emoji": "🦉", "cost": 1500, "income": 40},
        "dragon": {"name": "Дракон", "emoji": "🐉", "cost": 3000, "income": 80},
    }
    PET_FEED_COST = 50
    PET_FEED_XP = 25
    PET_HUNGER_SEC = 4 * 3600
    PET_MAX_LEVEL = 10
    PET_PLAY_COOLDOWN = 300

    # --- острова (пассивный доход за GMPOINT) --------------------------
    ISLAND_TYPES = {
        "sand":  {"name": "Песчаный",  "emoji": "🏝️", "cost": 0,   "income": 2,   "base": 0},
        "palm":  {"name": "Пальмовый", "emoji": "🌴", "cost": 150, "income": 6,   "base": 1},
        "volcano": {"name": "Вулкан",  "emoji": "🌋", "cost": 400, "income": 14,  "base": 2},
        "ice":   {"name": "Ледяной",   "emoji": "🧊", "cost": 900, "income": 30,  "base": 3},
        "city":  {"name": "Мегаполис", "emoji": "🏙️", "cost": 2000, "income": 65, "base": 4},
        "zen":   {"name": "Храм",      "emoji": "⛩️", "cost": 5000, "income": 140, "base": 5},
    }
    ISLAND_COLLECT_SEC = 3600
    ISLAND_MAX_LEVEL = 5

    def _ensure_islands(self, user_id: int) -> dict:
        row = self._row("SELECT * FROM islands WHERE user_id = ?", (user_id,))
        if row:
            return dict(row)
        self._exec(
            "INSERT INTO islands (user_id, islands, income_at, total_earned) "
            "VALUES (?, '{}', ?, 0)",
            (user_id, int(time.time())))
        row = self._row("SELECT * FROM islands WHERE user_id = ?", (user_id,))
        return dict(row) if row else {}

    def _user_gmpoint(self, user_id: int) -> int:
        row = self._row("SELECT gmpoint FROM users WHERE user_id = ?", (user_id,))
        return int(row["gmpoint"]) if row else 0

    def _decode_islands(self, raw: str) -> dict:
        try:
            data = json.loads(raw or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        for key in self.ISLAND_TYPES:
            if key not in data:
                data[key] = {"owned": False, "level": 1}
            if not isinstance(data[key], dict):
                data[key] = {"owned": False, "level": 1}
        return data

    def _encode_islands(self, data: dict) -> str:
        return json.dumps(data, ensure_ascii=False)

    def islands_state(self, user_id: int) -> dict:
        rec = self._ensure_islands(user_id)
        data = self._decode_islands(rec["islands"])
        now = int(time.time())
        gained = self._island_gained(rec, data, now)
        return {
            "islands": data,
            "types": [
                {"key": k, "name": v["name"], "emoji": v["emoji"],
                 "cost": v["cost"], "income": v["income"],
                 "max_level": self.ISLAND_MAX_LEVEL}
                for k, v in self.ISLAND_TYPES.items()
            ],
            "income_gained": gained,
            "income_rate": self._island_rate(data),
            "total_earned": int(rec["total_earned"]),
            "gmpoint": self._user_gmpoint(user_id),
        }

    def _island_rate(self, data: dict) -> int:
        total = 0
        for key, spec in self.ISLAND_TYPES.items():
            item = data.get(key) or {}
            if item.get("owned"):
                total += int(spec["income"]) * max(1, int(item.get("level") or 1))
        return total

    def _island_gained(self, rec: dict, data: dict, now: int) -> int:
        rate = self._island_rate(data)
        if rate <= 0:
            return 0
        last = int(rec["income_at"]) or now
        cycles = (now - last) // self.ISLAND_COLLECT_SEC
        if cycles <= 0:
            return 0
        return cycles * rate

    def island_buy(self, user_id: int, key: str) -> dict | None:
        spec = self.ISLAND_TYPES.get(key)
        if not spec:
            return None
        with self._lock:
            rec = self._ensure_islands(user_id)
            data = self._decode_islands(rec["islands"])
            if data[key]["owned"]:
                return None
            cost = int(spec["cost"])
            if (self._user_gmpoint(user_id) or 0) < cost:
                return None
            if not self.spend_gmpoint(user_id, cost):
                return None
            self.log_gmpoint(user_id, -cost, "island_buy")
            data[key] = {"owned": True, "level": 1}
            self._exec(
                "UPDATE islands SET islands = ? WHERE user_id = ?",
                (self._encode_islands(data), user_id))
            return self.islands_state(user_id)

    def island_upgrade(self, user_id: int, key: str) -> dict | None:
        spec = self.ISLAND_TYPES.get(key)
        if not spec:
            return None
        with self._lock:
            rec = self._ensure_islands(user_id)
            data = self._decode_islands(rec["islands"])
            item = data[key]
            if not item["owned"]:
                return None
            level = int(item.get("level") or 1)
            if level >= self.ISLAND_MAX_LEVEL:
                return None
            cost = int(spec["cost"]) * level
            if (self._user_gmpoint(user_id) or 0) < cost:
                return None
            if not self.spend_gmpoint(user_id, cost):
                return None
            self.log_gmpoint(user_id, -cost, "island_upgrade")
            data[key]["level"] = level + 1
            self._exec(
                "UPDATE islands SET islands = ? WHERE user_id = ?",
                (self._encode_islands(data), user_id))
            return self.islands_state(user_id)

    def island_collect(self, user_id: int) -> dict | None:
        with self._lock:
            rec = self._ensure_islands(user_id)
            data = self._decode_islands(rec["islands"])
            now = int(time.time())
            gained = self._island_gained(rec, data, now)
            if gained > 0:
                self.add_gmpoint(user_id, gained)
                self.log_gmpoint(user_id, gained, "island_collect")
            self._exec(
                "UPDATE islands SET income_at = ?, total_earned = total_earned + ? "
                "WHERE user_id = ?", (now, gained, user_id))
            return self.islands_state(user_id)

    def _ensure_pet(self, user_id: int) -> dict:
        row = self._row(
            "SELECT * FROM pet_inventory WHERE user_id = ?", (user_id,))
        if row:
            return dict(row)
        self._exec(
            "INSERT INTO pet_inventory (user_id, pet_type, level, xp, fed_at, "
            "born_at, total_earned) VALUES (?, 'cat', 1, 0, 0, ?, 0)",
            (user_id, int(time.time())))
        row = self._row(
            "SELECT * FROM pet_inventory WHERE user_id = ?", (user_id,))
        return dict(row) if row else {}

    def pet_buy(self, user_id: int, pet_type: str) -> dict | None:
        spec = self.PET_TYPES.get(pet_type)
        if not spec:
            return None
        balance = self.economy_balance(user_id, "gold")
        if balance < int(spec["cost"]):
            return None
        self.economy_transfer(user_id, "gold", -int(spec["cost"]), "pet_buy")
        self._exec(
            "UPDATE pet_inventory SET pet_type = ?, fed_at = 0 "
            "WHERE user_id = ?", (pet_type, user_id))
        return self._ensure_pet(user_id)

    def pet_feed(self, user_id: int) -> dict | None:
        pet = self._ensure_pet(user_id)
        balance = self.economy_balance(user_id, "gold")
        if balance < self.PET_FEED_COST:
            return None
        level = int(pet["level"])
        if level >= self.PET_MAX_LEVEL:
            return None
        self.economy_transfer(user_id, "gold", -self.PET_FEED_COST, "pet_feed")
        xp = int(pet["xp"]) + self.PET_FEED_XP
        new_level = min(self.PET_MAX_LEVEL, level + xp // 100)
        remain = xp % 100
        self._exec(
            "UPDATE pet_inventory SET level = ?, xp = ?, fed_at = ? "
            "WHERE user_id = ?",
            (new_level, remain, int(time.time()), user_id))
        return self._ensure_pet(user_id)

    def pet_collect(self, user_id: int) -> dict | None:
        pet = self._ensure_pet(user_id)
        now = int(time.time())
        spec = self.PET_TYPES.get(pet["pet_type"], self.PET_TYPES["cat"])
        level = int(pet["level"])
        hungry = pet["fed_at"] == 0 or (now - int(pet["fed_at"]) > self.PET_HUNGER_SEC)
        base = int(spec["income"])
        income = base * level
        if hungry:
            income = 0
        self._exec(
            "UPDATE pet_inventory SET born_at = ?, total_earned = total_earned + ? "
            "WHERE user_id = ?", (now, income, user_id))
        if income > 0:
            self.economy_transfer(user_id, "gold", income, "pet_collect")
        return self._ensure_pet(user_id)

    def pet_state(self, user_id: int) -> dict:
        pet = self._ensure_pet(user_id)
        spec = self.PET_TYPES.get(pet["pet_type"], self.PET_TYPES["cat"])
        now = int(time.time())
        hungry = pet["fed_at"] == 0 or (now - int(pet["fed_at"]) > self.PET_HUNGER_SEC)
        level = int(pet["level"])
        base = int(spec["income"])
        income = base * level
        if hungry:
            income = 0
        return {
            "pet": pet, "type": pet["pet_type"],
            "name": spec["name"], "emoji": spec["emoji"],
            "level": level, "xp": int(pet["xp"]),
            "income": income, "hungry": hungry,
            "types": [
                {"key": k, "name": v["name"], "emoji": v["emoji"],
                 "cost": v["cost"], "income": v["income"]}
                for k, v in self.PET_TYPES.items()
            ],
            "feed_cost": self.PET_FEED_COST,
            "max_level": self.PET_MAX_LEVEL,
            "gold": self.economy_balance(user_id, "gold"),
        }

    def pet_play(self, user_id: int) -> dict:
        pet = self._ensure_pet(user_id)
        now = int(time.time())
        last = int(pet.get("last_play_at") or 0)
        cooldown_left = self.PET_PLAY_COOLDOWN - (now - last)
        if cooldown_left > 0:
            return {"ok": False, "error": "cooldown",
                    "cooldown_left": cooldown_left}
        import random
        roll = random.randint(1, 100)
        if roll <= 40:
            result = "miss"
            reward = 0
        elif roll <= 75:
            result = "normal"
            reward = 10 + int(pet["level"]) * 2
        elif roll <= 95:
            result = "good"
            reward = 25 + int(pet["level"]) * 4
        else:
            result = "perfect"
            reward = 60 + int(pet["level"]) * 8
        if reward > 0:
            self.economy_transfer(user_id, "gold", reward, "pet_play")
        self._exec(
            "UPDATE pet_inventory SET last_play_at = ?, "
            "total_earned = total_earned + ? WHERE user_id = ?",
            (now, reward, user_id))
        state = self.pet_state(user_id)
        state["play"] = {"result": result, "reward": reward,
                         "cooldown": self.PET_PLAY_COOLDOWN}
        return state

    def pet_top(self, limit: int = 10) -> list[dict]:
        rows = self._rows(
            "SELECT user_id, pet_type, level, total_earned FROM pet_inventory "
            "ORDER BY total_earned DESC, level DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            spec = self.PET_TYPES.get(r["pet_type"], self.PET_TYPES["cat"])
            r = dict(r)
            r["nick"] = self.club_username(int(r["user_id"]))
            r["emoji"] = spec["emoji"]
            r["name"] = spec["name"]
            out.append(r)
        return out

    def club_history(self, limit: int = 6) -> list[dict]:
        rows = self._rows(
            "SELECT id, started_at, ends_at, status, winner_id "
            "FROM club_seasons WHERE status = 'finished' AND winner_id IS NOT NULL "
            "ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            r = dict(r)
            r["winner_nick"] = self.club_username(int(r["winner_id"]))
            out.append(r)
        return out
