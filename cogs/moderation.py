from __future__ import annotations

import time
import discord
from discord import app_commands
from discord.ext import commands

import database
from alt_detector import calculate_alt_score, get_score_summary, format_signed_score, format_account_age, FACTOR_LABELS

bot_started_at = time.time()

class Moderation(commands.Cog):
    """Moderation and security commands for Crouton."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

        channel_id = channel.id if channel else None
        await database.execute_query(
            """
            INSERT INTO guild_configs (guild_id, honeypot_channel_id) VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET honeypot_channel_id = excluded.honeypot_channel_id
            """,
            (guild_id, channel_id)
        )
        msg = f"Honeypot channel set to {channel.mention}." if channel else "Honeypot channel cleared."
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
        if not message.guild or message.author.bot:
            return

        guild_id = message.guild.id
        row = await database.fetch_one(
            "SELECT honeypot_channel_id, log_channel_id, moderator_role_id FROM guild_configs WHERE guild_id = ?",
            (guild_id,)
        )
        if not row or not row[0]:
            return

        honeypot_id = row[0]
        if message.channel.id != honeypot_id:
            return

        # Check if author is staff / admin / mod
        mod_role_id = row[2]
        is_staff = message.author.guild_permissions.administrator or (mod_role_id and any(r.id == mod_role_id for r in message.author.roles))
        if is_staff:
            return

        # Non-staff posted in honeypot -> ban
        try:
            await message.author.ban(reason="Triggered honeypot channel")
            await message.delete()
        except Exception:
            pass

        log_channel_id = row[1]
        if log_channel_id:
            log_chan = message.guild.get_channel(log_channel_id)
            if log_chan and isinstance(log_chan, discord.TextChannel):
                log_embed = discord.Embed(
                    title="Honeypot Triggered",
                    color=0xe74c3c,
                    description=f"{message.author.mention} ({message.author.id}) posted in honeypot channel {message.channel.mention} and was banned."
                )
                await log_chan.send(embed=log_embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
