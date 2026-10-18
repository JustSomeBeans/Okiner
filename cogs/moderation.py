from __future__ import annotations

import logging
import time
import discord
from discord import app_commands
from discord.ext import commands

import database
from alt_detector import calculate_alt_score, get_score_summary, format_signed_score, format_account_age, FACTOR_LABELS

bot_started_at = time.time()


def is_honeypot_exempt(member: discord.Member, mod_role_id: int | None) -> bool:
    """Return True if member is exempt from honeypot punishment."""
    if member.guild.owner_id and member.id == member.guild.owner_id:
        return True
    perms = member.guild_permissions
    if (
        perms.administrator
        or perms.manage_guild
        or perms.ban_members
        or perms.kick_members
        or perms.manage_messages
    ):
        return True
    if mod_role_id is not None and any(r.id == mod_role_id for r in member.roles):
        return True
    return False


def channel_matches_honeypot(
    channel: discord.abc.GuildChannel | discord.Thread, honeypot_id: int
) -> bool:
    """Return True if channel matches honeypot ID directly or via parent_id."""
    return channel.id == honeypot_id or getattr(channel, "parent_id", None) == honeypot_id


class Moderation(commands.Cog):
    """Moderation and security commands for Crouton."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._in_flight_honeypot: set[tuple[int, int]] = set()

    crouton_group = app_commands.Group(name="crouton", description="Crouton bot configuration and info")

    @crouton_group.command(name="setup", description="Configure log channel, verified role, and moderator role.")
    @app_commands.checks.has_permissions(administrator=True)
    async def crouton_setup(
        self,
        interaction: discord.Interaction,
        log_channel: discord.TextChannel | None = None,
        verified_role: discord.Role | None = None,
        moderator_role: discord.Role | None = None,
    ) -> None:
        guild_id = interaction.guild_id
        if not guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Fetch existing config
        row = await database.fetch_one(
            "SELECT log_channel_id, verified_role_id, moderator_role_id, honeypot_channel_id, inactivity_system_enabled FROM guild_configs WHERE guild_id = ?",
            (guild_id,)
        )

        log_id = log_channel.id if log_channel else (row[0] if row else None)
        verified_id = verified_role.id if verified_role else (row[1] if row else None)
        mod_id = moderator_role.id if moderator_role else (row[2] if row else None)
        honeypot_id = row[3] if row else None
        inactivity_enabled = row[4] if row else 0

        await database.execute_query(
            """
            INSERT INTO guild_configs (guild_id, log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                log_channel_id = excluded.log_channel_id,
                verified_role_id = excluded.verified_role_id,
                moderator_role_id = excluded.moderator_role_id
            """,
            (guild_id, log_id, honeypot_id, verified_id, mod_id, inactivity_enabled)
        )

        embed = discord.Embed(
            title="Crouton Configuration Updated",
            color=0x2ecc71,
            description="Server security and moderation settings have been saved."
        )
        embed.add_field(name="Log Channel", value=f"<#{log_id}>" if log_id else "Not set", inline=True)
        embed.add_field(name="Verified Role", value=f"<@&{verified_id}>" if verified_id else "Not set", inline=True)
        embed.add_field(name="Moderator Role", value=f"<@&{mod_id}>" if mod_id else "Not set", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @crouton_group.command(name="help", description="In-Discord command reference and feature guide.")
    async def crouton_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Crouton Bot Help & Commands",
            color=0x3498db,
            description="Crouton is a multi-guild moderation and security assistant."
        )
        embed.add_field(
            name="Configuration",
            value="/crouton setup - Configure roles and log channel\n/sethoneypot - Set honeypot channel\n/addscanchannel /removescanchannel - Manage scan channels",
            inline=False
        )
        embed.add_field(
            name="Security & Moderation",
            value="/scan - Run native alt/trust analysis on a member\n/enableunverification /disableunverification - Toggle inactivity audit sweep\n/manualresetinactivity - Reset inactivity timer",
            inline=False
        )
        embed.add_field(
            name="Leaderboards",
            value="/emojirank - Custom emoji usage leaderboard\n/reactionrank - Custom emoji reaction leaderboard",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @crouton_group.command(name="uptime", description="Reports process uptime.")
    async def crouton_uptime(self, interaction: discord.Interaction) -> None:
        uptime_seconds = int(time.time() - bot_started_at)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s" if days > 0 else f"{hours}h {minutes}m {seconds}s"
        await interaction.response.send_message(f"Crouton bot has been online for **{uptime_str}**.", ephemeral=True)

    @app_commands.command(name="sethoneypot", description="Sets or clears the server honeypot channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sethoneypot(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        guild_id = interaction.guild_id
        if not guild_id:
            return

        if channel is not None:
            row = await database.fetch_one(
                "SELECT log_channel_id FROM guild_configs WHERE guild_id = ?",
                (guild_id,)
            )
            log_id = row[0] if row else None
            if log_id and log_id == channel.id:
                await interaction.response.send_message(
                    "The honeypot channel can't be the same as the log channel.",
                    ephemeral=True,
                )
                return

        channel_id = channel.id if channel else None
        await database.execute_query(
            """
            INSERT INTO guild_configs (guild_id, honeypot_channel_id) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET honeypot_channel_id = excluded.honeypot_channel_id
            """,
            (guild_id, channel_id)
        )
        msg = f"Honeypot channel set to {channel.mention}." if channel else "Honeypot channel cleared."
        if channel is not None and interaction.guild and interaction.guild.me:
            if not interaction.guild.me.guild_permissions.ban_members:
                msg += " Warning: I don't have the Ban Members permission, so I can't ban anyone who triggers this until you grant it."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="addscanchannel", description="Allowlist a channel for /scan.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def addscanchannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        guild_id = interaction.guild_id
        if not guild_id:
            return

        await database.execute_query(
            "INSERT OR IGNORE INTO scan_channels (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel.id)
        )
        await interaction.response.send_message(f"Channel {channel.mention} added to scan allowlist.", ephemeral=True)

    @app_commands.command(name="removescanchannel", description="Remove a channel from the /scan allowlist.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def removescanchannel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        guild_id = interaction.guild_id
        if not guild_id:
            return

        await database.execute_query(
            "DELETE FROM scan_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel.id)
        )
        await interaction.response.send_message(f"Channel {channel.mention} removed from scan allowlist.", ephemeral=True)

    @app_commands.command(name="scan", description="Runs native Python alt/trust analysis on a member.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def scan(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guild_id = interaction.guild_id
        if not guild_id or not interaction.guild:
            return

        # Check if channel is allowed
        allowed = await database.fetch_one(
            "SELECT 1 FROM scan_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, interaction.channel_id)
        )
        if not allowed:
            # Also allow log channel or staff
            config_row = await database.fetch_one(
                "SELECT log_channel_id, moderator_role_id FROM guild_configs WHERE guild_id = ?",
                (guild_id,)
            )
            log_id = config_row[0] if config_row else None
            mod_role_id = config_row[1] if config_row else None
            is_mod = mod_role_id and interaction.user and any(r.id == mod_role_id for r in interaction.user.roles)
            if interaction.channel_id != log_id and not is_mod and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("This channel is not allowlisted for `/scan`.", ephemeral=True)
                return

        result = calculate_alt_score(member)
        label, color = get_score_summary(result["total"])

        embed = discord.Embed(
            title="Scan card",
            color=color,
            description=f"{member.mention} scanned by {interaction.user.mention}"
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Trust level", value=label, inline=True)
        embed.add_field(name="Score", value=format_signed_score(result["total"]), inline=True)
        embed.add_field(name="Account age", value=format_account_age(member.created_at), inline=True)

        positive_signals = [f"- {FACTOR_LABELS.get(k, k)}: score {format_signed_score(v)}" for k, v in result["categories"].items() if v > 0]
        negative_signals = [f"- {FACTOR_LABELS.get(k, k)}: score {format_signed_score(v)}" for k, v in result["categories"].items() if v < 0]

        embed.add_field(name=f"Why {member.display_name} scored higher", value="\n".join(positive_signals) if positive_signals else "- No strong trust signals detected", inline=False)
        embed.add_field(name=f"Why {member.display_name} scored lower", value="\n".join(negative_signals) if negative_signals else "- No strong risk signals detected", inline=False)
        embed.set_footer(text=f"{member.name} - {member.id}")
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not isinstance(message.author, discord.Member) or message.author.bot or message.guild is None:
            return

        guild = message.guild
        guild_id = guild.id
        user_id = message.author.id

        row = await database.fetch_one(
            "SELECT honeypot_channel_id, log_channel_id, moderator_role_id FROM guild_configs WHERE guild_id = ?",
            (guild_id,)
        )
        if not row or not row[0]:
            return

        honeypot_id = row[0]
        if not channel_matches_honeypot(message.channel, honeypot_id):
            return

        mod_role_id = row[2]
        if is_honeypot_exempt(message.author, mod_role_id):
            return

        flight_key = (guild_id, user_id)
        if flight_key in self._in_flight_honeypot:
            return

        self._in_flight_honeypot.add(flight_key)
        try:
            ban_performed = False
            skip_reason = None

            me = guild.me
            if not me or not me.guild_permissions.ban_members:
                skip_reason = "Bot lacks ban_members permission"
            elif message.author.id == guild.owner_id:
                skip_reason = "Cannot ban guild owner"
            elif message.author.top_role >= me.top_role:
                skip_reason = "Target member has equal or higher role than bot"
            else:
                try:
                    await guild.ban(
                        message.author,
                        reason="Triggered honeypot channel",
                        delete_message_seconds=3600
                    )
                    ban_performed = True
                except discord.Forbidden as e:
                    skip_reason = f"Missing permissions (Forbidden): {e}"
                    logging.error(f"Failed to ban user {user_id} in guild {guild_id} due to missing permissions (Forbidden): {e}")
                except discord.HTTPException as e:
                    skip_reason = f"HTTP exception: {e}"
                    logging.error(f"Failed to ban user {user_id} in guild {guild_id} due to HTTP exception: {e}")

            if not ban_performed:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound, discord.HTTPException) as e:
                    logging.warning(f"Failed to delete message after honeypot trigger for user {user_id} in guild {guild_id}: {e}")

            log_channel_id = row[1]
            if log_channel_id:
                log_chan = guild.get_channel(log_channel_id)
                if log_chan and isinstance(log_chan, discord.TextChannel):
                    if ban_performed:
                        log_embed = discord.Embed(
                            title="Honeypot Triggered",
                            color=0xe74c3c,
                            description=f"{message.author.mention} ({user_id}) posted in honeypot channel {message.channel.mention} and was banned."
                        )
                    else:
                        desc = f"{message.author.mention} ({user_id}) posted in honeypot channel {message.channel.mention}, but **automated banning failed**."
                        if skip_reason:
                            desc += f" Reason: {skip_reason}"
                        log_embed = discord.Embed(
                            title="Honeypot Triggered (Ban Failed)",
                            color=0xf1c40f,
                            description=desc
                        )
                    try:
                        await log_chan.send(embed=log_embed)
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logging.error(f"Failed to send honeypot log embed in guild {guild_id}: {e}")
        finally:
            self._in_flight_honeypot.discard(flight_key)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
