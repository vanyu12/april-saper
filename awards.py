import game


def metrics(db, user_id: int) -> dict:
    user = db.user(user_id)
    if not user:
        return {}
    refs = db.referrals(user_id)
    return {
        "games_played": int(user["games_played"]),
        "games_won": int(user["games_won"]),
        "best_multiplier": float(user["best_multiplier"]),
        "balance": int(user["balance"]),
        "deposits_count": db.count_deposits(user_id),
        "duels_won": int(user.get("duels_won") or 0),
        "referrals": int(refs["total"]),
        "spin_day": int(user.get("spin_day") or 1),
    }


def evaluate(db, user_id: int) -> list[dict]:
    user = db.user(user_id)
    if not user:
        return []
    claimed = db.user_achievements(user_id)
    stats = metrics(db, user_id)
    earned = []
    for ach in game.ACHIEVEMENTS:
        key = ach["key"]
        if key in claimed:
            continue
        if stats.get(ach["metric"], 0) < ach["target"]:
            continue
        if not db.claim_achievement(user_id, key):
            continue
        db.add_balance(user_id, int(ach["reward"]))
        db.add_xp(user_id, int(ach["xp"]))
        earned.append(dict(ach))
    return earned
