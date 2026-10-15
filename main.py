import os
import json
import logging
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
CONFIG_FILE = "config.json"
PREFIX = ">"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# Twemoji graphics are CC BY 4.0. Source: https://github.com/twitter/twemoji
TWEMOJI_ASSETS = {
    "bot_check": "2705",
    "bot_cross": "274c",
    "bot_info": "2139",
    "bot_warning": "26a0",
    "bot_star": "2b50",
    "bot_shield": "1f6e1",
    "bot_tools": "1f6e0",
    "bot_notice": "1f4e2",
    "bot_calendar": "1f4c5",
    "bot_clock": "23f0",
    "bot_party": "1f389",
    "bot_gift": "1f381",
    "bot_fire": "1f525",
    "bot_heart": "2764",
    "bot_lock": "1f512",
    "bot_chat": "1f4ac",
    "bot_trophy": "1f3c6",
    "bot_wave": "1f44b",
    "bot_thumbsup": "1f44d",
    "bot_sparkles": "1f31f",
}

DEFAULT_CONFIG = {
    "welcome_channels": {},
    "warnings": {},
}

config = DEFAULT_CONFIG.copy()


def load_config():
    global config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)

        for key, default in DEFAULT_CONFIG.items():
            if isinstance(saved.get(key), dict):
                config[key] = saved[key]
            else:
                config[key] = default.copy()

    except FileNotFoundError:
        save_config()
    except (json.JSONDecodeError, OSError):
        logging.exception("Could not load config.json")


def save_config():
    temporary_file = CONFIG_FILE + ".tmp"

    try:
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)

        os.replace(temporary_file, CONFIG_FILE)
    except OSError:
        logging.exception("Could not save config.json")


def get_emoji(guild, name, fallback):
    """Use the server's uploaded custom emoji, or a Unicode fallback."""
    if guild:
        emoji = discord.utils.get(guild.emojis, name=name)
        if emoji:
            return str(emoji)
    return fallback


def make_embed(guild, title, description=None, color=discord.Color.blurple()):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow(),
    )

    if bot.user:
        embed.set_author(
            name=bot.user.display_name,
            icon_url=bot.user.display_avatar.url,
        )

    if guild:
        embed.set_footer(text=guild.name)

    return embed


async def install_server_emojis(guild):
    """Download and add Twemoji assets when the bot has permission."""
    me = guild.me
    if not me or not me.guild_permissions.manage_emojis_and_stickers:
        logging.info("Skipping emoji setup in %s: missing emoji permissions.", guild.name)
        return

    existing_names = {emoji.name for emoji in guild.emojis}

    async with aiohttp.ClientSession() as session:
        for name, codepoint in TWEMOJI_ASSETS.items():
            if name in existing_names:
                continue

            url = (
                "https://raw.githubusercontent.com/twitter/twemoji/"
                f"master/assets/72x72/{codepoint}.png"
            )

            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        logging.warning("Could not download emoji %s", name)
                        continue
                    image_data = await response.read()

                await guild.create_custom_emoji(
                    name=name,
                    image=image_data,
                    reason="Install Twemoji set (CC BY 4.0)",
                )

                # Avoid sending many create requests at once.
                await asyncio.sleep(1)

            except discord.HTTPException as exc:
                logging.warning("Could not add emoji %s in %s: %s", name, guild.name, exc)
                if getattr(exc, "status", None) == 400:
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                logging.warning("Could not download emoji %s", name)


# -------------------------
# EVENTS
# -------------------------

@bot.event
async def on_ready():
    logging.info("Logged in as %s", bot.user)

    for guild in bot.guilds:
        await install_server_emojis(guild)


@bot.event
async def on_member_join(member):
    channel_id = config.get("welcome_channels", {}).get(str(member.guild.id))
    if not channel_id:
        return

    channel = member.guild.get_channel(int(channel_id))
    if not channel:
        return

    embed = make_embed(
        member.guild,
        f"{get_emoji(member.guild, 'bot_wave', '👋')} Welcome!",
        f"Welcome to **{member.guild.name}**, {member.mention}!",
        discord.Color.green(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member number", value=str(member.guild.member_count), inline=True)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)

    await channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(users=True),
    )


# -------------------------
# GENERAL COMMANDS
# -------------------------

@bot.command(name="help")
async def help_command(ctx):
    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_info', 'ℹ️')} Bot Commands",
        f"Command prefix: `{PREFIX}`\nUse the commands below to manage and explore the server.",
    )

    embed.add_field(
        name="Moderation",
        value="`kick`, `ban`, `unban`, `timeout`, `untimeout`, `purge`, `warn`, `warnings`, `clearwarnings`",
        inline=False,
    )
    embed.add_field(
        name="Channels and server",
        value="`slowmode`, `lock`, `unlock`, `announce`, `setwelcome`, `serverinfo`, `roleinfo`",
        inline=False,
    )
    embed.add_field(
        name="Member tools",
        value="`userinfo`, `avatar`, `poll`, `ping`, `emojiinfo`",
        inline=False,
    )
    embed.add_field(
        name="Fun",
        value="`coinflip`, `roll`, `choose`, `8ball`",
        inline=False,
    )
    embed.set_footer(text="Some commands require server permissions.")
    await ctx.reply(embed=embed, mention_author=False)


@bot.command()
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} Pong!",
        f"Bot latency: **{latency} ms**",
        discord.Color.green(),
    )
    await ctx.reply(embed=embed)


@bot.command()
@commands.guild_only()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = make_embed(
        guild,
        f"{get_emoji(guild, 'bot_info', 'ℹ️')} {guild.name}",
        "Server information",
    )

    embed.add_field(name="Owner", value=str(guild.owner or "Unknown"), inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="D"), inline=True)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    await ctx.reply(embed=embed)


@bot.command()
@commands.guild_only()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = make_embed(ctx.guild, f"User information: {member}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User ID", value=str(member.id), inline=True)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="D"), inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, style="D") if member.joined_at else "Unknown",
        inline=True,
    )
    embed.add_field(
        name="Roles",
        value=", ".join(role.mention for role in member.roles[1:])[:1000] or "No roles",
        inline=False,
    )
    await ctx.reply(embed=embed)


@bot.command()
@commands.guild_only()
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = make_embed(ctx.guild, f"Avatar: {member}")
    embed.set_image(url=member.display_avatar.url)
    await ctx.reply(embed=embed)


@bot.command()
@commands.guild_only()
async def roleinfo(ctx, role: discord.Role):
    embed = make_embed(ctx.guild, f"Role: {role.name}", color=role.color or discord.Color.blurple())
    embed.add_field(name="ID", value=str(role.id), inline=True)
    embed.add_field(name="Members", value=str(len(role.members)), inline=True)
    embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
    embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, style="D"), inline=True)

    permissions = [
        permission.replace("_", " ").title()
        for permission, enabled in role.permissions
        if enabled
    ]
    embed.add_field(name="Permissions", value=", ".join(permissions)[:1000] or "None", inline=False)
    await ctx.reply(embed=embed)


# -------------------------
# MODERATION COMMANDS
# -------------------------

@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot kick member", "Their role is equal to or higher than yours.", discord.Color.red()))
        return

    await member.kick(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} Member kicked",
        f"**Member:** {member}\n**Reason:** {reason}",
        discord.Color.orange(),
    ))


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot ban member", "Their role is equal to or higher than yours.", discord.Color.red()))
        return

    await member.ban(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} Member banned",
        f"**Member:** {member}\n**Reason:** {reason}",
        discord.Color.red(),
    ))


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="No reason provided"):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} User unbanned",
        f"**User:** {user}\n**Reason:** {reason}",
        discord.Color.green(),
    ))


@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
    from datetime import timedelta

    if minutes < 1 or minutes > 40320:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid duration", "Choose between 1 minute and 28 days.", discord.Color.red()))
        return

    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot timeout member", "Their role is equal to or higher than yours.", discord.Color.red()))
        return

    await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_warning', '⚠️')} Member timed out",
        f"**Member:** {member.mention}\n**Duration:** {minutes} minutes\n**Reason:** {reason}",
        discord.Color.orange(),
    ))


@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member, *, reason="Timeout removed by staff"):
    await member.timeout(None, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} Timeout removed",
        f"Removed timeout for {member.mention}.\n**Reason:** {reason}",
        discord.Color.green(),
    ))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid amount", "Choose between 1 and 100 messages.", discord.Color.red()))
        return

    deleted = await ctx.channel.purge(limit=amount + 1)
    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_check', '✅')} Messages deleted",
        f"Deleted **{max(0, len(deleted) - 1)}** messages.",
        discord.Color.green(),
    )
    await ctx.send(embed=embed, delete_after=5)


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    key = f"{ctx.guild.id}:{member.id}"
    entries = config.setdefault("warnings", {}).setdefault(key, [])
    entries.append({
        "reason": reason[:500],
        "moderator": ctx.author.id,
        "date": discord.utils.utcnow().isoformat(),
    })
    save_config()

    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_warning', '⚠️')} Warning added",
        f"{member.mention} received a warning.",
        discord.Color.orange(),
    )
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="Warning count", value=str(len(entries)), inline=True)
    await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="warnings")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warnings_command(ctx, member: discord.Member):
    entries = config.get("warnings", {}).get(f"{ctx.guild.id}:{member.id}", [])
    embed = make_embed(ctx.guild, f"Warnings: {member}", color=discord.Color.orange())

    if not entries:
        embed.description = "This member has no recorded warnings."
    else:
        for index, warning in enumerate(entries[-10:], start=max(1, len(entries) - 9)):
            embed.add_field(
                name=f"Warning {index} • {warning.get('date', '')[:10]}",
                value=f"{warning.get('reason', 'No reason')[:900]} • Moderator <@{warning.get('moderator', 0)}>",
                inline=False,
            )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{len(entries)} warning(s) total")
    await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def clearwarnings(ctx, member: discord.Member):
    config.setdefault("warnings", {}).pop(f"{ctx.guild.id}:{member.id}", None)
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Warnings cleared", f"Cleared warnings for {member.mention}.", discord.Color.green()))


# -------------------------
# CHANNEL AND SERVER TOOLS
# -------------------------

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid slowmode", "Choose between 0 and 21600 seconds.", discord.Color.red()))
        return

    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Changed by {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Slowmode updated", f"Slowmode is now **{seconds} seconds**.", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def lock(ctx, *, reason="Channel locked"):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
    await ctx.reply(embed=make_embed(ctx.guild, "🔒 Channel locked", reason, discord.Color.red()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unlock(ctx, *, reason="Channel unlocked"):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
    await ctx.reply(embed=make_embed(ctx.guild, "🔓 Channel unlocked", reason, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
@commands.bot_has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname: str = None):
    await member.edit(nick=nickname, reason=f"Changed by {ctx.author}")
    label = nickname or member.name
    await ctx.reply(embed=make_embed(ctx.guild, "Nickname updated", f"{member.mention} is now **{label}**.", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def setwelcome(ctx, channel: discord.TextChannel = None):
    if channel is None:
        config.setdefault("welcome_channels", {}).pop(str(ctx.guild.id), None)
        save_config()
        await ctx.reply(embed=make_embed(ctx.guild, "Welcome messages disabled", color=discord.Color.orange()))
        return

    config.setdefault("welcome_channels", {})[str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Welcome channel set", f"New members will be welcomed in {channel.mention}.", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def announce(ctx, channel: discord.TextChannel, *, message: str):
    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'bot_notice', '📢')} Announcement",
        message[:4000],
        discord.Color.gold(),
    )
    embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text=f"Posted by {ctx.author.display_name}")

    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await ctx.reply(embed=make_embed(ctx.guild, "Announcement posted", f"Sent to {channel.mention}.", discord.Color.green()))


@bot.command()
@commands.guild_only()
async def poll(ctx, *, question: str):
    embed = make_embed(ctx.guild, "📊 Poll", question[:4000])
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    message = await ctx.send(embed=embed)
    await message.add_reaction("👍")
    await message.add_reaction("👎")


@bot.command()
@commands.guild_only()
async def emojiinfo(ctx):
    embed = make_embed(
        ctx.guild,
        "Custom emoji setup",
        "The bot tries to add a set of Twemoji images when it starts. It needs the **Manage Emojis and Stickers** permission, and the server needs available emoji slots.",
    )
    embed.add_field(name="Source", value="[Twemoji project](https://github.com/twitter/twemoji)", inline=False)
    embed.add_field(name="License", value="[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)", inline=False)
    await ctx.reply(embed=embed)


# -------------------------
# FUN COMMANDS
# -------------------------

@bot.command()
async def coinflip(ctx):
    result = random.choice(["Heads", "Tails"])
    await ctx.reply(embed=make_embed(ctx.guild, "🪙 Coin flip", f"It landed on **{result}**!", discord.Color.gold()))


@bot.command()
async def roll(ctx, sides: int = 6):
    if sides < 2 or sides > 1000000:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid dice", "Choose from 2 to 1,000,000 sides.", discord.Color.red()))
        return

    result = random.randint(1, sides)
    await ctx.reply(embed=make_embed(ctx.guild, "🎲 Dice roll", f"You rolled **{result}** on a {sides}-sided die.", discord.Color.gold()))


@bot.command()
async def choose(ctx, *choices):
    if len(choices) < 2:
        await ctx.reply(embed=make_embed(ctx.guild, "Give me choices", "Example: `>choose pizza sushi tacos`", discord.Color.orange()))
        return

    result = random.choice(choices)
    await ctx.reply(embed=make_embed(ctx.guild, "🎯 Choice", f"I choose **{result}**!", discord.Color.gold()))


@bot.command(name="8ball")
async def eight_ball(ctx, *, question: str):
    answers = [
        "Yes, definitely.",
        "It looks likely.",
        "Ask again later.",
        "I cannot predict that right now.",
        "Probably not.",
        "No.",
    ]
    await ctx.reply(embed=make_embed(
        ctx.guild,
        "🎱 Magic 8-Ball",
        f"**Question:** {question[:1000]}\n**Answer:** {random.choice(answers)}",
        discord.Color.blurple(),
    ))


# -------------------------
# ERROR HANDLING
# -------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        message = "You don't have permission to use that command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "The bot is missing a permission needed for that command."
    elif isinstance(error, commands.MissingRequiredArgument):
        message = f"Missing an argument: `{error.param.name}`. Use `>help` to see commands."
    elif isinstance(error, commands.BadArgument):
        message = "I couldn't understand one of the command arguments. Check the command and try again."
    else:
        logging.exception("Command error", exc_info=error)
        message = "Something went wrong while running that command."

    await ctx.reply(embed=make_embed(ctx.guild, "Command error", message, discord.Color.red()))


load_config()

if not TOKEN:
    raise RuntimeError("Set the BOT_TOKEN environment variable before starting the bot.")

bot.run(TOKEN)
