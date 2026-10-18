from __future__ import annotations

import re
import discord
from discord import app_commands
from discord.ext import commands, tasks

import database

class Behavior(commands.Cog):
    """Behavioral tracking, inactivity system, and emoji leaderboards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_sweep.start()

    def cog_unload(self) -> None:
        self.inactivity_sweep.cancel()

    # default_permissions is a UI hint, not a security boundary
    @app_commands.command(name="enableunverification", description="Turns on the automatic unverification sweep.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def enableunverification(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id

        row = await database.fetch_one(
            "SELECT verified_role_id FROM guild_configs WHERE guild_id = ?",
            (guild_id,)
        )
        if not row or not row[0]:
            await interaction.response.send_message("Please configure a verified role first using `/crouton setup`.", ephemeral=True)
            return

        await database.execute_query(
            """
            INSERT INTO guild_configs (guild_id, inactivity_system_enabled) VALUES (?, 1)
            ON CONFLICT(guild_id) DO UPDATE SET inactivity_system_enabled = 1
            """,
            (guild_id,)
        )
        await interaction.response.send_message("Automatic unverification system enabled.", ephemeral=True)

    # default_permissions is a UI hint, not a security boundary
    @app_commands.command(name="disableunverification", description="Turns off the automatic unverification sweep.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def disableunverification(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild_id

        await database.execute_query(
            """
            INSERT INTO guild_configs (guild_id, inactivity_system_enabled) VALUES (?, 0)
            ON CONFLICT(guild_id) DO UPDATE SET inactivity_system_enabled = 0
            """,
            (guild_id,)
        )
        await interaction.response.send_message("Automatic unverification system disabled.", ephemeral=True)

    # default_permissions is a UI hint, not a security boundary
    @app_commands.command(name="manualresetinactivity", description="Resets a member's inactivity timer.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def manualresetinactivity(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild_id = interaction.guild_id

        now = int(discord.utils.utcnow().timestamp())
        await database.execute_query(
            """
            INSERT INTO member_behavior (guild_id, user_id, joined_at, inactivity_reset_at, last_active_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                inactivity_reset_at = excluded.inactivity_reset_at,
                last_active_at = excluded.last_active_at,
                inactivity_status = NULL
            """,
            (guild_id, member.id, now, now, now)
        )
        await interaction.response.send_message(f"Inactivity timer reset for {member.mention}.", ephemeral=True)

    @app_commands.command(name="emojirank", description="Custom emoji message usage leaderboard.")
    @app_commands.choices(sort_direction=[
        app_commands.Choice(name="Top (Most used)", value="top"),
        app_commands.Choice(name="Bottom (Least used)", value="bottom"),
    ])
    async def emojirank(self, interaction: discord.Interaction, sort_direction: str = "top") -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        guild_id = interaction.guild_id

        order = "DESC" if sort_direction == "top" else "ASC"
        rows = await database.fetch_one(
            f"SELECT emoji_id, message_uses FROM guild_emojis WHERE guild_id = ? ORDER BY message_uses {order} LIMIT 10",
            (guild_id,)
        )
        # Fetch multiple rows properly
        async with self.bot.db_pool.acquire() as conn:
            cursor = await conn.execute(
                f"SELECT emoji_id, message_uses FROM guild_emojis WHERE guild_id = ? ORDER BY message_uses {order} LIMIT 10",
                (guild_id,)
            )
            data = await cursor.fetchall()

        if not data:
            await interaction.response.send_message("No custom emoji usage tracked yet.", ephemeral=True)
            return

        lines = []
        for rank, (emoji_id, uses) in enumerate(data, 1):
            emoji = interaction.guild.get_emoji(emoji_id)
            emoji_str = str(emoji) if emoji else f"<:unknown:{emoji_id}>"
            lines.append(f"`#{rank}` {emoji_str} — **{uses}** uses")

        embed = discord.Embed(
            title=f"Custom Emoji Message Usage ({sort_direction.capitalize()})",
            color=0x3498db,
            description="\n".join(lines)
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reactionrank", description="Custom emoji reaction usage leaderboard.")
    @app_commands.choices(sort_direction=[
        app_commands.Choice(name="Top (Most used)", value="top"),
        app_commands.Choice(name="Bottom (Least used)", value="bottom"),
    ])
    async def reactionrank(self, interaction: discord.Interaction, sort_direction: str = "top") -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return
        guild_id = interaction.guild_id

        order = "DESC" if sort_direction == "top" else "ASC"
        async with self.bot.db_pool.acquire() as conn:
            cursor = await conn.execute(
                f"SELECT emoji_id, reaction_uses FROM guild_emojis WHERE guild_id = ? ORDER BY reaction_uses {order} LIMIT 10",
                (guild_id,)
            )
            data = await cursor.fetchall()

        if not data:
            await interaction.response.send_message("No custom emoji reaction usage tracked yet.", ephemeral=True)
            return

        lines = []
        for rank, (emoji_id, uses) in enumerate(data, 1):
            emoji = interaction.guild.get_emoji(emoji_id)
            emoji_str = str(emoji) if emoji else f"<:unknown:{emoji_id}>"
            lines.append(f"`#{rank}` {emoji_str} — **{uses}** reactions")

        embed = discord.Embed(
            title=f"Custom Emoji Reaction Usage ({sort_direction.capitalize()})",
            color=0x3498db,
            description="\n".join(lines)
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        guild_id = message.guild.id
        user_id = message.author.id
        now = int(discord.utils.utcnow().timestamp())

        # Update member behavior stats
        await database.execute_query(
            """
            INSERT INTO member_behavior (guild_id, user_id, joined_at, total_messages, last_active_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                total_messages = total_messages + 1,
                last_active_at = excluded.last_active_at
            """,
            (guild_id, user_id, now, now)
        )

        # Track custom emojis in message content
        custom_emojis = re.findall(r"<a?:[a-zA-Z0-9\_]+:([0-9]+)>", message.content)
        for emoji_id_str in custom_emojis:
            emoji_id = int(emoji_id_str)
            await database.execute_query(
                """
                INSERT INTO guild_emojis (guild_id, emoji_id, message_uses) VALUES (?, ?, 1)
                ON CONFLICT(guild_id, emoji_id) DO UPDATE SET message_uses = message_uses + 1
                """,
                (guild_id, emoji_id)
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not payload.emoji.id:
            return

        guild_id = payload.guild_id
        emoji_id = payload.emoji.id
        await database.execute_query(
            """
            INSERT INTO guild_emojis (guild_id, emoji_id, reaction_uses) VALUES (?, ?, 1)
            ON CONFLICT(guild_id, emoji_id) DO UPDATE SET reaction_uses = reaction_uses + 1
            """,
            (guild_id, emoji_id)
        )

    @tasks.loop(hours=6)
    async def inactivity_sweep(self) -> None:
        # Periodic check for inactive verified members when enabled
        pass

    @inactivity_sweep.before_loop
    async def before_inactivity_sweep(self) -> None:
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Behavior(bot))
