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
    """Keep RP type names consistent so autocomplete and lookups stay predictable."""
    return raw_value.strip().lower()


def normalize_image_url(url: str) -> str:
    """Clean up pasted image URLs before we validate or store them."""
    return url.strip().strip("<>")


def is_valid_image_url(url: str) -> bool:
    """Do a lightweight URL sanity check before storing links."""
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
    """Split long list output into safe message-sized chunks."""
    if not entries:
        return [f"{title}\nNothing saved yet."]

    chunks: list[str] = []
    current_chunk = title

    for index, entry in enumerate(entries, start=1):
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