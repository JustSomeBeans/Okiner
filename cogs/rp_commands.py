from __future__ import annotations

# =============================================================================
# cogs/rp_commands.py — All slash commands, grouped as a discord.py Cog
# -----------------------------------------------------------------------------
# Loaded by:    bot.py  (via load_extension("cogs.rp_commands") in setup_hook)
# Imports from: autocomplete.py → EVERYONE_TARGET, rp_target_autocomplete,
#                                 rp_type_autocomplete
#               checks.py       → moderator_only
#               config.py       → MAX_EMBED_DESCRIPTION_LENGTH, MAX_TEXT_LENGTH,
#                                 MAX_TYPE_LENGTH, MAX_URL_LENGTH
#               database.py     → execute_query, fetch_one, fetch_column,
#                                 rp_type_exists, add_rp_type, add_rp_entry
#               utils.py        → PlaceholderTarget, apply_placeholders,
#                                 build_list_messages, is_valid_image_url,
#                                 normalize_image_url, normalize_rp_type,
#                                 truncate_for_embed
#               views.py        → ActionTextConfirmView
#               discord         → discord.Interaction, discord.Guild,
#                                 discord.Member, discord.Embed, discord.Color,
#                                 discord.AllowedMentions, discord.HTTPException
#               discord.app_commands → app_commands.command, guild_only,
#                                 describe, autocomplete, default_permissions,
#                                 AppCommandError, MissingPermissions,
#                                 NoPrivateMessage, CommandOnCooldown
#               discord.ext.commands → commands.Bot, commands.Cog
#               urllib.parse    → urlparse
#               logging, random, re → stdlib
# =============================================================================

import logging
import random
import re
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import database
from autocomplete import EVERYONE_TARGET, rp_target_autocomplete, rp_type_autocomplete
from checks import moderator_only
from config import (
    MAX_EMBED_DESCRIPTION_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_TYPE_LENGTH,
    MAX_URL_LENGTH,
)
from utils import (
    PlaceholderTarget,
    apply_placeholders,
    build_list_messages,
    is_valid_image_url,
    normalize_image_url,
    normalize_rp_type,
    truncate_for_embed,
)
from views import ActionTextConfirmView

TARGET_MENTION_RE = re.compile(r"<@!?(\d+)>")
STANDARD_CASE = "standard"
SELF_CASE = "selfcase"
NULL_CASE = "nullcase"
ALLOWED_COLUMNS = {"texts", "action_texts"} # guard against SQL injection in _fetch_case_entries


async def send_chunked_response(
    interaction: discord.Interaction, messages: list[str], *, ephemeral: bool = True
) -> None:
    """Send one or more response chunks without tripping interaction rules."""
    allowed_mentions = discord.AllowedMentions.none()
    first, *rest = messages
    await interaction.response.send_message(
        first, ephemeral=ephemeral, allowed_mentions=allowed_mentions
    )
    for message in rest:
        await interaction.followup.send(
            message, ephemeral=ephemeral, allowed_mentions=allowed_mentions
        )


class RPCommands(commands.Cog):
    """All roleplay slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Shared RP helpers                                                 #
    # ------------------------------------------------------------------ #

    def _case_display_name(self, case_type: str) -> str:
        return {STANDARD_CASE: "standard", SELF_CASE: "selfcase", NULL_CASE: "nullcase"}.get(
    case_type, case_type  # fall back to the raw string rather than crashing
)

    def _default_action(
        self, actor: discord.abc.User, target: PlaceholderTarget, case_type: str
    ) -> str:
        """Fall back to a simple action line when no custom one is saved."""
        return (
            actor.display_name
            if case_type == NULL_CASE
            else f"{actor.display_name} -> {target.display_name}"
        )

    def _required_action_tags(self, case_type: str) -> list[str]:
        """Figure out which placeholders we expect for each case bucket."""
        return ["{user}"] if case_type == NULL_CASE else ["{user}", "{target}"]

    def _find_member(self, guild: discord.Guild, token: str) -> discord.Member | None:
        """Resolve a typed target token without relying on mentions alone."""
        token = token.strip()
        member_id = None
        if token.isdigit():
            member_id = int(token)
        else:
            match = TARGET_MENTION_RE.fullmatch(token)
            if match:
                member_id = int(match.group(1))
        if member_id is not None:
            return guild.get_member(member_id)
        lowered = token.lower()
        exact = [
            m
            for m in guild.members
            if lowered in {m.display_name.lower(), m.name.lower()}
        ]
        if exact:
            return exact[0]
        partial = [
            m
            for m in guild.members
            if lowered in m.display_name.lower() or lowered in m.name.lower()
        ]
        if partial:
            partial.sort(
                key=lambda m: (
                    not (
                        lowered in m.display_name.lower()
                        and lowered in m.name.lower()
                    ),
                    m.display_name.lower(),
                    m.name.lower(),
                )
            )
            return partial[0]
        return None

    async def _resolve_target(
        self, interaction: discord.Interaction, target: str | None
    ) -> tuple[PlaceholderTarget, str] | None:
        """Turn raw target input into placeholder data plus the matching case."""
        if target is None or not target.strip():
            return PlaceholderTarget("", ""), NULL_CASE
        guild = interaction.guild
        if guild is None:
            return None
        raw_target = target.strip()
        if raw_target.lower().lstrip("@") == EVERYONE_TARGET:
            return PlaceholderTarget(EVERYONE_TARGET, EVERYONE_TARGET), STANDARD_CASE
        member = self._find_member(guild, raw_target)
        if member is None:
            raise RuntimeError("_resolve_target called outside of a guild context")
        return (
            PlaceholderTarget(member.mention, member.display_name),
            SELF_CASE if member.id == interaction.user.id else STANDARD_CASE,
        )
    
    async def _fetch_case_entries(
        self, conn, guild_id: int, rp_type: str, column: str, case_type: str
    ) -> list[str]:
        """Load text pools for a case, falling back to standard when needed."""
        if column not in ALLOWED_COLUMNS:
            raise ValueError(f"Invalid column: {column!r}")
        result = await conn.execute(
            f"SELECT {column} FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND {column} IS NOT NULL",
            (guild_id, rp_type, case_type),
        )
        values = [row[0] for row in await result.fetchall()]
        if values or case_type == STANDARD_CASE:
            return values
        result = await conn.execute(
            f"SELECT {column} FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND {column} IS NOT NULL",
            (guild_id, rp_type, STANDARD_CASE),
        )
        return [row[0] for row in await result.fetchall()]

    async def _fetch_standard_images(
        self, conn, guild_id: int, rp_type: str
    ) -> list[str]:
        """Images stay on the standard pool even when text switches cases."""
        result = await conn.execute(
            "SELECT url FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND url IS NOT NULL",
            (guild_id, rp_type, STANDARD_CASE),
        )
        return [row[0] for row in await result.fetchall()]

    # ------------------------------------------------------------------ #
    #  Text helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _add_text_entry(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        text: str,
        *,
        case_type: str,
    ) -> None:
        """Shared save flow for standard, selfcase, and nullcase embed text."""
        rp_type = normalize_rp_type(rp_type)
        text = text.strip()
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        if not text:
            await interaction.response.send_message(
                "Text entries can't be blank.", ephemeral=True
            )
            return
        if len(text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep text entries under {MAX_TEXT_LENGTH} characters so they stay usable in Discord.",
                ephemeral=True,
            )
            return
        duplicate = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND texts = ?",
            (interaction.guild_id, rp_type, case_type, text),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                f"That {self._case_display_name(case_type)} text is already saved for this RP type.",
                ephemeral=True,
            )
            return
        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=case_type,
            text=text,
        )
        await interaction.response.send_message(
            f"Added {self._case_display_name(case_type)} text to `{rp_type}`.",
            ephemeral=True,
        )

    async def _remove_text_entry(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        text: str,
        *,
        case_type: str,
    ) -> None:
        """Shared remove flow for the case-specific embed text buckets."""
        rp_type = normalize_rp_type(rp_type)
        text = text.strip()
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND texts = ?",
            (interaction.guild_id, rp_type, case_type, text),
        )
        if existing is None:
            await interaction.response.send_message(
                f"That {self._case_display_name(case_type)} text isn't saved under this RP type.",
                ephemeral=True,
            )
            return
        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND texts = ?",
            (interaction.guild_id, rp_type, case_type, text),
        )
        await interaction.response.send_message(
            f"Removed {self._case_display_name(case_type)} text from `{rp_type}`.",
            ephemeral=True,
        )

    async def _list_text_entries(
        self, interaction: discord.Interaction, rp_type: str, *, case_type: str
    ) -> None:
        """Shared list flow for the case-specific embed text buckets."""
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        texts = await database.fetch_column(
            "SELECT DISTINCT texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND texts IS NOT NULL ORDER BY texts COLLATE NOCASE",
            (interaction.guild_id, rp_type, case_type),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(
                f"Saved {self._case_display_name(case_type)} embed texts for `{rp_type}`:",
                texts,
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Action text helpers                                               #
    # ------------------------------------------------------------------ #

    async def _add_action_text_entry(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        action_text: str,
        *,
        case_type: str,
    ) -> None:
        """Shared save flow for the case-specific action text buckets."""
        rp_type = normalize_rp_type(rp_type)
        action_text = action_text.strip()
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        if not action_text:
            await interaction.response.send_message(
                "Action text entries can't be blank.", ephemeral=True
            )
            return
        if len(action_text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep action text entries under {MAX_TEXT_LENGTH} characters so they stay usable in Discord.",
                ephemeral=True,
            )
            return
        duplicate = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, case_type, action_text),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                f"That {self._case_display_name(case_type)} action text is already saved for this RP type.",
                ephemeral=True,
            )
            return
        missing = [
            tag
            for tag in self._required_action_tags(case_type)
            if tag not in action_text and tag.replace("}", "_name}") not in action_text
        ]
        if missing:
            warning = (
                f"Warning: your action text is missing the following dynamic tags: {', '.join(f'`{tag}`' for tag in missing)}.\n\n"
                "How it works:\n"
                "- `{user}` / `{target}` use mention-style placeholders.\n"
                "- `{user_name}` / `{target_name}` use display names.\n\n"
                "Do you want to add it anyway?"
            )
            view = ActionTextConfirmView(
                interaction.user.id,
                interaction.guild_id,
                rp_type,
                action_text,
                case_type=case_type,
            )
            await interaction.response.send_message(warning, view=view, ephemeral=True)
            view.message = await interaction.original_response() # make sure a reference is saved for on_timeout in views.py
            return
        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=case_type,
            action_text=action_text,
        )
        await interaction.response.send_message(
            f"Added {self._case_display_name(case_type)} action text to `{rp_type}`.",
            ephemeral=True,
        )

    async def _remove_action_text_entry(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        action_text: str,
        *,
        case_type: str,
    ) -> None:
        """Shared remove flow for the case-specific action text buckets."""
        rp_type = normalize_rp_type(rp_type)
        action_text = action_text.strip()
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, case_type, action_text),
        )
        if existing is None:
            await interaction.response.send_message(
                f"That {self._case_display_name(case_type)} action text isn't saved under this RP type.",
                ephemeral=True,
            )
            return
        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, case_type, action_text),
        )
        await interaction.response.send_message(
            f"Removed {self._case_display_name(case_type)} action text from `{rp_type}`.",
            ephemeral=True,
        )

    async def _list_action_text_entries(
        self, interaction: discord.Interaction, rp_type: str, *, case_type: str
    ) -> None:
        """Shared list flow for the case-specific action text buckets."""
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        action_texts = await database.fetch_column(
            "SELECT DISTINCT action_texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND action_texts IS NOT NULL ORDER BY action_texts COLLATE NOCASE",
            (interaction.guild_id, rp_type, case_type),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(
                f"Saved {self._case_display_name(case_type)} action texts for `{rp_type}`:",
                action_texts,
            ),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Core RP command                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="rp", description="Perform an interaction between users."
    )
    @app_commands.guild_only()
    @app_commands.describe(
        rp_type="Which interaction to perform", target="Who to target, or everyone"
    )
    @app_commands.autocomplete(
        rp_type=rp_type_autocomplete, target=rp_target_autocomplete
    )
    async def rp(
        self, interaction: discord.Interaction, rp_type: str, target: str | None = None
    ) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message(
                f"I don't know the RP type `{rp_type}` in this server yet.",
                ephemeral=True,
            )
            return
        resolved_target = await self._resolve_target(interaction, target)
        if resolved_target is None:
            await interaction.response.send_message(
                "I couldn't find that target. Pick a member from autocomplete or use `everyone`.",
                ephemeral=True,
            )
            return
        target_info, case_type = resolved_target
        async with self.bot.db_pool.acquire() as conn:
            if case_type == NULL_CASE:
                null_text_rows = await conn.execute(
                    "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND texts IS NOT NULL LIMIT 1",
                    (interaction.guild_id, rp_type, NULL_CASE),
                )
                null_action_rows = await conn.execute(
                    "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND action_texts IS NOT NULL LIMIT 1",
                    (interaction.guild_id, rp_type, NULL_CASE),
                )
                has_null_text = await null_text_rows.fetchone()
                has_null_action_text = await null_action_rows.fetchone()
                if has_null_text is None and has_null_action_text is None:
                    await interaction.response.send_message(
                        f"`{rp_type}` doesn't work without a target.",
                        ephemeral=True,
                    )
                    return
            texts = await self._fetch_case_entries(
                conn, interaction.guild_id, rp_type, "texts", case_type
            )
            action_texts = await self._fetch_case_entries(
                conn, interaction.guild_id, rp_type, "action_texts", case_type
            )
            # Images are alwayss drawn from the standard pool. They're type level flavor,
            # not case specific. This is intentional.
            images = await self._fetch_standard_images(
                conn, interaction.guild_id, rp_type
            )
        raw_action = (
            apply_placeholders(
                random.choice(action_texts), interaction.user, target_info
            ).strip()
            if action_texts
            else self._default_action(interaction.user, target_info, case_type)
        )
        action_line = truncate_for_embed(
            f"**{raw_action}**", MAX_EMBED_DESCRIPTION_LENGTH
        )
        if texts:
            raw_text = apply_placeholders(
                random.choice(texts), interaction.user, target_info
            ).strip()
            rp_line = truncate_for_embed(
                raw_text, MAX_EMBED_DESCRIPTION_LENGTH - len(action_line) - 2
            )
            description = f"{action_line}\n{rp_line}" if rp_line else action_line
        else:
            description = action_line
        description = truncate_for_embed(description, MAX_EMBED_DESCRIPTION_LENGTH)
        valid_images = [
            normalize_image_url(url)
            for url in images
            if is_valid_image_url(normalize_image_url(url))
        ]
        image_url = random.choice(valid_images) if valid_images else None
        embed = discord.Embed(description=description, color=discord.Color.blurple())
        if image_url:
            embed.set_image(url=image_url)
        try:
            await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logging.warning("RP message send failed; retrying without image.", exc_info=True)
            embed.set_image(url=None)  # strip the image from the same object
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                logging.error("RP fallback send also failed.", exc_info=True)

    # ------------------------------------------------------------------ #
    #  Type management                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="addtype", description="Add a new RP type to this server."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    async def add_type(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not rp_type:
            await interaction.response.send_message(
                "RP type names can't be blank.", ephemeral=True
            )
            return
        if len(rp_type) > MAX_TYPE_LENGTH:
            await interaction.response.send_message(
                "RP type names need to stay at 64 characters or fewer.", ephemeral=True
            )
            return
        if not rp_type.replace("-", "").replace("_", "").isalnum():
            await interaction.response.send_message(
                "Keep RP type names to letters, numbers, hyphens, or underscores.",
                ephemeral=True,
            )
            return
        if await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message(
                "That RP type already exists.", ephemeral=True
            )
            return
        await database.add_rp_type(interaction.guild_id, rp_type)
        await interaction.response.send_message(
            f"Added RP type `{rp_type}`.", ephemeral=True
        )

    @app_commands.command(
        name="removetype",
        description="Remove an RP type and everything saved under it.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_type(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        await database.execute_query(
            "DELETE FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        await interaction.response.send_message(
            f"Removed RP type `{rp_type}` and all of its saved entries.", ephemeral=True
        )

    @app_commands.command(
        name="listtype", description="List all RP types configured for this server."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    async def list_type(self, interaction: discord.Interaction) -> None:
        rp_types = await database.fetch_column(
            "SELECT type FROM rp_types WHERE guild_id = ? ORDER BY type COLLATE NOCASE",
            (interaction.guild_id,),
        )
        await send_chunked_response(
            interaction,
            build_list_messages("RP types in this server:", rp_types),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Image management                                                  #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="addimage", description="Save an image URL under an RP type."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_image(
        self, interaction: discord.Interaction, rp_type: str, url: str
    ) -> None:
        rp_type = normalize_rp_type(rp_type)
        url = normalize_image_url(url)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        parsed = urlparse(url)
        if parsed.netloc in {"imgur.com", "www.imgur.com"}:
            await interaction.response.send_message(
                "Please provide the direct image link. It should start with `i.imgur.com`, not `imgur.com`.",
                ephemeral=True,
            )
            return
        if not is_valid_image_url(url):
            await interaction.response.send_message(
                "That doesn't look like a valid `http` or `https` URL.", ephemeral=True
            )
            return
        if len(url) > MAX_URL_LENGTH:
            await interaction.response.send_message(
                "That URL is longer than I want to store safely.", ephemeral=True
            )
            return
        duplicate = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND url = ?",
            (interaction.guild_id, rp_type, STANDARD_CASE, url),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                "That image is already saved for this RP type.", ephemeral=True
            )
            return
        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=STANDARD_CASE,
            url=url,
        )
        await interaction.response.send_message(
            f"Added image to `{rp_type}`.", ephemeral=True
        )

    @app_commands.command(
        name="removeimage", description="Remove a saved image URL from an RP type."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_image(
        self, interaction: discord.Interaction, rp_type: str, url: str
    ) -> None:
        rp_type = normalize_rp_type(rp_type)
        url = normalize_image_url(url)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND url = ?",
            (interaction.guild_id, rp_type, STANDARD_CASE, url),
        )
        if existing is None:
            await interaction.response.send_message(
                "That image URL isn't saved under this RP type.", ephemeral=True
            )
            return
        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND url = ?",
            (interaction.guild_id, rp_type, STANDARD_CASE, url),
        )
        await interaction.response.send_message(
            f"Removed image from `{rp_type}`.", ephemeral=True
        )

    @app_commands.command(
        name="listimage", description="List the saved image URLs for an RP type."
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_image(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return
        images = await database.fetch_column(
            "SELECT DISTINCT url FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND url IS NOT NULL ORDER BY url COLLATE NOCASE",
            (interaction.guild_id, rp_type, STANDARD_CASE),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(f"Saved images for `{rp_type}`:", images),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Text management                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="addtext",
        description="Save a standard embed text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._add_text_entry(interaction, rp_type, text, case_type=STANDARD_CASE)

    @app_commands.command(
        name="removetext",
        description="Remove a standard embed text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._remove_text_entry(
            interaction, rp_type, text, case_type=STANDARD_CASE
        )

    @app_commands.command(
        name="listtext",
        description="List the standard embed text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_text(self, interaction: discord.Interaction, rp_type: str) -> None:
        await self._list_text_entries(interaction, rp_type, case_type=STANDARD_CASE)

    @app_commands.command(
        name="addselftext",
        description="Save a selfcase embed text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_self_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._add_text_entry(interaction, rp_type, text, case_type=SELF_CASE)

    @app_commands.command(
        name="removeselftext",
        description="Remove a selfcase embed text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_self_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._remove_text_entry(interaction, rp_type, text, case_type=SELF_CASE)

    @app_commands.command(
        name="listselftext",
        description="List the selfcase embed text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_self_text(
        self, interaction: discord.Interaction, rp_type: str
    ) -> None:
        await self._list_text_entries(interaction, rp_type, case_type=SELF_CASE)

    @app_commands.command(
        name="addnulltext",
        description="Save a nullcase embed text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_null_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._add_text_entry(interaction, rp_type, text, case_type=NULL_CASE)

    @app_commands.command(
        name="removenulltext",
        description="Remove a nullcase embed text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_null_text(
        self, interaction: discord.Interaction, rp_type: str, text: str
    ) -> None:
        await self._remove_text_entry(interaction, rp_type, text, case_type=NULL_CASE)

    @app_commands.command(
        name="listnulltext",
        description="List the nullcase embed text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_null_text(
        self, interaction: discord.Interaction, rp_type: str
    ) -> None:
        await self._list_text_entries(interaction, rp_type, case_type=NULL_CASE)

    # ------------------------------------------------------------------ #
    #  Action text management                                            #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="addactiontext",
        description="Save a standard action text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._add_action_text_entry(
            interaction, rp_type, action_text, case_type=STANDARD_CASE
        )

    @app_commands.command(
        name="removeactiontext",
        description="Remove a standard action text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._remove_action_text_entry(
            interaction, rp_type, action_text, case_type=STANDARD_CASE
        )

    @app_commands.command(
        name="listactiontext",
        description="List the standard action text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_action_text(
        self, interaction: discord.Interaction, rp_type: str
    ) -> None:
        await self._list_action_text_entries(
            interaction, rp_type, case_type=STANDARD_CASE
        )

    @app_commands.command(
        name="addselfactiontext",
        description="Save a selfcase action text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_self_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._add_action_text_entry(
            interaction, rp_type, action_text, case_type=SELF_CASE
        )

    @app_commands.command(
        name="removeselfactiontext",
        description="Remove a selfcase action text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_self_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._remove_action_text_entry(
            interaction, rp_type, action_text, case_type=SELF_CASE
        )

    @app_commands.command(
        name="listselfactiontext",
        description="List the selfcase action text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_self_action_text(
        self, interaction: discord.Interaction, rp_type: str
    ) -> None:
        await self._list_action_text_entries(interaction, rp_type, case_type=SELF_CASE)

    @app_commands.command(
        name="addnullactiontext",
        description="Save a nullcase action text template under an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_null_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._add_action_text_entry(
            interaction, rp_type, action_text, case_type=NULL_CASE
        )

    @app_commands.command(
        name="removenullactiontext",
        description="Remove a nullcase action text template from an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_null_action_text(
        self, interaction: discord.Interaction, rp_type: str, action_text: str
    ) -> None:
        await self._remove_action_text_entry(
            interaction, rp_type, action_text, case_type=NULL_CASE
        )

    @app_commands.command(
        name="listnullactiontext",
        description="List the nullcase action text templates for an RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_null_action_text(
        self, interaction: discord.Interaction, rp_type: str
    ) -> None:
        await self._list_action_text_entries(interaction, rp_type, case_type=NULL_CASE)

    # ------------------------------------------------------------------ #
    #  Error handler                                                     #
    # ------------------------------------------------------------------ #

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(error, app_commands.MissingPermissions):
            message = "That one is for mods only."
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "That command only works inside a server."
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = (
                f"That command is cooling down. Try again in {error.retry_after:.1f}s."
            )
        else:
            logging.error(
                "Unhandled app command error",
                exc_info=(type(original), original, original.__traceback__),
            )
            message = (
                "Something went wrong while running that command. The error was logged."
            )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RPCommands(bot))
