import os
import re
import json
import random
import logging
import asyncio
import aiohttp
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
CONFIG_FILE = "config.json"
PREFIX = ">"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

DEFAULT_CONFIG = {
    "welcome_channels": {},
    "warnings": {},
    "supervisor_roles": {},
    "staff_roles": {},
    "rank_ladders": {},
    "staff_log_channels": {},
    "audit_channels": {},
}
config = {key: value.copy() for key, value in DEFAULT_CONFIG.items()}

# Custom icon images from Emoji.gg's role icons collection.
# The collection contains user-uploaded art.
CUSTOM_EMOJIS = {
    "squarecheck": "https://cdn3.emoji.gg/emojis/3004-square-checkmark.png",
    "xmark": "https://cdn3.emoji.gg/emojis/8118-xmark.png",
    "roleowner": "https://cdn3.emoji.gg/emojis/221415-holographicownerroleicon.png",
    "roleadmin": "https://cdn3.emoji.gg/emojis/958314-adminroleicon.png",
    "rolebot": "https://cdn3.emoji.gg/emojis/990565-botroleicon.png",
    "redadmin": "https://cdn3.emoji.gg/emojis/14489-redheadadminroleicon.png",
    "greenadmin": "https://cdn3.emoji.gg/emojis/357319-greenheadadminroleicon.png",
    "rolestaff": "https://cdn3.emoji.gg/emojis/845855-staffroleicon.png",
    "redmod": "https://cdn3.emoji.gg/emojis/694231-redmodroleicon.png",
    "adminicon2": "https://cdn3.emoji.gg/emojis/361076-adminroleicon.png",
    "adminicon3": "https://cdn3.emoji.gg/emojis/114992-adminroleicon.png",
}

# Maps convenient names used by embeds to uploaded server emoji names.
ICON_NAMES = {
    "check": "squarecheck",
    "cross": "xmark",
    "owner": "roleowner",
    "admin": "redadmin",
    "bot": "rolebot",
    "staff": "rolestaff",
    "mod": "redmod",
    "info": "roleadmin",
    "notice": "adminicon2",
    "shield": "greenadmin",
}


def load_config():
    global config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)
        for key, default in DEFAULT_CONFIG.items():
            if isinstance(saved.get(key), dict):
                config[key] = saved[key]
    except FileNotFoundError:
        save_config()
    except (OSError, json.JSONDecodeError):
        logging.exception("Could not load config.json")


def save_config():
    temp_file = CONFIG_FILE + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
        os.replace(temp_file, CONFIG_FILE)
    except OSError:
        logging.exception("Could not save config.json")


def get_emoji(guild, key, fallback="»"):
    emoji_name = ICON_NAMES.get(key, key)
    if guild:
        found = discord.utils.get(guild.emojis, name=emoji_name)
        if found:
            return str(found)
    return fallback


def get_custom_emoji(guild, key):
    emoji_name = ICON_NAMES.get(key, key)
    return discord.utils.get(guild.emojis, name=emoji_name) if guild else None


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
    if not guild.me or not guild.me.guild_permissions.manage_emojis_and_stickers:
        logging.info("Missing emoji permission in %s; skipping emoji upload.", guild.name)
        return

    existing = {emoji.name for emoji in guild.emojis}
    async with aiohttp.ClientSession() as session:
        for name, url in CUSTOM_EMOJIS.items():
            if name in existing:
                continue
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        logging.warning("Could not download %s: HTTP %s", name, response.status)
                        continue
                    image = await response.read()

                await guild.create_custom_emoji(
                    name=name,
                    image=image,
                    reason="Install custom role icons from Emoji.gg",
                )
                await asyncio.sleep(1)
            except discord.HTTPException as exc:
                logging.warning("Could not upload %s in %s: %s", name, guild.name, exc)
                if getattr(exc, "status", None) == 400:
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                logging.warning("Could not download %s", name)


def guild_config(section, guild_id, default=None):
    return config.setdefault(section, {}).get(str(guild_id), default)


def can_manage_target(ctx, member, role):
    if member == ctx.guild.owner or member == ctx.author:
        return False
    if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
        return False
    if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
        return False
    return True


async def log_staff_action(guild, message):
    channel_id = guild_config("staff_log_channels", guild.id)
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        await channel.send(
            embed=make_embed(guild, "Staff action", message),
            allowed_mentions=discord.AllowedMentions.none(),
        )


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
    channel_id = guild_config("welcome_channels", member.guild.id)
    channel = member.guild.get_channel(int(channel_id)) if channel_id else None
    if not channel:
        return

    embed = make_embed(
        member.guild,
        f"{get_emoji(member.guild, 'staff')} Welcome!",
        f"Welcome to **{member.guild.name}**, {member.mention}.",
        discord.Color.green(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Member number", value=str(member.guild.member_count))
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True))


# -------------------------
# HELP, SERVER AND USER INFO
# -------------------------

@bot.command(name="help")
async def help_command(ctx):
    embed = make_embed(
        ctx.guild,
        f"{get_emoji(ctx.guild, 'info')} All-in-One Commands",
        f"Prefix: `{PREFIX}`",
    )
    embed.add_field(
        name="Moderation",
        value="`kick`, `ban`, `unban`, `timeout`, `untimeout`, `purge`, `warn`, `warnings`, `clearwarnings`",
        inline=False,
    )
    embed.add_field(
        name="Server tools",
        value="`setwelcome`, `slowmode`, `lock`, `unlock`, `announce`, `serverinfo`, `roleinfo`",
        inline=False,
    )
    embed.add_field(
        name="Member and fun",
        value="`userinfo`, `avatar`, `ping`, `poll`, `coinflip`, `roll`, `choose`, `8ball`",
        inline=False,
    )
    embed.add_field(
        name="Staff tools",
        value="`promo`, `demo`, `super`, `staff`, `role`, `steal`, `setranks`, `setstaffroles`, `setstaffsupervisor`, `setpromodemo`, `setaudit`, `staffsettings`",
        inline=False,
    )
    await ctx.reply(embed=embed, mention_author=False)


@bot.command()
async def ping(ctx):
    ms = round(bot.latency * 1000)
    await ctx.reply(embed=make_embed(
        ctx.guild, f"{get_emoji(ctx.guild, 'check')} Pong!",
        f"Latency: **{ms} ms**", discord.Color.green(),
    ))


@bot.command()
@commands.guild_only()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = make_embed(guild, f"{get_emoji(guild, 'info')} {guild.name}", "Server information")
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
    embed.add_field(name="ID", value=str(member.id), inline=True)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="D"), inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, style="D") if member.joined_at else "Unknown",
        inline=True,
    )
    embed.add_field(name="Roles", value=", ".join(r.mention for r in member.roles[1:])[:1000] or "None", inline=False)
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
    permissions = ", ".join(p.replace("_", " ").title() for p, enabled in role.permissions if enabled)
    embed.add_field(name="Permissions", value=permissions[:1000] or "None", inline=False)
    await ctx.reply(embed=embed)


# -------------------------
# MODERATION
# -------------------------

@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot kick", "Member role is equal to or above yours.", discord.Color.red()))
        return
    await member.kick(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Member kicked", f"{member}\n**Reason:** {reason}", discord.Color.orange()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot ban", "Member role is equal to or above yours.", discord.Color.red()))
        return
    await member.ban(reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Member banned", f"{member}\n**Reason:** {reason}", discord.Color.red()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="No reason provided"):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "User unbanned", f"{user}\n**Reason:** {reason}", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
    from datetime import timedelta
    if minutes < 1 or minutes > 40320:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid duration", "Choose 1 to 40320 minutes.", discord.Color.red()))
        return
    if member == ctx.guild.owner or member.top_role >= ctx.author.top_role:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot timeout", "Member role is equal to or above yours.", discord.Color.red()))
        return
    await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Member timed out", f"{member.mention} for {minutes} minutes.\n{reason}", discord.Color.orange()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member, *, reason="Timeout removed"):
    await member.timeout(None, reason=f"{reason} | By {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Timeout removed", f"{member.mention}\n{reason}", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge(ctx, amount: int = 10):
    if not 1 <= amount <= 100:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid amount", "Choose 1 to 100 messages.", discord.Color.red()))
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(
        embed=make_embed(ctx.guild, "Messages deleted", f"Deleted {max(0, len(deleted) - 1)} messages.", discord.Color.green()),
        delete_after=5,
    )


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    key = f"{ctx.guild.id}:{member.id}"
    entries = config.setdefault("warnings", {}).setdefault(key, [])
    entries.append({"reason": reason[:500], "by": ctx.author.id, "at": discord.utils.utcnow().isoformat()})
    save_config()
    embed = make_embed(ctx.guild, "Warning added", f"{member.mention}\n**Reason:** {reason}", discord.Color.orange())
    embed.add_field(name="Warning count", value=str(len(entries)))
    await ctx.reply(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="warnings")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warnings_command(ctx, member: discord.Member):
    entries = config.get("warnings", {}).get(f"{ctx.guild.id}:{member.id}", [])
    embed = make_embed(ctx.guild, f"Warnings: {member}", color=discord.Color.orange())
    if entries:
        for i, item in enumerate(entries[-10:], start=max(1, len(entries) - 9)):
            embed.add_field(name=f"Warning {i} • {item.get('at', '')[:10]}", value=item.get("reason", "No reason")[:900], inline=False)
    else:
        embed.description = "No warnings recorded."
    await ctx.reply(embed=embed)


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def clearwarnings(ctx, member: discord.Member):
    config.setdefault("warnings", {}).pop(f"{ctx.guild.id}:{member.id}", None)
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Warnings cleared", member.mention, discord.Color.green()))


# -------------------------
# CHANNEL AND WELCOME TOOLS
# -------------------------

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if not 0 <= seconds <= 21600:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid slowmode", "Choose 0 to 21600 seconds.", discord.Color.red()))
        return
    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Changed by {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Slowmode updated", f"{seconds} seconds.", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def lock(ctx, *, reason="Channel locked"):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
    await ctx.reply(embed=make_embed(ctx.guild, "Channel locked", reason, discord.Color.red()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unlock(ctx, *, reason="Channel unlocked"):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
    await ctx.reply(embed=make_embed(ctx.guild, "Channel unlocked", reason, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
@commands.bot_has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname: str = None):
    await member.edit(nick=nickname, reason=f"Changed by {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Nickname updated", f"{member.mention}: {nickname or member.name}", discord.Color.green()))


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
    await ctx.reply(embed=make_embed(ctx.guild, "Welcome channel set", channel.mention, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def announce(ctx, channel: discord.TextChannel, *, message: str):
    embed = make_embed(ctx.guild, f"{get_emoji(ctx.guild, 'notice')} Announcement", message[:4000], discord.Color.gold())
    embed.set_footer(text=f"Posted by {ctx.author.display_name}")
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await ctx.reply(embed=make_embed(ctx.guild, "Announcement posted", channel.mention, discord.Color.green()))


@bot.command()
@commands.guild_only()
async def poll(ctx, *, question: str):
    embed = make_embed(ctx.guild, "Poll", question[:4000])
    message = await ctx.send(embed=embed)
    for key in ("check", "cross"):
        emoji = get_custom_emoji(ctx.guild, key)
        if emoji:
            await message.add_reaction(emoji)


# -------------------------
# FUN COMMANDS
# -------------------------

@bot.command()
async def coinflip(ctx):
    await ctx.reply(embed=make_embed(ctx.guild, "Coin flip", random.choice(("Heads", "Tails")), discord.Color.gold()))


@bot.command()
async def roll(ctx, sides: int = 6):
    if not 2 <= sides <= 1000000:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid dice", "Choose 2 to 1,000,000 sides.", discord.Color.red()))
        return
    await ctx.reply(embed=make_embed(ctx.guild, "Dice roll", f"You rolled **{random.randint(1, sides)}**.", discord.Color.gold()))


@bot.command()
async def choose(ctx, *choices):
    if len(choices) < 2:
        await ctx.reply(embed=make_embed(ctx.guild, "Need more choices", "Example: `>choose pizza sushi tacos`.", discord.Color.orange()))
        return
    await ctx.reply(embed=make_embed(ctx.guild, "Choice", random.choice(choices), discord.Color.gold()))


@bot.command(name="8ball")
async def eight_ball(ctx, *, question: str):
    answer = random.choice([
        "Definitely.", "Looks likely.", "Ask again later.",
        "I can't tell right now.", "Probably not.", "No.",
    ])
    await ctx.reply(embed=make_embed(ctx.guild, "Magic 8-Ball", f"**{question[:1000]}**\n{answer}"))


# -------------------------
# STAFF COMMANDS
# -------------------------

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def setstaffsupervisor(ctx, role: discord.Role):
    config.setdefault("supervisor_roles", {})[str(ctx.guild.id)] = role.id
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Supervisor role set", role.mention, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def setstaffroles(ctx, *roles: discord.Role):
    if not roles:
        await ctx.reply(embed=make_embed(ctx.guild, "Mention staff roles", "Example: `>setstaffroles @Staff @Moderator`.", discord.Color.orange()))
        return
    config.setdefault("staff_roles", {})[str(ctx.guild.id)] = [role.id for role in roles]
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Staff roles saved", ", ".join(role.mention for role in roles), discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def setranks(ctx, *roles: discord.Role):
    if not roles:
        await ctx.reply(embed=make_embed(ctx.guild, "Mention ranks in order", "Example: `>setranks @Junior @Senior @Lead`.", discord.Color.orange()))
        return
    config.setdefault("rank_ladders", {})[str(ctx.guild.id)] = [role.id for role in roles]
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Rank ladder saved", " → ".join(role.mention for role in roles), discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def promo(ctx, member: discord.Member):
    ladder = [
        ctx.guild.get_role(role_id)
        for role_id in guild_config("rank_ladders", ctx.guild.id, [])
    ]
    ladder = [role for role in ladder if role]
    current = next((role for role in reversed(ladder) if role in member.roles), None)
    next_index = ladder.index(current) + 1 if current else 0

    if next_index >= len(ladder):
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot promote", "No next rank is configured.", discord.Color.orange()))
        return

    new_role = ladder[next_index]
    if not can_manage_target(ctx, member, new_role):
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot promote", "Check member and role hierarchy.", discord.Color.red()))
        return

    if current:
        await member.remove_roles(current, reason=f"Promotion by {ctx.author}")
    await member.add_roles(new_role, reason=f"Promotion by {ctx.author}")
    await log_staff_action(ctx.guild, f"{member.mention} promoted to {new_role.mention} by {ctx.author.mention}.")
    await ctx.reply(embed=make_embed(ctx.guild, "Staff member promoted", f"{member.mention} → {new_role.mention}", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def demo(ctx, member: discord.Member):
    ladder = [
        ctx.guild.get_role(role_id)
        for role_id in guild_config("rank_ladders", ctx.guild.id, [])
    ]
    ladder = [role for role in ladder if role]
    current = next((role for role in reversed(ladder) if role in member.roles), None)

    if not current or ladder.index(current) == 0:
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot demote", "Member is at the lowest rank or has no ladder role.", discord.Color.orange()))
        return

    new_role = ladder[ladder.index(current) - 1]
    if not can_manage_target(ctx, member, current):
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot demote", "Check member and role hierarchy.", discord.Color.red()))
        return

    await member.remove_roles(current, reason=f"Demotion by {ctx.author}")
    await member.add_roles(new_role, reason=f"Demotion by {ctx.author}")
    await log_staff_action(ctx.guild, f"{member.mention} demoted to {new_role.mention} by {ctx.author.mention}.")
    await ctx.reply(embed=make_embed(ctx.guild, "Staff member demoted", f"{member.mention} → {new_role.mention}", discord.Color.orange()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def super(ctx, member: discord.Member):
    role_id = guild_config("supervisor_roles", ctx.guild.id)
    role = ctx.guild.get_role(role_id) if role_id else None
    if not role or not can_manage_target(ctx, member, role):
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot assign supervisor role", "Set the role and check role hierarchy.", discord.Color.red()))
        return
    await member.add_roles(role, reason=f"Supervisor assigned by {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Supervisor assigned", f"{role.mention} → {member.mention}", discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def staff(ctx, member: discord.Member):
    roles = [
        ctx.guild.get_role(role_id)
        for role_id in guild_config("staff_roles", ctx.guild.id, [])
    ]
    roles = [role for role in roles if role and can_manage_target(ctx, member, role)]
    if not roles:
        await ctx.reply(embed=make_embed(ctx.guild, "No assignable staff roles", "Configure roles with `>setstaffroles`.", discord.Color.orange()))
        return
    await member.add_roles(*roles, reason=f"Staff roles assigned by {ctx.author}")
    await ctx.reply(embed=make_embed(ctx.guild, "Staff roles assigned", f"{member.mention}: " + ", ".join(r.mention for r in roles), discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def role(ctx, member: discord.Member, role: discord.Role):
    if not can_manage_target(ctx, member, role):
        await ctx.reply(embed=make_embed(ctx.guild, "Cannot change role", "Check member and role hierarchy.", discord.Color.red()))
        return
    if role in member.roles:
        await member.remove_roles(role, reason=f"Role change by {ctx.author}")
        message = f"Removed {role.mention} from {member.mention}."
    else:
        await member.add_roles(role, reason=f"Role change by {ctx.author}")
        message = f"Added {role.mention} to {member.mention}."
    await ctx.reply(embed=make_embed(ctx.guild, "Role updated", message, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_emojis_and_stickers=True)
@commands.bot_has_permissions(manage_emojis_and_stickers=True)
async def steal(ctx, emoji: str, name: str = None):
    match = re.fullmatch(r"<(a?):([A-Za-z0-9_]+):(\d+)>", emoji)
    if not match:
        await ctx.reply(embed=make_embed(ctx.guild, "Invalid emoji", "Mention a custom emoji to copy.", discord.Color.red()))
        return

    animated, old_name, emoji_id = match.groups()
    extension = "gif" if animated else "png"
    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                await ctx.reply(embed=make_embed(ctx.guild, "Download failed", "Could not fetch that emoji.", discord.Color.red()))
                return
            image = await response.read()

    created = await ctx.guild.create_custom_emoji(name=name or old_name, image=image)
    await ctx.reply(embed=make_embed(ctx.guild, "Emoji added", str(created), discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def setpromodemo(ctx, channel: discord.TextChannel):
    config.setdefault("staff_log_channels", {})[str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Staff log channel set", channel.mention, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def setaudit(ctx, channel: discord.TextChannel):
    config.setdefault("audit_channels", {})[str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(embed=make_embed(ctx.guild, "Audit channel set", channel.mention, discord.Color.green()))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def staffsettings(ctx):
    supervisor_id = guild_config("supervisor_roles", ctx.guild.id)
    staff_ids = guild_config("staff_roles", ctx.guild.id, [])
    rank_ids = guild_config("rank_ladders", ctx.guild.id, [])
    log_id = guild_config("staff_log_channels", ctx.guild.id)

    supervisor = ctx.guild.get_role(supervisor_id) if supervisor_id else None
    staff_roles = [ctx.guild.get_role(i) for i in staff_ids]
    ranks = [ctx.guild.get_role(i) for i in rank_ids]

    embed = make_embed(ctx.guild, "Staff settings")
    embed.add_field(name="Supervisor", value=supervisor.mention if supervisor else "Not set", inline=False)
    embed.add_field(name="Staff roles", value=", ".join(r.mention for r in staff_roles if r) or "Not set", inline=False)
    embed.add_field(name="Rank ladder", value=" → ".join(r.mention for r in ranks if r) or "Not set", inline=False)
    embed.add_field(name="Staff log", value=f"<#{log_id}>" if log_id else "Not set", inline=False)
    await ctx.reply(embed=embed)


# -------------------------
# ERRORS AND STARTUP
# -------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "You don't have permission to use this command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "The bot is missing a required permission."
    elif isinstance(error, commands.MissingRequiredArgument):
        message = f"Missing argument: `{error.param.name}`. Use `>help`."
    elif isinstance(error, commands.BadArgument):
        message = "I couldn't understand one of the command arguments."
    else:
        logging.error("Command error: %s", error)
        message = "Something went wrong while running that command."
    await ctx.reply(embed=make_embed(ctx.guild, "Command error", message, discord.Color.red()))


load_config()

if not TOKEN:
    raise RuntimeError("Set the BOT_TOKEN environment variable before starting the bot.")

bot.run(TOKEN)
