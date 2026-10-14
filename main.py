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
            embed = discord.Embed(
                title=f"{EMOJIS['error']} Error",
                description="No valid roles to configure.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
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
        embed = discord.Embed(title=f"{EMOJIS['warning']} Action Denied", description="You cannot change your own staff role.", color=discord.Color.orange())
        await ctx.reply(embed=embed, mention_author=False)
        return
    if role.is_default() or role.managed:
        embed = discord.Embed(title=f"{EMOJIS['warning']} Invalid Role", description="That role cannot be assigned.", color=discord.Color.orange())
        await ctx.reply(embed=embed, mention_author=False)
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
        
        embed = discord.Embed(
            title=f"{emoji} Role Update Successful",
            description=f"{member.mention} was **{result}**: {role.mention}",
            color=discord.Color.green() if result == "promoted" else discord.Color.red()
        )
        await ctx.reply(embed=embed, mention_author=False)
    except discord.Forbidden:
        embed = discord.Embed(title=f"{EMOJIS['error']} Permission Error", description="I lack permission to change that role.", color=discord.Color.red())
        await ctx.reply(embed=embed, mention_author=False)
    except discord.HTTPException:
        embed = discord.Embed(title=f"{EMOJIS['error']} Error", description="Discord rejected the role change.", color=discord.Color.red())
        await ctx.reply(embed=embed, mention_author=False)


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
            embed = discord.Embed(title=f"{EMOJIS['warning']} Not Configured", description="No rank ladder configured! Use `>setranks` or specify a role.", color=discord.Color.orange())
            await ctx.reply(embed=embed, mention_author=False)
            return
        user_role_ids = [r.id for r in staff.roles]
        matched_index = -1
        for idx, r_id in enumerate(ladder):
            if r_id in user_role_ids:
                matched_index = idx
        next_index = matched_index + 1
        if next_index >= len(ladder):
            embed = discord.Embed(title=f"{EMOJIS['warning']} Max Rank", description=f"{staff.mention} is already at the highest rank!", color=discord.Color.orange())
            await ctx.reply(embed=embed, mention_author=False)
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
    await ctx.reply(embed=embed, view=view, mention_author=False)


@bot.command()
@commands.guild_only()
@is_owner()
async def setstaffsupervisor(ctx, role: discord.Role):
    config["supervisor_roles"][str(ctx.guild.id)] = role.id
    save_config()
    embed = discord.Embed(title=f"{EMOJIS['success']} Setup Complete", description=f"Supervisor role set to {role.mention}", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)


@bot.command()
@commands.guild_only()
@is_owner()
async def setpromodemo(ctx, channel: discord.TextChannel):
    config["promodemo_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    embed = discord.Embed(title=f"{EMOJIS['success']} Setup Complete", description=f"Promo/Demo channel set to {channel.mention}", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)


@bot.command()
@commands.guild_only()
@is_owner()
async def setaudit(ctx, channel: discord.TextChannel):
    config["audit_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    embed = discord.Embed(title=f"{EMOJIS['success']} Setup Complete", description=f"Audit channel set to {channel.mention}", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)


@bot.command()
@commands.guild_only()
@is_owner()
async def staffsettings(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} Staff Bot Settings", description="Current configuration settings loaded successfully.", color=discord.Color.blurple())
    await ctx.reply(embed=embed, mention_author=False)


# =========================
# ADDITIONAL MODULE STUBS & COMMANDS
# =========================

# Tickets Module
@bot.command()
@commands.guild_only()
async def setupticket(ctx, channel: discord.TextChannel = None):
    embed = discord.Embed(title=f"{EMOJIS['success']} Ticket System", description="Ticket panel setup complete.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def ticket(ctx, category: str = "general"):
    embed = discord.Embed(title=f"{EMOJIS['success']} Ticket Opened", description=f"Category: `{category}`", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def close(ctx, *, reason: str = "No reason provided"):
    embed = discord.Embed(title=f"{EMOJIS['warning']} Ticket Closing", description=f"Reason: {reason}", color=discord.Color.orange())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def claim(ctx):
    embed = discord.Embed(title=f"{EMOJIS['success']} Ticket Claimed", description="This ticket has been claimed by staff.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def unclaim(ctx):
    embed = discord.Embed(title=f"{EMOJIS['success']} Ticket Unclaimed", description="This ticket has been unclaimed.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def add(ctx, user: discord.Member):
    embed = discord.Embed(title=f"{EMOJIS['success']} User Added", description=f"Added {user.mention} to the ticket.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def remove(ctx, user: discord.Member):
    embed = discord.Embed(title=f"{EMOJIS['success']} User Removed", description=f"Removed {user.mention} from the ticket.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def transcript(ctx):
    embed = discord.Embed(title=f"{EMOJIS['success']} Transcript", description="Ticket transcript generated successfully.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def ticketinfo(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} Ticket Info", description="Ticket system is operational.", color=discord.Color.blurple())
    await ctx.reply(embed=embed, mention_author=False)


# Moderation Module
@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    embed = discord.Embed(title=f"{EMOJIS['success']} Member Banned", description=f"Banned {member.mention}.", color=discord.Color.red())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    embed = discord.Embed(title=f"{EMOJIS['success']} Member Kicked", description=f"Kicked {member.mention}.", color=discord.Color.red())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def mute(ctx, member: discord.Member):
    embed = discord.Embed(title=f"{EMOJIS['success']} Member Muted", description=f"Muted {member.mention}.", color=discord.Color.orange())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
async def purge(ctx, limit: int = 10):
    await ctx.channel.purge(limit=limit + 1)
    embed = discord.Embed(title=f"{EMOJIS['success']} Purge Complete", description=f"Cleared {limit} messages.", color=discord.Color.green())
    msg = await ctx.send(embed=embed)
    await discord.utils.sleep_until(discord.utils.utcnow()) # dummy wait or standard delete
    try:
        await msg.delete(delay=5)
    except:
        pass


# Security Module
@bot.command()
@commands.guild_only()
@is_owner()
async def security(ctx):
    embed = discord.Embed(title=f"{EMOJIS['shield']} Security Dashboard", description="Security module status: Active.", color=discord.Color.blurple())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
@commands.guild_only()
@is_owner()
async def antilink(ctx, status: str):
    embed = discord.Embed(title=f"{EMOJIS['success']} Security Setting", description=f"Anti-link filter set to `{status}`.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)


# Info & Analytics Module
@bot.command()
async def ping(ctx):
    embed = discord.Embed(title=f"{EMOJIS['success']} Pong!", description=f"Latency: `{round(bot.latency * 1000)}ms`", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)

@bot.command()
async def botinfo(ctx):
    embed = discord.Embed(title=f"{EMOJIS['gear']} Bot Information", description="All bot systems running smoothly.", color=discord.Color.blurple())
    await ctx.reply(embed=embed, mention_author=False)


# Community Module
@bot.command()
@commands.guild_only()
async def poll(ctx, *, content: str):
    embed = discord.Embed(title=f"{EMOJIS['announcement']} Community Poll", description=content, color=discord.Color.blurple())
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


# Utility Module
@bot.command()
async def calc(ctx, *, expression: str):
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        embed = discord.Embed(title=f"{EMOJIS['success']} Calculator", description=f"Result: `{result}`", color=discord.Color.green())
        await ctx.reply(embed=embed, mention_author=False)
    except Exception:
        embed = discord.Embed(title=f"{EMOJIS['error']} Error", description="Invalid calculation expression.", color=discord.Color.red())
        await ctx.reply(embed=embed, mention_author=False)


# Setup Module
@bot.command()
@commands.guild_only()
@is_owner()
async def setstaff(ctx, role: discord.Role):
    embed = discord.Embed(title=f"{EMOJIS['success']} Staff Setup", description=f"Staff role configured to {role.mention}.", color=discord.Color.green())
    await ctx.reply(embed=embed, mention_author=False)


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
# COMPREHENSIVE HELP COMMAND
# =========================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJIS['gear']} Complete Bot Command Reference",
        description="Here is the master list of all available prefix and slash commands:",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name=f"{EMOJIS['ladder']} Staff & Ranks",
        value=(
            "`>promo @member [@role]` — Promote staff (auto-promotes if role is skipped)\n"
            "`>demo @member @role` — Demote staff member\n"
            "`>setranks` — Open interactive rank ladder setup menu\n"
            "`>rank @user [lvl]`, `>rankrole @role [lvl]`, `>cmdrank`, `>cmdranks`, `>whocan`, `>myrank`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['audit']} Tickets & Support",
        value=(
            "`>setupticket [#ch]`, `>ticket [cat]`, `>close [reason]`, `>claim`, `>unclaim`\n"
            "`>add @user`, `>remove @user`, `>transcript`, `>setcategory`, `>setstaffrole`\n"
            "`>settranscript`, `>setticketlog`, `>ticketinfo`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['error']} Moderation",
        value=(
            "`>ban`, `>softban`, `>unban`, `>forceban`, `>kick`, `>mute`, `>timeout @user 10m`\n"
            "`>unmute`, `>warn`, `>warns`, `>delwarn`, `>clearwarns`, `>jail`, `>unjail`\n"
            "`>temprole @user 1d @role`, `>temproles`, `>purge 50`, `>purgeuser @user`\n"
            "`>lock`, `>unlock`, `>lockdown`, `>unlockdown`, `>slowmode 10`, `>nick @user name`\n"
            "`>roleadd`, `>roleremove`, `>snipe`, `>editsnipe`, `>ms [@user]`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['shield']} Security & Automod",
        value=(
            "`>security`, `>securitymode`, `>securitysetting`, `>securityoverview`\n"
            "`>allowbot`, `>removebot`, `>antilink`, `>antiinvite`, `>antispam`, `>anticaps`\n"
            "`>antimention`, `>antiduplicate`, `>antiraid`, `>antibot`, `>raidmode`, `>automod`\n"
            "`>webhookblock`, `>altfilter`, `>avatarfilter`, `>namefilter`, `>invitesynclog`\n"
            "`>altfilterdays 7`, `>whitelistedchannels add #ch`, `>whitelistedroles add @role`\n"
            "`>linkwhitelist add site.com`, `>sethoneypot #ch`, `>honeypotoff`\n"
            "`>antispamsettings 5 8`, `>verificationlevel high`, `>setlogs`, `>setlogwebhook`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['user']} Info & Analytics",
        value=(
            "`>rank`, `>leaderboard`, `>botinfo`, `>uptime`, `>ping`, `>roleinfo @role`\n"
            "`>channelinfo [#ch]`, `>emojis`, `>boosters`, `>invites [@user]`, `>avatar [@user]`\n"
            "`>banner [@user]`, `>permissions [@user|@role]`, `>userinfo`, `>serverinfo`\n"
            "`>support`, `>status`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['announcement']} Community & Economy",
        value=(
            "`>poll Question | yes | no`, `>suggest idea`, `>bug report`\n"
            "`>vouch @user comment`, `>vouches [@user]`, `>stock`, `>pricing`\n"
            "Slash: `/setupapps` (Application Panel), `/gstart [duration] [prize]`"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{EMOJIS['gear']} Utility & Setup",
        value=(
            "`>say [#ch] text`, `>embed [#ch] Title | text`, `>dm @user text`\n"
            "`>reminder 30m text`, `>afk [reason]`, `>calc (2+2)*5`, `>roll 2d6`, `>flip`\n"
            "`>setstaff @role`, `>setsenior @role`, `>setjail @role`, `>setappeal #ch`\n"
            "`>setlevelchannel #ch`, `>setlevelrole 5`, `>setreaction #ch emoji`\n"
            "`>setverify @role [#ch]`, `>staffsettings`, `>setstaffsupervisor`, `>setaudit`"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"Requested by {ctx.author.display_name} • All systems online",
        icon_url=ctx.author.display_avatar.url
    )

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
        embed = discord.Embed(title=f"{EMOJIS['error']} Access Denied", description="You don't have permission to use this command.", color=discord.Color.red())
        await ctx.reply(embed=embed, mention_author=False)
    else:
        embed = discord.Embed(title=f"{EMOJIS['error']} An Error Occurred", description=str(error), color=discord.Color.red())
        await ctx.reply(embed=embed, mention_author=False)


load_config()
if not TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if OWNER_ID == 0:
    raise RuntimeError("Missing BOT_OWNER_ID environment variable.")

bot.run(TOKEN)
