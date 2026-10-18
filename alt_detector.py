from __future__ import annotations

import datetime
import discord

FACTOR_LABELS = {
    "age": "Account age",
    "activity": "Activity",
    "usernameWords": "Username",
    "usernameSymbols": "Username ending",
    "displaynameWords": "Display name",
    "displaynameCaps": "Display name caps",
    "displaynameSymbols": "Display name symbols",
    "flags": "User flags",
    "booster": "Server boost",
    "pfp": "Avatar",
    "banner": "Banner",
    "custom": "Custom checks"
}

def calculate_alt_score(member: discord.Member | discord.User) -> dict:
    """
    Pure Python alt detector analysis for a discord Member or User.
    Calculates account age, avatar state, flags, booster status, etc.
    Returns a dict with total score and category scores.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    created_at = member.created_at
    age_days = (now - created_at).days

    # Age score
    if age_days <= 3:
        age_score = -6
    elif age_days <= 7:
        age_score = -4
    elif age_days <= 30:
        age_score = -2
    elif age_days > 1095:  # 3 years
        age_score = 4
    elif age_days > 365:
        age_score = 1
    else:
        age_score = 0

    # Avatar score (pfp)
    if hasattr(member, "guild_avatar") and member.guild_avatar:
        pfp_score = 2
    elif member.avatar:
        if member.avatar.is_animated():
            pfp_score = 2
        else:
            pfp_score = 1
    else:
        pfp_score = 0

    # Banner score
    banner_score = 2 if getattr(member, "banner", None) else 0

    # Booster score (if member)
    booster_score = 1 if isinstance(member, discord.Member) and member.premium_since else 0

    # Username heuristics
    username = member.name
    username_symbols_score = 0
    if username and any(not c.isalnum() for c in username[-4:]):
        username_symbols_score = -2

    # Flags
    flags_score = 0
    if hasattr(member, "public_flags") and member.public_flags:
        if member.public_flags.active_developer or member.public_flags.early_supporter or member.public_flags.verified_bot_developer:
            flags_score = 2

    categories = {
        "age": age_score,
        "activity": 0,
        "usernameWords": 0,
        "usernameSymbols": username_symbols_score,
        "displaynameWords": 0,
        "displaynameCaps": 0,
        "displaynameSymbols": 0,
        "flags": flags_score,
        "booster": booster_score,
        "pfp": pfp_score,
        "banner": banner_score,
        "custom": 0,
    }

    total = sum(v for v in categories.values() if isinstance(v, int))
    return {"total": total, "categories": categories}

def get_score_summary(total_score: int) -> tuple[str, int]:
    """Returns (label, color_int)."""
    if total_score >= 8:
        return "Highly trusted", 0x2ecc71
    elif total_score >= 3:
        return "Trusted", 0x3498db
    elif total_score >= -1:
        return "Neutral", 0x95a5a6
    elif total_score >= -5:
        return "Suspicious", 0xe67e22
    else:
        return "High risk", 0xe74c3c

def format_signed_score(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)

def format_account_age(created_at: datetime.datetime) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    diff = now - created_at
    days = diff.days
    if days < 1:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} old"
    elif days < 30:
        return f"{days} day{'s' if days != 1 else ''} old"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} old"
    else:
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} old"
