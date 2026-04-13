from __future__ import annotations

# =============================================================================
# cogs/rp_commands.py — All slash commands, grouped as a discord.py Cog
# -----------------------------------------------------------------------------
# Loaded by:    bot.py  (via load_extension("cogs.rp_commands") in setup_hook)
# Imports from: autocomplete.py → rp_type_autocomplete
#               checks.py       → moderator_only
#               config.py       → MAX_EMBED_DESCRIPTION_LENGTH, MAX_TEXT_LENGTH,
#                                  MAX_TYPE_LENGTH, MAX_URL_LENGTH
#               database.py     → execute_query, fetch_one, fetch_column,
#                                  rp_type_exists, add_rp_type, add_rp_entry,
#                                  add_self_case
#               utils.py        → normalize_rp_type, normalize_image_url,
#                                  is_valid_image_url, truncate_for_embed,
#                                  build_list_messages
#               views.py        → ActionTextConfirmView
#               discord         → discord.Interaction, discord.Member,
#                                  discord.Embed, discord.Color,
#                                  discord.AllowedMentions, discord.HTTPException
#               discord.app_commands → app_commands.command, app_commands.guild_only,
#                                      app_commands.describe, app_commands.autocomplete,
#                                      app_commands.default_permissions,
#                                      app_commands.AppCommandError,
#                                      app_commands.MissingPermissions,
#                                      app_commands.NoPrivateMessage,
#                                      app_commands.CommandOnCooldown
#               discord.ext.commands → commands.Bot, commands.Cog
#               urllib           → urlparse  (imgur domain check in add_image)
#               logging, random  → stdlib
# =============================================================================

import logging
import random
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import database
from autocomplete import rp_type_autocomplete
from checks import moderator_only
from config import MAX_EMBED_DESCRIPTION_LENGTH, MAX_TEXT_LENGTH, MAX_TYPE_LENGTH, MAX_URL_LENGTH
from utils import (
    apply_placeholders,
    build_list_messages,
    is_valid_image_url,
    normalize_image_url,
    normalize_rp_type,
    truncate_for_embed,
)
from views import ActionTextConfirmView


async def send_chunked_response(
    interaction: discord.Interaction,
    messages: list[str],
    *,
    ephemeral: bool = True,
) -> None:
    """Send one or more response chunks without tripping interaction rules.

    Discord requires the first response to go through interaction.response and all
    follow-ups through interaction.followup — you can't call response.send_message twice.
    build_list_messages handles the splitting; this handles the sending.
    """
    allowed_mentions = discord.AllowedMentions.none()
    first_message, *remaining_messages = messages
    await interaction.response.send_message(
        first_message,
        ephemeral=ephemeral,
        allowed_mentions=allowed_mentions,
    )
    for message in remaining_messages:
        await interaction.followup.send(
            message,
            ephemeral=ephemeral,
            allowed_mentions=allowed_mentions,
        )


class RPCommands(commands.Cog):
    """All roleplay slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Core RP command                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="rp", description="Perform an interaction between users.")
    @app_commands.guild_only()
    @app_commands.describe(rp_type="Which interaction to perform", target="Who to target")
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def rp(self, interaction: discord.Interaction, rp_type: str, target: discord.Member) -> None:
        rp_type = normalize_rp_type(rp_type)

        # guild_id can theoretically be None even with @guild_only if something goes sideways
        if interaction.guild_id is None or self.bot.db_pool is None:
            await interaction.response.send_message("This command only works inside a server.", ephemeral=True)
            return

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message(
                f"I don't know the RP type `{rp_type}` in this server yet.",
                ephemeral=True,
            )
            return

        texts, action_texts, images = [], [], []
        handled_by_self_case = False

        if interaction.user == target:
            self_case = await database.fetch_one(
                "SELECT texts, action_texts, url FROM rp_self_cases WHERE guild_id = ? AND type = ?",
                (interaction.guild_id, rp_type),
            )
            if self_case is not None:
                handled_by_self_case = True
                self_text, self_action, self_url = self_case
                if self_text:
                    texts.append(self_text)
                if self_action:
                    action_texts.append(self_action)
                if self_url:
                    images.append(self_url)

        if not handled_by_self_case:
            async with self.bot.db_pool.acquire() as conn:
                text_rows = await conn.execute(
                    "SELECT texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts IS NOT NULL",
                    (interaction.guild_id, rp_type),
                )
                texts = [row[0] for row in await text_rows.fetchall()]

                action_text_rows = await conn.execute(
                    "SELECT action_texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts IS NOT NULL",
                    (interaction.guild_id, rp_type),
                )
                action_texts = [row[0] for row in await action_text_rows.fetchall()]

                image_rows = await conn.execute(
                    "SELECT url FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url IS NOT NULL",
                    (interaction.guild_id, rp_type),
                )
                images = [row[0] for row in await image_rows.fetchall()]

        if action_texts:
            # apply_placeholders handles all four {user}/{target}/{user_name}/{target_name} substitutions
            raw_action = apply_placeholders(random.choice(action_texts), interaction.user, target)
        else:
            raw_action = f"{interaction.user.display_name} → {target.display_name}"

        action_line = truncate_for_embed(f"**{raw_action}**", MAX_EMBED_DESCRIPTION_LENGTH)

        if texts:
            raw_text = apply_placeholders(random.choice(texts), interaction.user, target)
            rp_line = truncate_for_embed(raw_text, MAX_EMBED_DESCRIPTION_LENGTH - len(action_line) - 2)
            description = f"{action_line}\n{rp_line}"
        else:
            description = action_line

        description = truncate_for_embed(description, MAX_EMBED_DESCRIPTION_LENGTH)

        normalized_images = [normalize_image_url(url) for url in images]
        valid_images = [url for url in normalized_images if is_valid_image_url(url)]
        image_url = random.choice(valid_images) if valid_images else None

        embed = discord.Embed(description=description, color=discord.Color.blurple())
        if image_url:
            embed.set_image(url=image_url)

        try:
            await interaction.response.send_message(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            # Most likely a bad image URL that Discord couldn't load. Try again without it.
            logging.warning("RP message send failed; retrying without image.", exc_info=True)
            fallback_embed = discord.Embed(description=description, color=discord.Color.blurple())
            # By the time we're in the except block the response might already be marked done
            # even if it technically errored, so we have to check before deciding which path to use.
            if interaction.response.is_done():
                await interaction.followup.send(embed=fallback_embed)
            else:
                await interaction.response.send_message(embed=fallback_embed)

    # ------------------------------------------------------------------ #
    #  Self Case Management                                              #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="addselfcase", description="Set a custom response for when a user targets themselves.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_self_case(
        self,
        interaction: discord.Interaction,
        rp_type: str,
        text: str | None = None,
        action_text: str | None = None,
        image: str | None = None,
    ) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        if not text and not action_text and not image:
            await interaction.response.send_message(
                "You must provide at least one of: text, action_text, or image.", ephemeral=True
            )
            return

        if text and len(text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep text under {MAX_TEXT_LENGTH} characters.", ephemeral=True
            )
            return

        if action_text and len(action_text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep action text under {MAX_TEXT_LENGTH} characters.", ephemeral=True
            )
            return

        if image:
            image = normalize_image_url(image)
            parsed = urlparse(image)
            if parsed.netloc in {"imgur.com", "www.imgur.com"}:
                await interaction.response.send_message(
                    "Please provide the direct image link (Right-click → Copy image address). "
                    "It should start with `i.imgur.com`, not `imgur.com`.",
                    ephemeral=True,
                )
                return

            if not is_valid_image_url(image):
                await interaction.response.send_message(
                    "That doesn't look like a valid URL.", ephemeral=True
                )
                return

            if len(image) > MAX_URL_LENGTH:
                await interaction.response.send_message(
                    "That URL is too long.", ephemeral=True
                )
                return

        await database.add_self_case(interaction.guild_id, rp_type, text, action_text, image)
        await interaction.response.send_message(f"Set self case override for `{rp_type}`.", ephemeral=True)
    
    @app_commands.command(name="removeselfcase", description="Remove the custom self-targeting response for an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_self_case(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        existing = await database.fetch_self_case(interaction.guild_id, rp_type)
        if not existing:
            await interaction.respone.send_message("No self case override is set for `{rp_type}`.", ephemeral=True)
            return
        
        await database.remove_self_case(interaction.guild_id, rp_type)
        await interaction.response.send_message(f"Removed self case override for `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="listselfcase", description="Show the custom self-targeting response configured for an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_self_case(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        row = await database.fetch_self_case(interaction.guild_id, rp_type)
        if not row:
            await interaction.response.send_message(f"No self case override is set for `{rp_type}`.", ephemeral=True)
            return

        text, action_text, url = row
        
        details = [f"**Self Case for `{rp_type}`:**"]
        details.append(f"**Action Text:** {action_text or '*None (Default)*'}")
        details.append(f"**Embed Text:** {text or '*None*'}")
        details.append(f"**Image URL:** {url or '*None*'}")

        await interaction.response.send_message("\n".join(details), ephemeral=True)

    # ------------------------------------------------------------------ #
    #  Type management                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="addtype", description="Add a new RP type to this server.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    # default_permissions hides the command in the UI for users without the permission.
    # moderator_only() is the actual runtime enforcement — default_permissions alone can be
    # overridden by server admins in the Discord integration settings, so we want both.
    async def add_type(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not rp_type:
            await interaction.response.send_message("RP type names can't be blank.", ephemeral=True)
            return

        if len(rp_type) > MAX_TYPE_LENGTH:
            await interaction.response.send_message(
                f"RP type names need to stay under {MAX_TYPE_LENGTH} characters.", ephemeral=True
            )
            return

        if not rp_type.replace("-", "").replace("_", "").isalnum():
            # Strip allowed separators first, then check the remainder is alphanumeric.
            # Keeps type names clean and autocomplete-friendly without being overly strict.
            await interaction.response.send_message(
                "Keep RP type names to letters, numbers, hyphens, or underscores.",
                ephemeral=True,
            )
            return

        if await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("That RP type already exists.", ephemeral=True)
            return

        await database.add_rp_type(interaction.guild_id, rp_type)
        await interaction.response.send_message(f"Added RP type `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="removetype", description="Remove an RP type and everything saved under it.")
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
        # The foreign key cascade in rp_schema.sql takes care of deleting all
        # roleplay_entries rows that reference this type, so we don't need a second query.
        await interaction.response.send_message(
            f"Removed RP type `{rp_type}` and all of its saved entries.",
            ephemeral=True,
        )

    @app_commands.command(name="listtype", description="List all RP types configured for this server.")
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

    @app_commands.command(name="addimage", description="Save an image URL under an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_image(self, interaction: discord.Interaction, rp_type: str, url: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        url = normalize_image_url(url)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        parsed = urlparse(url)
        if parsed.netloc in {"imgur.com", "www.imgur.com"}:
            # imgur gallery/page URLs don't embed properly in Discord — the image never shows.
            # i.imgur.com links are the actual image files and work fine.
            await interaction.response.send_message(
                "Please provide the direct image link (Right-click → Copy image address). "
                "It should start with `i.imgur.com`, not `imgur.com`.",
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
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
            (interaction.guild_id, rp_type, url),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                "That image is already saved for this RP type.", ephemeral=True
            )
            return

        await database.add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, url=url)
        await interaction.response.send_message(f"Added image to `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="removeimage", description="Remove a saved image URL from an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_image(self, interaction: discord.Interaction, rp_type: str, url: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        url = normalize_image_url(url)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
            (interaction.guild_id, rp_type, url),
        )
        if existing is None:
            await interaction.response.send_message(
                "That image URL isn't saved under this RP type.", ephemeral=True
            )
            return

        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
            (interaction.guild_id, rp_type, url),
        )
        await interaction.response.send_message(f"Removed image from `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="listimage", description="List the saved image URLs for an RP type.")
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
            """
            SELECT DISTINCT url
            FROM roleplay_entries
            WHERE guild_id = ? AND type = ? AND url IS NOT NULL
            ORDER BY url COLLATE NOCASE
            """,
            (interaction.guild_id, rp_type),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(f"Saved images for `{rp_type}`:", images),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Text management                                                   #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="addtext", description="Save an embed text template under an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_text(self, interaction: discord.Interaction, rp_type: str, text: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        text = text.strip()

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        if not text:
            await interaction.response.send_message("Text entries can't be blank.", ephemeral=True)
            return

        if len(text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep text entries under {MAX_TEXT_LENGTH} characters so they stay usable in Discord.",
                ephemeral=True,
            )
            return

        duplicate = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
            (interaction.guild_id, rp_type, text),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                "That text is already saved for this RP type.", ephemeral=True
            )
            return

        await database.add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, text=text)
        await interaction.response.send_message(f"Added text to `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="removetext", description="Remove a saved embed text template from an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_text(self, interaction: discord.Interaction, rp_type: str, text: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        text = text.strip()

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
            (interaction.guild_id, rp_type, text),
        )
        if existing is None:
            await interaction.response.send_message(
                "That text isn't saved under this RP type.", ephemeral=True
            )
            return

        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
            (interaction.guild_id, rp_type, text),
        )
        await interaction.response.send_message(f"Removed text from `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="listtext", description="List the saved embed text templates for an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_text(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        texts = await database.fetch_column(
            """
            SELECT DISTINCT texts
            FROM roleplay_entries
            WHERE guild_id = ? AND type = ? AND texts IS NOT NULL
            ORDER BY texts COLLATE NOCASE
            """,
            (interaction.guild_id, rp_type),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(f"Saved embed texts for `{rp_type}`:", texts),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Action text management                                            #
    # ------------------------------------------------------------------ #

    @app_commands.command(name="addactiontext", description="Save a dynamic action text template under an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def add_action_text(self, interaction: discord.Interaction, rp_type: str, action_text: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        action_text = action_text.strip()

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        if not action_text:
            await interaction.response.send_message("Action text entries can't be blank.", ephemeral=True)
            return

        if len(action_text) > MAX_TEXT_LENGTH:
            await interaction.response.send_message(
                f"Keep action text entries under {MAX_TEXT_LENGTH} characters so they stay usable in Discord.",
                ephemeral=True,
            )
            return

        duplicate = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, action_text),
        )
        if duplicate is not None:
            await interaction.response.send_message(
                "That action text is already saved for this RP type.", ephemeral=True
            )
            return

        has_user = "{user}" in action_text or "{user_name}" in action_text
        has_target = "{target}" in action_text or "{target_name}" in action_text

        if not (has_user and has_target):
            missing = []
            if not has_user:
                missing.append("`{user}`")
            if not has_target:
                missing.append("`{target}`")

            warning = (
                f"⚠️ **Warning:** Your action text is missing the following dynamic tags: {', '.join(missing)}.\n\n"
                "**How it works:**\n"
                "- `{user}` / `{target}`: Pings/Mentions the users.\n"
                "- `{user_name}` / `{target_name}`: Uses their display names.\n\n"
                "Do you want to add it anyway?"
            )
            # Kick it over to a confirmation view rather than just rejecting outright —
            # there are legit cases where someone wants a one-sided action text.
            view = ActionTextConfirmView(interaction.user.id, interaction.guild_id, rp_type, action_text)
            await interaction.response.send_message(warning, view=view, ephemeral=True)
        else:
            await database.add_rp_entry(
                interaction.user.id, interaction.guild_id, rp_type, action_text=action_text
            )
            await interaction.response.send_message(f"Added action text to `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="removeactiontext", description="Remove a saved dynamic action text template from an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def remove_action_text(self, interaction: discord.Interaction, rp_type: str, action_text: str) -> None:
        rp_type = normalize_rp_type(rp_type)
        action_text = action_text.strip()

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        existing = await database.fetch_one(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, action_text),
        )
        if existing is None:
            await interaction.response.send_message(
                "That action text isn't saved under this RP type.", ephemeral=True
            )
            return

        await database.execute_query(
            "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts = ?",
            (interaction.guild_id, rp_type, action_text),
        )
        await interaction.response.send_message(f"Removed action text from `{rp_type}`.", ephemeral=True)

    @app_commands.command(name="listactiontext", description="List the saved dynamic action text templates for an RP type.")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @moderator_only()
    @app_commands.autocomplete(rp_type=rp_type_autocomplete)
    async def list_action_text(self, interaction: discord.Interaction, rp_type: str) -> None:
        rp_type = normalize_rp_type(rp_type)

        if not await database.rp_type_exists(interaction.guild_id, rp_type):
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        action_texts = await database.fetch_column(
            """
            SELECT DISTINCT action_texts
            FROM roleplay_entries
            WHERE guild_id = ? AND type = ? AND action_texts IS NOT NULL
            ORDER BY action_texts COLLATE NOCASE
            """,
            (interaction.guild_id, rp_type),
        )
        await send_chunked_response(
            interaction,
            build_list_messages(f"Saved action texts for `{rp_type}`:", action_texts),
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    #  Error handler                                                     #
    # ------------------------------------------------------------------ #

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.MissingPermissions):
            message = "That one is for mods only."
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "That command only works inside a server."
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"That command is cooling down. Try again in {error.retry_after:.1f}s."
        else:
            logging.error(
                "Unhandled app command error",
                exc_info=(type(original), original, original.__traceback__),
            )
            message = "Something went wrong while running that command. The error was logged."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RPCommands(bot))