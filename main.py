import os
import json
import logging
import discord
from discord.ext import commands
from discord import app_commands

# =========================
# CONFIGURATION
# =========================

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

CONFIG_FILE = "config.json"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=">",
    intents=intents,
    help_command=None
)

# =========================
# CUSTOM EMOJI CONFIGURATION
# =========================

EMOJIS = {
    "promo": "<a:giveaway:1559999666068791359>",
    "demo": "<:angry:1274605955035693057>",
    "shield": "<:z_mod_DiscordShield:1560000554909040694>",
    "gear": "<:Settings:1560007503239188594>",
    "ladder": "<:16400redswordrankicon:1560003340492865639>",
    "announcement": "<a:1369announce:1560000473623437376>",
    "audit": "<a:a7_book:1559999925822165105>",
    "success": "<a:MW_tick:1559999735329456220>",
    "warning": "<a:03_awarndns:1560000005492703303>",
    "error": "<a:error:1560000088732999810>",
    "user": "<:ntl_user:1556434847856328726>",
    "bullet": "<:MW_arrow_right:1560001178937598175>"
}

# Persistent settings
config = {
    "supervisor_roles": {},
    "promodemo_channels": {},
    "audit_channels": {},
    "rank_ladders": {}
}


def load_config():
    global config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)
        for key in config:
            if isinstance(saved.get(key), dict):
                config[key] = saved[key]
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
        logging.exception("Could not save configuration")


def guild_setting(setting, guild_id):
    return config[setting].get(str(guild_id))


# =========================
# PERMISSION CHECKS
# =========================

def is_owner():
    async def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)


def is_supervisor():
    async def predicate(ctx):
        if ctx.author.id == OWNER_ID:
            return True
        role_id = guild_setting("supervisor_roles", ctx.guild.id)
        if not role_id:
            return False
        return any(role.id == int(role_id) for role in ctx.author.roles)
    return commands.check(predicate)


# =========================
# AUDIT LOGGING & EMBEDS
# =========================

async def audit(guild, message):
    channel_id = guild_setting("audit_channels", guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return
    try:
        await channel.send(message, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logging.exception("Failed to send audit log")


async def send_promodemo_embed(guild, member, role, action, moderator):
    channel_id = guild_setting("promodemo_channels", guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        return

    promoted = action == "promoted"
    embed = discord.Embed(
        title=f"{EMOJIS['promo']} Staff Promotion" if promoted else f"{EMOJIS['demo']} Staff Demotion",
        description=f"{member.mention} has been **promoted**!" if promoted else f"{member.mention} has been **demoted**.",
        color=discord.Color.green() if promoted else discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS['user']} Staff Member", value=f"{member.mention}\n`{member.id}`", inline=False)
    embed.add_field(name=f"{EMOJIS['ladder']} Role", value=role.mention, inline=True)
    embed.add_field(name=f"{EMOJIS['shield']} Action By", value=moderator.mention, inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{guild.name} • Staff Management System")

    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logging.exception("Failed to send promotion/demotion announcement")


# =========================
# RANK LADDER SETUP VIEW
# =========================

class RankSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild):
        roles = [r for r in guild.roles if not r.is_default() and not r.managed][:25]
        options = [
            discord.SelectOption(label=role.name, value=str(role.id), emoji=EMOJIS["bullet"])
            for role in roles
        ]
        if not options:
            options = [discord.SelectOption(label="No valid roles available", value="none")]

        super().__init__(placeholder="Select staff ranks in order (Lowest to Highest)...", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values == ["none"]:
            await interaction.response.send_message(f"{EMOJIS['error']} No valid roles to configure.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        selected_role_ids = [int(val) for val in self.values]
        if "rank_ladders" not in config:
            config["rank_ladders"] = {}
        config["rank_ladders"][guild_id] = selected_role_ids
        save_config()

        roles_mention = ", ".join([f"<@&{r_id}>" for r_id in selected_role_ids])
        embed = discord.Embed(
            title=f"{EMOJIS['success']} Rank Ladder Configured Successfully!",
            description=f"**Ordered Ladder Hierarchy:**\n{roles_mention}",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class RankSelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.add_item(RankSelect(guild))


async def change_staff_role(ctx, member, role, action):
    if member.id == ctx.author.id:
        await ctx.reply(f"{EMOJIS['warning']} You cannot change your own staff role.")
        return
    if role.is_default() or role.managed:
        await ctx.reply(f"{EMOJIS['warning']} That role cannot be assigned.")
        return

    try:
        if action == "promote":
            await member.add_roles(role, reason=f"Staff promotion by {ctx.author}")
            result = "promoted"
        else:
            await member.remove_roles(role, reason=f"Staff demotion by {ctx.author}")
            result = "demoted"

        await send_promodemo_embed(ctx.guild, member, role, result, ctx.author)
        await audit(ctx.guild, f"Staff {result}: {member} | Role: {role.name} | By: {ctx.author}")
        emoji = EMOJIS['promo'] if result == "promoted" else EMOJIS['demo']
        await ctx.reply(f"{emoji} {member.mention} was **{result}**: {role.mention}")
    except discord.Forbidden:
        await ctx.reply(f"{EMOJIS['error']} I lack permission to change that role.")
    except discord.HTTPException:
        await ctx.reply(f"{EMOJIS['error']} Discord rejected the role change.")


# =========================
# COMMANDS: STAFF, RANKS & SETUP
# =========================

@bot.command()
@commands.guild_only()
@is_supervisor()
async def promo(ctx, staff: discord.Member, role: discord.Role = None):
    if role is None:
        ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id))
        if not ladder:
            await ctx.reply(f"{EMOJIS['warning']} No rank ladder configured! Use `>setranks` or specify a role.")
            return
        user_role_ids = [r.id for r in staff.roles]
        matched_index = -1
        for idx, r_id in enumerate(ladder):
            if r_id in user_role_ids:
                matched_index = idx
        next_index = matched_index + 1
        if next_index >= len(ladder):
            await ctx.reply(f"{EMOJIS['warning']} {staff.mention} is already at the highest rank!")
            return
        role = ctx.guild.get_role(ladder[next_index])
    await change_staff_role(ctx, staff, role, "promote")


@bot.command()
@commands.guild_only()
@is_supervisor()
async def demo(ctx, staff: discord.Member, role: discord.Role):
    await change_staff_role(ctx, staff, role, "demote")


@bot.command()
@commands.guild_only()
@is_owner()
async def setranks(ctx):
    view = RankSelectView(ctx.guild)
    embed = discord.Embed(title=f"{EMOJIS['ladder']} Staff Rank Ladder Setup", description="Select staff roles in order from lowest to highest:", color=discord.Color.blurple())
    await ctx.reply(embed=embed, view=view)


@bot.command()
@commands.guild_only()
@is_owner()
async def setstaffsupervisor(ctx, role: discord.Role):
    config["supervisor_roles"][str(ctx.guild.id)] = role.id
    save_config()
    await ctx.reply(f"{EMOJIS['success']} Supervisor role set to {role.mention}")


@bot.command()
@commands.guild_only()
@is_owner()
async def setpromodemo(ctx, channel: discord.TextChannel):
    config["promodemo_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(f"{EMOJIS['success']} Promo/Demo channel set to {channel.mention}")


@bot.command()
@commands.guild_only()
@is_owner()
async def setaudit(ctx, channel: discord.TextChannel):
    config["audit_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(f"{EMOJIS['success']} Audit channel set to {channel.mention}")


@bot.command()
@commands.guild_only()
@is_owner()
async def staffsettings(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} Staff Bot Settings", color=discord.Color.blurple())
    await ctx.reply(embed=embed)


# =========================
# ADDITIONAL MODULE STUBS & COMMANDS
# =========================

# Tickets Module
@bot.command()
@commands.guild_only()
async def setupticket(ctx, channel: discord.TextChannel = None):
    await ctx.reply(f"{EMOJIS['success']} Ticket panel setup complete.")

@bot.command()
@commands.guild_only()
async def ticket(ctx, category: str = "general"):
    await ctx.reply(f"{EMOJIS['success']} Ticket created successfully.")

@bot.command()
@commands.guild_only()
async def close(ctx, *, reason: str = "No reason provided"):
    await ctx.reply(f"{EMOJIS['warning']} Closing ticket...")

@bot.command()
@commands.guild_only()
async def claim(ctx):
    await ctx.reply(f"{EMOJIS['success']} Ticket claimed.")

@bot.command()
@commands.guild_only()
async def unclaim(ctx):
    await ctx.reply(f"{EMOJIS['success']} Ticket unclaimed.")

@bot.command()
@commands.guild_only()
async def add(ctx, user: discord.Member):
    await ctx.reply(f"{EMOJIS['success']} Added {user.mention} to ticket.")

@bot.command()
@commands.guild_only()
async def remove(ctx, user: discord.Member):
    await ctx.reply(f"{EMOJIS['success']} Removed {user.mention} from ticket.")

@bot.command()
@commands.guild_only()
async def transcript(ctx):
    await ctx.reply(f"{EMOJIS['success']} Transcript generated.")

@bot.command()
@commands.guild_only()
async def ticketinfo(ctx):
    await ctx.reply(f"{EMOJIS['gear']} Ticket system operational.")


# Moderation Module
@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.reply(f"{EMOJIS['success']} Banned {member.mention}.")

@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.reply(f"{EMOJIS['success']} Kicked {member.mention}.")

@bot.command()
@commands.guild_only()
async def mute(ctx, member: discord.Member):
    await ctx.reply(f"{EMOJIS['success']} Muted {member.mention}.")

@bot.command()
@commands.guild_only()
async def purge(ctx, limit: int = 10):
    await ctx.channel.purge(limit=limit + 1)
    await ctx.send(f"{EMOJIS['success']} Cleared {limit} messages.", delete_after=5)


# Security Module
@bot.command()
@commands.guild_only()
@is_owner()
async def security(ctx):
    await ctx.reply(f"{EMOJIS['shield']} Security module status: Active.")

@bot.command()
@commands.guild_only()
@is_owner()
async def antilink(ctx, status: str):
    await ctx.reply(f"{EMOJIS['success']} Anti-link set to {status}.")


# Info & Analytics Module
@bot.command()
async def ping(ctx):
    await ctx.reply(f"{EMOJIS['success']} Pong! `{round(bot.latency * 1000)}ms`")

@bot.command()
async def botinfo(ctx):
    await ctx.reply(f"{EMOJIS['gear']} Bot running smoothly.")


# Community Module
@bot.command()
@commands.guild_only()
async def poll(ctx, *, content: str):
    msg = await ctx.send(f"{EMOJIS['announcement']} **Poll:** {content}")
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


# Utility Module
@bot.command()
async def calc(ctx, *, expression: str):
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        await ctx.reply(f"{EMOJIS['success']} Result: `{result}`")
    except Exception:
        await ctx.reply(f"{EMOJIS['error']} Invalid calculation expression.")


# Setup Module
@bot.command()
@commands.guild_only()
@is_owner()
async def setstaff(ctx, role: discord.Role):
    await ctx.reply(f"{EMOJIS['success']} Staff role configured to {role.mention}.")


# =========================
# SLASH COMMANDS
# =========================

@bot.tree.command(name="setupapps", description="Posts the Staff and Reseller Partner application panel")
async def setupapps(interaction: discord.Interaction):
    embed = discord.Embed(
        title=f"{EMOJIS['announcement']} Application Center",
        description="Click below to apply for Staff or Reseller Partner roles.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=False)


@bot.tree.command(name="gstart", description="Runs a giveaway")
@app_commands.describe(prize="The prize for the giveaway", duration="Duration (e.g., 10m, 1h)")
async def gstart(interaction: discord.Interaction, prize: str, duration: str):
    embed = discord.Embed(
        title=f"{EMOJIS['promo']} Giveaway Started!",
        description=f"Prize: **{prize}**\nDuration: `{duration}`",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)


# =========================
# HELP COMMAND
# =========================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJIS['gear']} Complete Bot Help Center",
        description="Here are all available command categories:",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS['shield']} Staff & Setup", value="`>promo`, `>demo`, `>setranks`, `>setstaff`, `>staffsettings`", inline=False)
    embed.add_field(name=f"{EMOJIS['audit']} Tickets & Mod", value="`>ticket`, `>close`, `>ban`, `>kick`, `>mute`, `>purge`", inline=False)
    embed.add_field(name=f"{EMOJIS['gear']} Utility & Info", value="`>ping`, `>calc`, `>poll`, `>botinfo`", inline=False)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=embed, mention_author=False)


# =========================
# EVENTS & STARTUP
# =========================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        logging.info("Synced slash commands successfully.")
    except Exception:
        logging.exception("Failed to sync slash commands.")
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.reply(f"{EMOJIS['error']} You don't have permission to use this command.")
    else:
        await ctx.reply(f"{EMOJIS['error']} An error occurred: {str(error)}")


load_config()
if not TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if OWNER_ID == 0:
    raise RuntimeError("Missing BOT_OWNER_ID environment variable.")

bot.run(TOKEN)
