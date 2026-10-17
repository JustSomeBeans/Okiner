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
from autocomplete import rp_target_autocomplete, rp_type_autocomplete
from checks import moderator_only
from config import (
    EVERYONE_TARGET,
    MAX_EMBED_DESCRIPTION_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_TYPE_LENGTH,
    MAX_URL_LENGTH,
    NULL_CASE,
    SELF_CASE,
    STANDARD_CASE,
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
from views import ActionTextConfirmView, AddRPOptionsView, EditRPOptionsView, ManageRPView, RPBackView

TARGET_MENTION_RE = re.compile(r"<@!?(\d+)>")
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
    ) -> tuple[PlaceholderTarget, str, int | None] | None:
        """Turn raw target input into placeholder data plus the matching case."""
        if target is None or not target.strip():
            return PlaceholderTarget("", ""), NULL_CASE, None
        guild = interaction.guild
        if guild is None:
            return None
        raw_target = target.strip()
        if raw_target.lower().lstrip("@") == EVERYONE_TARGET:
            return PlaceholderTarget(EVERYONE_TARGET, EVERYONE_TARGET), STANDARD_CASE, None
        member = self._find_member(guild, raw_target)
        if member is None:
            raise RuntimeError("_resolve_target called outside of a guild context")
        return (
            PlaceholderTarget(member.mention, member.display_name),
            SELF_CASE if member.id == interaction.user.id else STANDARD_CASE,
            member.id,
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

    async def _execute_rp(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        target_info: PlaceholderTarget,
        case_type: str,
        *,
        view: discord.ui.View | None = None,
    ) -> discord.Embed | None:
        """Run the shared RP pipeline, send the embed, and return the sent embed."""
        send_view = view if view is not None else discord.utils.MISSING
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
                    return None
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
            await interaction.response.send_message(
                embed=embed,
                view=send_view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return embed
        except discord.HTTPException:
            logging.warning("RP message send failed; retrying without image.", exc_info=True)
            embed.set_image(url=None)  # strip the image from the same object
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        embed=embed,
                        view=send_view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await interaction.response.send_message(
                        embed=embed,
                        view=send_view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                return embed
            except discord.HTTPException:
                logging.error("RP fallback send also failed.", exc_info=True)
                return None

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
        target_info, case_type, resolved_target_id = resolved_target
        show_back_button = case_type != SELF_CASE and case_type != NULL_CASE
        view = (
            RPBackView(
                cog=self,
                rp_type=rp_type,
                original_actor_id=interaction.user.id,
                target_id=resolved_target_id,
                guild_id=interaction.guild_id,
            )
            if show_back_button
            else None
        )
        embed = await self._execute_rp(
            interaction,
            rp_type,
            target_info,
            case_type,
            view=view,
        )
        if embed is None:
            return
        if view is not None:
            view.message = await interaction.original_response()

    # ------------------------------------------------------------------ #
    #  Type management                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="add_rp",
        description="Create a new RP type and initial entries in a guided flow.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.describe(
        rp_type="Name of the new RP type to create",
        image_url="URL pointing to a 3rd party image host (optional if attaching image_file)",
        image_file="Direct image file upload attachment (optional if providing image_url)",
    )
    async def add_rp(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        image_url: str | None = None,
        image_file: discord.Attachment | None = None,
    ) -> None:
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
                "That RP type already exists. Use `/edit_rp` instead.",
                ephemeral=True,
            )
            return

        has_file = image_file is not None
        has_url = image_url is not None and len(image_url.strip()) > 0

        if not (has_file ^ has_url):
            if not has_file and not has_url:
                await interaction.response.send_message(
                    "❌ **Error:** You must provide either an **image upload** OR an **image link**.",
                    ephemeral=True,
                )
                return
            else:
                await interaction.response.send_message(
                    "❌ **Error:** You cannot provide both an image upload and a link. Please choose only one option.",
                    ephemeral=True,
                )
                return

        resolved_image_url = None
        if has_file:
            if image_file.content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                await interaction.response.send_message(
                    "❌ **Error:** Invalid image file type. Please upload a PNG, JPEG, WEBP, or GIF image.",
                    ephemeral=True,
                )
                return
            resolved_image_url = image_file.url
        else:
            resolved_image_url = normalize_image_url(image_url)
            parsed = urlparse(resolved_image_url)
            if parsed.netloc in {"imgur.com", "www.imgur.com"}:
                await interaction.response.send_message(
                    "Please provide the direct image link. It should start with `i.imgur.com`, not `imgur.com`.",
                    ephemeral=True,
                )
                return
            if not is_valid_image_url(resolved_image_url):
                await interaction.response.send_message(
                    "That doesn't look like a valid `http` or `https` URL.", ephemeral=True
                )
                return
            if len(resolved_image_url) > MAX_URL_LENGTH:
                await interaction.response.send_message(
                    "That URL is longer than I want to store safely.", ephemeral=True
                )
                return

        view = AddRPOptionsView(interaction.user.id, rp_type, resolved_image_url, self)
        await interaction.response.send_message(
            f"Configuring new RP type `{rp_type}`. Select the case configuration mode:",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def _handle_add_rp_submission(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        image_url: str,
        std_text: str,
        std_action: str,
        case_mode: str,
        self_text: str | None,
        null_text: str | None,
    ) -> None:
        rp_type = normalize_rp_type(rp_type)
        if await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message(
                "That RP type already exists. Use `/edit_rp` instead.",
                ephemeral=True,
            )
            return

        std_text = std_text.strip()
        if not std_text or len(std_text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Standard text must be between 1 and {MAX_TEXT_LENGTH} characters.", ephemeral=True
            )
            return

        std_action = std_action.strip()
        if not std_action or len(std_action) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Standard action text must be between 1 and {MAX_TEXT_LENGTH} characters.", ephemeral=True
            )
            return

        await database.add_rp_type(interaction.guild_id, rp_type)

        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=STANDARD_CASE,
            url=image_url,
        )
        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=STANDARD_CASE,
            text=std_text,
        )

        missing_std = [
            tag
            for tag in self._required_action_tags(STANDARD_CASE)
            if tag not in std_action and tag.replace("}", "_name}") not in std_action
        ]
        if missing_std:
            warning = (
                f"Warning: your standard action text is missing the following dynamic tags: {', '.join(f'`{tag}`' for tag in missing_std)}.\n\n"
                "Do you want to add it anyway?"
            )
            view = ActionTextConfirmView(
                interaction.user.id,
                interaction.guild_id,
                rp_type,
                std_action,
                case_type=STANDARD_CASE,
            )
            await interaction.response.send_message(warning, view=view, ephemeral=True)
            view.message = await interaction.original_response()
            return

        await database.add_rp_entry(
            interaction.user.id,
            interaction.guild_id,
            rp_type,
            case_type=STANDARD_CASE,
            action_text=std_action,
        )

        if case_mode in {"self", "standard_self_null"}:
            if self_text and self_text.strip():
                st = self_text.strip()
                if len(st) <= MAX_TEXT_LENGTH:
                    await database.add_rp_entry(
                        interaction.user.id,
                        interaction.guild_id,
                        rp_type,
                        case_type=SELF_CASE,
                        text=st,
                    )

        if case_mode in {"null", "standard_self_null"}:
            if null_text and null_text.strip():
                nt = null_text.strip()
                if len(nt) <= MAX_TEXT_LENGTH:
                    await database.add_rp_entry(
                        interaction.user.id,
                        interaction.guild_id,
                        rp_type,
                        case_type=NULL_CASE,
                        text=nt,
                    )

        await interaction.response.send_message(
            f"Successfully created RP type `{rp_type}`!",
            ephemeral=True,
        )

    @app_commands.command(
        name="edit_rp",
        description="Append additional data to an existing RP type.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.describe(rp_type="Existing RP type to add data to")
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def edit_rp(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message(
                f"Unknown RP type `{rp_type}`. Use `/add_rp` to create it first.",
                ephemeral=True,
            )
            return

        view = EditRPOptionsView(interaction.user.id, rp_type, self)
        await interaction.response.send_message(
            f"Editing RP type `{rp_type}`. Select data pool to add to:",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def _handle_edit_rp_submission(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        pool_type: str,
        value: str,
    ) -> None:
        rp_type = normalize_rp_type(rp_type)
        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        value = value.strip()
        if not value:
            await interaction.response.send_message("Value cannot be blank.", ephemeral=True)
            return

        case_map = {
            "std_img": (STANDARD_CASE, "url"),
            "std_text": (STANDARD_CASE, "texts"),
            "std_action": (STANDARD_CASE, "action_texts"),
            "self_text": (SELF_CASE, "texts"),
            "self_action": (SELF_CASE, "action_texts"),
            "null_text": (NULL_CASE, "texts"),
            "null_action": (NULL_CASE, "action_texts"),
        }
        case_type, col = case_map.get(pool_type, (STANDARD_CASE, "texts"))

        if col == "url":
            value = normalize_image_url(value)
            parsed = urlparse(value)
            if parsed.netloc in {"imgur.com", "www.imgur.com"}:
                await interaction.response.send_message(
                    "Please provide the direct image link (`i.imgur.com`).", ephemeral=True
                )
                return
            if not is_valid_image_url(value) or len(value) > MAX_URL_LENGTH:
                await interaction.response.send_message("Invalid image URL.", ephemeral=True)
                return
            await database.add_rp_entry(
                interaction.user.id, interaction.guild_id, rp_type, case_type=case_type, url=value
            )
            await interaction.response.send_message(f"Added image to `{rp_type}`.", ephemeral=True)
            return

        if len(value) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(f"Text exceeds {MAX_TEXT_LENGTH} characters.", ephemeral=True)
            return

        if col == "action_texts":
            missing = [
                tag
                for tag in self._required_action_tags(case_type)
                if tag not in value and tag.replace("}", "_name}") not in value
            ]
            if missing:
                warning = (
                    f"Warning: your action text is missing dynamic tags: {', '.join(f'`{tag}`' for tag in missing)}.\n\n"
                    "Do you want to add it anyway?"
                )
                view = ActionTextConfirmView(
                    interaction.user.id,
                    interaction.guild_id,
                    rp_type,
                    value,
                    case_type=case_type,
                )
                await interaction.response.send_message(warning, view=view, ephemeral=True)
                view.message = await interaction.original_response()
                return
            await database.add_rp_entry(
                interaction.user.id, interaction.guild_id, rp_type, case_type=case_type, action_text=value
            )
            await interaction.response.send_message(f"Added {self._case_display_name(case_type)} action text to `{rp_type}`.", ephemeral=True)
            return

        await database.add_rp_entry(
            interaction.user.id, interaction.guild_id, rp_type, case_type=case_type, text=value
        )
        await interaction.response.send_message(f"Added {self._case_display_name(case_type)} text to `{rp_type}`.", ephemeral=True)

    @app_commands.command(
        name="manage_rp",
        description="Manage RP types and entries (list, edit, delete).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    async def manage_rp(self, interaction: discord.Interaction) -> None:
        rp_types = await database.fetch_column(
            "SELECT type FROM rp_types WHERE guild_id = ? ORDER BY type COLLATE NOCASE",
            (interaction.guild_id,),
        )
        if not rp_types:
            await interaction.response.send_message(
                "No RP types configured in this server yet. Use `/add_rp` first.",
                ephemeral=True,
            )
            return

        view = ManageRPView(interaction.user.id, interaction.guild_id, rp_types, self)
        await interaction.response.send_message(
            "Select an RP type to manage:",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

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
