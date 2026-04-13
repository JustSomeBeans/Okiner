from __future__ import annotations

# =============================================================================
# utils.py — Pure, stateless helper functions
# -----------------------------------------------------------------------------
# Imported by:  autocomplete.py     → normalize_rp_type
#               cogs/rp_commands.py → normalize_rp_type, normalize_image_url,
#                                     is_valid_image_url, truncate_for_embed,
#                                     build_list_messages
# Imports from: config.py → MAX_MESSAGE_LENGTH
#               discord   → discord.abc.User, discord.Member  (apply_placeholders)
#               urllib    → urlparse  (is_valid_image_url)
# =============================================================================

from urllib.parse import urlparse

import discord

from config import MAX_MESSAGE_LENGTH


def normalize_rp_type(raw_value: str) -> str:
    """Keep RP type names consistent so autocomplete and lookups stay predictable.

    Types are stored lowercase, so we normalize on the way in and on every lookup.
    If you ever change this, make sure autocomplete.py and the DB queries stay in sync.
    """
    return raw_value.strip().lower()


def normalize_image_url(url: str) -> str:
    """Clean up pasted image URLs before we validate or store them.

    Discord wraps URLs in angle brackets when you paste them with Shift+Enter
    or in certain embed contexts, so we strip those off first.
    """
    return url.strip().strip("<>")


def is_valid_image_url(url: str) -> bool:
    """Do a lightweight URL sanity check before storing links.

    We're not fetching the URL to verify it's actually an image — that would
    be slow and leak the bot's IP. This just makes sure it's a real-looking
    http/https URL with a host. Discord will handle the actual embed validation.
    """
    if not url or any(character.isspace() for character in url):
        return False

    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def apply_placeholders(template: str, actor: discord.abc.User, target: discord.Member) -> str:
    """Fill the simple placeholders we support inside RP text."""
    return (
        template.replace("{user}", actor.mention)
        .replace("{target}", target.mention)
        .replace("{user_name}", actor.display_name)
        .replace("{target_name}", target.display_name)
    )


def truncate_for_embed(text: str, limit: int) -> str:
    """Trim text to a Discord-safe embed length without chopping mid-error."""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def build_list_messages(title: str, entries: list[str]) -> list[str]:
    """Split long list output into safe message-sized chunks.

    Discord's message limit is 2000 chars; we use MAX_MESSAGE_LENGTH (1900) to leave
    some headroom. Each chunk restarts with the title so it's clear what you're looking at
    if it ends up spanning multiple messages.
    """
    if not entries:
        return [f"{title}\nNothing saved yet."]

    chunks: list[str] = []
    current_chunk = title

    for index, entry in enumerate(entries, start=1):
        # Backticks inside code blocks break the formatting, so we swap them out.
        safe_entry = entry.replace("```", "'''")
        if len(safe_entry) > 1200:
            safe_entry = f"{safe_entry[:1197]}..."
        line = f"\n{index}. {safe_entry}"
        if len(current_chunk) + len(line) > MAX_MESSAGE_LENGTH:
            chunks.append(current_chunk)
            current_chunk = f"{title}\n{index}. {safe_entry}"
        else:
            current_chunk += line

    chunks.append(current_chunk)
    return chunks