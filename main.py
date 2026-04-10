from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from urllib.parse import urlparse, urlencode

import asqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

DB_PATH = "rp.db"
SCHEMA_PATH = Path(__file__).with_name("rp_schema.sql")
MAX_MESSAGE_LENGTH = 1900
MAX_TYPE_LENGTH = 64
MAX_TEXT_LENGTH = 1500
MAX_URL_LENGTH = 1000
MAX_EMBED_TITLE_LENGTH = 256
MAX_EMBED_DESCRIPTION_LENGTH = 4096


def normalize_rp_type(raw_value: str) -> str:
    """Keep RP type names consistent so autocomplete and lookups stay predictable."""
    return raw_value.strip().lower()


def normalize_image_url(url: str) -> str:
    """
    Clean up pasted image URLs before we validate or store them.
    """
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


def moderator_only() -> app_commands.Check:
    """Restrict management commands to moderators."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()

        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions and permissions.manage_messages:
            return True

        raise app_commands.MissingPermissions(["manage_messages"])

    return app_commands.check(predicate)


async def async_execute_query(query: str, params: tuple = ()) -> None:
    """Run a write query and commit it right away."""
    async with bot.db_pool.acquire() as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(query, params)
        await conn.commit()


async def fetch_one(query: str, params: tuple = ()) -> tuple | None:
    """Fetch a single database row."""
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(query, params)
        return await result.fetchone()


async def fetch_column(query: str, params: tuple = ()) -> list[str]:
    """Fetch the first column from all returned rows as a plain string list."""
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(query, params)
        rows = await result.fetchall()

    return [str(row[0]) for row in rows]


async def rp_type_exists(guild_id: int, rp_type: str) -> bool:
    """Small helper so command code stays readable."""
    row = await fetch_one(
        "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
        (guild_id, rp_type),
    )
    return row is not None


async def send_chunked_response(
    interaction: discord.Interaction,
    messages: list[str],
    *,
    ephemeral: bool = True,
) -> None:
    """Send one or more response chunks without tripping interaction rules."""
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


async def add_rp_type(guild_id: int, rp_type: str) -> None:
    """Create a new RP type for the current server."""
    await async_execute_query(
        "INSERT INTO rp_types (guild_id, type) VALUES (?, ?)",
        (guild_id, rp_type),
    )


async def add_rp_entry(
    user_id: int,
    guild_id: int,
    rp_type: str,
    *,
    text: str | None = None,
    action_text: str | None = None,
    url: str | None = None,
) -> None:
    """Store an entry tied to a server RP type."""
    await async_execute_query(
        "INSERT INTO roleplay_entries (user_id, guild_id, type, url, texts, action_texts) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, guild_id, rp_type, url, text, action_text),
    )

class ActionTextConfirmView(discord.ui.View):
    """View to handle the Yes/No confirmation for adding action text with missing tags."""
    def __init__(self, user_id: int, guild_id: int, rp_type: str, action_text: str):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_type = rp_type
        self.action_text = action_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the person who used the command can confirm.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, Add It", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await add_rp_entry(self.user_id, self.guild_id, self.rp_type, action_text=self.action_text)
        await interaction.response.edit_message(content=f"✅ Added action text to `{self.rp_type}` despite missing tags.", view=None)

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Action text addition cancelled.", view=None)


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

requested_permissions = discord.Permissions(
    add_reactions=True,
    attach_files=True,
    change_nickname=True,
    embed_links=True,
    send_messages=True,
    send_messages_in_threads=True,
    use_external_emojis=True,
    use_external_stickers=True,
    use_application_commands=True,
    view_audit_log=True,
    view_channel=True,
)


class OkinerBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            intents=intents,
            command_prefix="oki!",
            application_id=int(APPLICATION_ID) if APPLICATION_ID else None,
            help_command=None,
        )
        self.db_pool: asqlite.Pool | None = None

    async def setup_hook(self) -> None:
        self.db_pool = await asqlite.create_pool(DB_PATH)

        async with self.db_pool.acquire() as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            await conn.commit()

    async def close(self) -> None:
        if self.db_pool is not None:
            await self.db_pool.close()
        await super().close()

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

        if APPLICATION_ID:
            logging.info("Bot invite URL: %s", build_invite_url(APPLICATION_ID))


def build_invite_url(application_id: str) -> str:
    query = urlencode(
        {
            "client_id": application_id,
            "scope": "bot applications.commands",
            "permissions": requested_permissions.value,
        }
    )
    return f"[https://discord.com/oauth2/authorize](https://discord.com/oauth2/authorize)?{query}"


async def rp_type_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if interaction.guild_id is None:
        return []

    pattern = f"%{normalize_rp_type(current)}%"
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            """
            SELECT type
            FROM rp_types
            WHERE guild_id = ? AND LOWER(type) LIKE ?
            ORDER BY type COLLATE NOCASE
            LIMIT 25
            """,
            (interaction.guild_id, pattern),
        )
        rows = await result.fetchall()

    return [app_commands.Choice(name=row[0], value=row[0]) for row in rows]


bot = OkinerBot()


@bot.tree.command(name="rp", description="Perform an interaction between users.")
@app_commands.guild_only()
@app_commands.describe(rp_type="Which interaction to perform", target="Who to target")
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def rp(interaction: discord.Interaction, rp_type: str, target: discord.Member) -> None:
    rp_type = normalize_rp_type(rp_type)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message(
            f"I don't know the RP type `{rp_type}` in this server yet.",
            ephemeral=True,
        )
        return

    async with bot.db_pool.acquire() as conn:
        # 1. Fetch "Regular Text" (Now for the Title)
        text_rows = await conn.execute(
            "SELECT texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts IS NOT NULL",
            (interaction.guild_id, rp_type),
        )
        texts = [row[0] for row in await text_rows.fetchall()]
        
        # 2. Fetch "Action Text" (Now for the Message Content)
        action_text_rows = await conn.execute(
            "SELECT action_texts FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts IS NOT NULL",
            (interaction.guild_id, rp_type),
        )
        action_texts = [row[0] for row in await action_text_rows.fetchall()]

        # 3. Fetch Images
        image_rows = await conn.execute(
            "SELECT url FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url IS NOT NULL",
            (interaction.guild_id, rp_type),
        )
        images = [row[0] for row in await image_rows.fetchall()]

    # --- Logic for Embed Action Text (bold, top of description) ---
    # Always use display names (never mentions) so it renders correctly on both
    # desktop and mobile without showing raw <@userID> strings.
    if action_texts:
        base_action = random.choice(action_texts)
        raw_action = (
            base_action
            .replace("{user}", interaction.user.display_name)
            .replace("{target}", target.display_name)
            .replace("{user_name}", interaction.user.display_name)
            .replace("{target_name}", target.display_name)
        )
    else:
        # Default fallback if no action text exists
        raw_action = f"{interaction.user.display_name} → {target.display_name}"

    action_line = truncate_for_embed(f"**{raw_action}**", MAX_EMBED_DESCRIPTION_LENGTH)

    # --- Logic for Embed RP Text (plain, below action text) ---
    if texts:
        base_text = random.choice(texts)
        raw_text = (
            base_text
            .replace("{user}", interaction.user.display_name)
            .replace("{target}", target.display_name)
            .replace("{user_name}", interaction.user.display_name)
            .replace("{target_name}", target.display_name)
        )
        rp_line = truncate_for_embed(raw_text, MAX_EMBED_DESCRIPTION_LENGTH - len(action_line) - 2)
        description = f"{action_line}\n{rp_line}"
    else:
        description = action_line

    description = truncate_for_embed(description, MAX_EMBED_DESCRIPTION_LENGTH)

    # --- Handle Image ---
    normalized_images = [normalize_image_url(url) for url in images]
    valid_images = [url for url in normalized_images if is_valid_image_url(url)]
    image_url = random.choice(valid_images) if valid_images else None

    embed = discord.Embed(
        description=description,
        color=discord.Color.blurple(),
    )
    if image_url:
        embed.set_image(url=image_url)

    # --- Send ---
    try:
        await interaction.response.send_message(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        logging.warning("RP message send failed; retrying without image.", exc_info=True)
        fallback_embed = discord.Embed(description=description, color=discord.Color.blurple())
        if interaction.response.is_done():
            await interaction.followup.send(embed=fallback_embed)
        else:
            await interaction.response.send_message(embed=fallback_embed)


@bot.tree.command(name="addtype", description="Add a new RP type to this server.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
async def add_type(interaction: discord.Interaction, rp_type: str) -> None:
    rp_type = normalize_rp_type(rp_type)

    if not rp_type:
        await interaction.response.send_message("RP type names can't be blank.", ephemeral=True)
        return

    if len(rp_type) > MAX_TYPE_LENGTH:
        await interaction.response.send_message("RP type names need to stay under 65 characters.", ephemeral=True)
        return

    if not rp_type.replace("-", "").replace("_", "").isalnum():
        await interaction.response.send_message(
            "Keep RP type names to letters, numbers, hyphens, or underscores.",
            ephemeral=True,
        )
        return

    if await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("That RP type already exists.", ephemeral=True)
        return

    await add_rp_type(interaction.guild_id, rp_type)
    await interaction.response.send_message(f"Added RP type `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removetype", description="Remove an RP type and everything saved under it.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_type(interaction: discord.Interaction, rp_type: str) -> None:
    rp_type = normalize_rp_type(rp_type)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    await async_execute_query(
        "DELETE FROM rp_types WHERE guild_id = ? AND type = ?",
        (interaction.guild_id, rp_type),
    )
    await interaction.response.send_message(
        f"Removed RP type `{rp_type}` and all of its saved entries.",
        ephemeral=True,
    )


@bot.tree.command(name="addimage", description="Save an image URL under an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_image(interaction: discord.Interaction, rp_type: str, url: str) -> None:
    rp_type = normalize_rp_type(rp_type)
    url = normalize_image_url(url)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    parsed = urlparse(url)
    if parsed.netloc in {"imgur.com", "[www.imgur.com](https://www.imgur.com)"}:
        await interaction.response.send_message(
            "Please provide the direct image link (Right-click the image -> Copy image address). It should start with `i.imgur.com`, not `imgur.com`.",
            ephemeral=True,
        )
        return

    if not is_valid_image_url(url):
        await interaction.response.send_message(
            "That doesn't look like a valid `http` or `https` URL.",
            ephemeral=True,
        )
        return

    if len(url) > MAX_URL_LENGTH:
        await interaction.response.send_message("That URL is longer than I want to store safely.", ephemeral=True)
        return

    duplicate = await fetch_one(
        "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
        (interaction.guild_id, rp_type, url),
    )
    if duplicate is not None:
        await interaction.response.send_message("That image is already saved for this RP type.", ephemeral=True)
        return
    
    await add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, url=url)
    await interaction.response.send_message(f"Added image to `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removeimage", description="Remove a saved image URL from an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_image(interaction: discord.Interaction, rp_type: str, url: str) -> None:
    rp_type = normalize_rp_type(rp_type)
    url = normalize_image_url(url)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    existing = await fetch_one(
        "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
        (interaction.guild_id, rp_type, url),
    )
    if existing is None:
        await interaction.response.send_message("That image URL isn't saved under this RP type.", ephemeral=True)
        return

    await async_execute_query(
        "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND url = ?",
        (interaction.guild_id, rp_type, url),
    )
    await interaction.response.send_message(f"Removed image from `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="listimage", description="List the saved image URLs for an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def list_image(interaction: discord.Interaction, rp_type: str) -> None:
    rp_type = normalize_rp_type(rp_type)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    images = await fetch_column(
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


@bot.tree.command(name="addtext", description="Save an embed text template under an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    rp_type = normalize_rp_type(rp_type)
    text = text.strip()

    if not await rp_type_exists(interaction.guild_id, rp_type):
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

    duplicate = await fetch_one(
        "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
        (interaction.guild_id, rp_type, text),
    )
    if duplicate is not None:
        await interaction.response.send_message("That text is already saved for this RP type.", ephemeral=True)
        return

    await add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, text=text)
    await interaction.response.send_message(f"Added text to `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removetext", description="Remove a saved embed text template from an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    rp_type = normalize_rp_type(rp_type)
    text = text.strip()

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    existing = await fetch_one(
        "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
        (interaction.guild_id, rp_type, text),
    )
    if existing is None:
        await interaction.response.send_message("That text isn't saved under this RP type.", ephemeral=True)
        return

    await async_execute_query(
        "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND texts = ?",
        (interaction.guild_id, rp_type, text),
    )
    await interaction.response.send_message(f"Removed text from `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="listtext", description="List the saved embed text templates for an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def list_text(interaction: discord.Interaction, rp_type: str) -> None:
    rp_type = normalize_rp_type(rp_type)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    texts = await fetch_column(
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


# --- ACTIONTEXT COMMANDS --- #

@bot.tree.command(name="addactiontext", description="Save a dynamic action text template under an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_action_text(interaction: discord.Interaction, rp_type: str, action_text: str) -> None:
    rp_type = normalize_rp_type(rp_type)
    action_text = action_text.strip()

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    # Check for placeholders
    has_user = "{user}" in action_text or "{user_name}" in action_text
    has_target = "{target}" in action_text or "{target_name}" in action_text

    if not (has_user and has_target):
        missing = []
        if not has_user: missing.append("`{user}`")
        if not has_target: missing.append("`{target}`")
        
        warning = (
            f"⚠️ **Warning:** Your action text is missing the following dynamic tags: {', '.join(missing)}.\n\n"
            "**How it works:**\n"
            "- `{user}` / `{target}`: Pings/Mentions the users.\n"
            "- `{user_name}` / `{target_name}`: Uses their display names.\n\n"
            "Do you want to add it anyway?"
        )
        view = ActionTextConfirmView(interaction.user.id, interaction.guild_id, rp_type, action_text)
        await interaction.response.send_message(warning, view=view, ephemeral=True)
    else:
        await add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, action_text=action_text)
        await interaction.response.send_message(f"Added action text to `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removeactiontext", description="Remove a saved dynamic action text template from an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_action_text(interaction: discord.Interaction, rp_type: str, action_text: str) -> None:
    """Remove an action text template from a server RP type."""
    rp_type = normalize_rp_type(rp_type)
    action_text = action_text.strip()

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    existing = await fetch_one(
        "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts = ?",
        (interaction.guild_id, rp_type, action_text),
    )
    if existing is None:
        await interaction.response.send_message("That action text isn't saved under this RP type.", ephemeral=True)
        return

    await async_execute_query(
        "DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND action_texts = ?",
        (interaction.guild_id, rp_type, action_text),
    )
    await interaction.response.send_message(f"Removed action text from `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="listactiontext", description="List the saved dynamic action text templates for an RP type.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def list_action_text(interaction: discord.Interaction, rp_type: str) -> None:
    """Show every stored action text template for the chosen RP type."""
    rp_type = normalize_rp_type(rp_type)

    if not await rp_type_exists(interaction.guild_id, rp_type):
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    action_texts = await fetch_column(
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


@bot.tree.command(name="listtype", description="List all RP types configured for this server.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@moderator_only()
async def list_type(interaction: discord.Interaction) -> None:
    rp_types = await fetch_column(
        """
        SELECT type
        FROM rp_types
        WHERE guild_id = ?
        ORDER BY type COLLATE NOCASE
        """,
        (interaction.guild_id,),
    )
    await send_chunked_response(
        interaction,
        build_list_messages("RP types in this server:", rp_types),
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(
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


@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx: commands.Context, scope: str = "local") -> None:
    scope = scope.lower()

    if scope == "global":
        synced = await bot.tree.sync()
        await ctx.reply(f"Global sync finished. {len(synced)} commands updated.")
        return

    if ctx.guild is None:
        await ctx.reply("Local sync only works inside a server.")
        return

    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.reply(f"Local sync finished for this server. {len(synced)} commands updated.")


@sync.error
async def sync_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.NotOwner):
        await ctx.reply("That command is owner-only.")
        return

    logging.error(
        "Unhandled sync command error",
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.reply("Sync failed. Check the logs for details.")


def main() -> None:
    bot.run(TOKEN)


if __name__ == "__main__":
    main()