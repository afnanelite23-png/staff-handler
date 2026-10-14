import os
import json
import logging
import discord
from discord.ext import commands

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

# Persistent settings
# Added "rank_ladders" to store ordered role lists per guild
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

        role_id = guild_setting(
            "supervisor_roles", ctx.guild.id
        )

        if not role_id:
            return False

        return any(
            role.id == int(role_id)
            for role in ctx.author.roles
        )

    return commands.check(predicate)


# =========================
# AUDIT LOGGING
# =========================

async def audit(guild, message):
    channel_id = guild_setting("audit_channels", guild.id)

    if not channel_id:
        return

    channel = guild.get_channel(int(channel_id))

    if channel is None:
        return

    try:
        await channel.send(
            message,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        logging.exception("Failed to send audit log")


# =========================
# PROMOTION / DEMOTION EMBEDS
# =========================

async def send_promodemo_embed(
    guild, member, role, action, moderator
):
    channel_id = guild_setting(
        "promodemo_channels", guild.id
    )

    if not channel_id:
        logging.info(
            "No promotion/demotion channel configured for %s",
            guild.id
        )
        return

    channel = guild.get_channel(int(channel_id))

    if channel is None:
        logging.warning("Promotion/demotion channel not found")
        return

    promoted = action == "promoted"

    embed = discord.Embed(
        title=(
            "🚀 Staff Promotion"
            if promoted else "🔻 Staff Demotion"
        ),
        description=(
            f"{member.mention} has been **promoted**! ✨"
            if promoted else
            f"{member.mention} has been **demoted**. 📉"
        ),
        color=(
            discord.Color.green()
            if promoted else discord.Color.red()
        ),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="👤 Staff Member",
        value=f"{member.mention}\n`{member.id}`",
        inline=False
    )

    embed.add_field(
        name="🏷️ Role",
        value=role.mention,
        inline=True
    )

    embed.add_field(
        name="🛡️ Action By",
        value=moderator.mention,
        inline=True
    )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"{guild.name} • Staff Management System")

    try:
        await channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        logging.exception(
            "Failed to send promotion/demotion announcement"
        )


# =========================
# RANK LADDER DROPDOWN SETUP
# =========================

class RankSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild):
        # Filter out default and managed roles, keep up to 25 for select menu limits
        roles = [r for r in guild.roles if not r.is_default() and not r.managed][:25]
        
        options = [
            discord.SelectOption(
                label=role.name, 
                value=str(role.id), 
                emoji="🔹"
            ) for role in roles
        ]

        if not options:
            options = [discord.SelectOption(label="No valid roles available", value="none")]

        super().__init__(
            placeholder="📌 Select staff ranks in order (Lowest to Highest)...",
            min_values=1,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values == ["none"]:
            await interaction.response.send_message("❌ No valid roles to configure.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        selected_role_ids = [int(val) for val in self.values]
        
        if "rank_ladders" not in config:
            config["rank_ladders"] = {}
        
        config["rank_ladders"][guild_id] = selected_role_ids
        save_config()

        roles_mention = ", ".join([f"<@&{r_id}>" for r_id in selected_role_ids])
        
        embed = discord.Embed(
            title="✅ Rank Ladder Configured Successfully!",
            description=f"**Ordered Ladder Hierarchy:**\n{roles_mention}\n\n*Now you can use `>promo @member` without specifying a role to auto-promote to the next rank!*",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class RankSelectView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.add_item(RankSelect(guild))


# =========================
# STAFF ROLE CHANGES & AUTO-PROMO
# =========================

async def change_staff_role(ctx, member, role, action):
    if member.id == ctx.author.id:
        await ctx.reply("⚠️ You cannot change your own staff role.")
        return

    if member.id == ctx.guild.owner_id:
        await ctx.reply("⚠️ You cannot modify the server owner's roles.")
        return

    if role.is_default() or role.managed:
        await ctx.reply("⚠️ That role cannot be assigned.")
        return

    bot_member = ctx.guild.me

    if bot_member is None or role >= bot_member.top_role:
        await ctx.reply(
            "⚠️ My highest role must be above the selected role."
        )
        return

    if ctx.author.id != OWNER_ID:
        if role >= ctx.author.top_role:
            await ctx.reply(
                "⚠️ You cannot manage a role equal to or above yours."
            )
            return

        if member.top_role >= ctx.author.top_role:
            await ctx.reply(
                "⚠️ You cannot manage a member equal to or above you."
            )
            return

    if action == "promote" and role in member.roles:
        await ctx.reply("⚠️ That member already has this role.")
        return

    if action == "demote" and role not in member.roles:
        await ctx.reply("⚠️ That member does not have this role.")
        return

    try:
        if action == "promote":
            await member.add_roles(
                role,
                reason=f"Staff promotion by {ctx.author}"
            )
            result = "promoted"

        else:
            await member.remove_roles(
                role,
                reason=f"Staff demotion by {ctx.author}"
            )
            result = "demoted"

        await send_promodemo_embed(
            ctx.guild,
            member,
            role,
            result,
            ctx.author
        )

        await audit(
            ctx.guild,
            f"Staff {result}: {member} ({member.id}) | "
            f"Role: {role.name} ({role.id}) | "
            f"By: {ctx.author} ({ctx.author.id})"
        )

        emoji = "🚀" if result == "promoted" else "🔻"
        await ctx.reply(
            f"{emoji} {member.mention} was **{result}**: {role.mention}"
        )

    except discord.Forbidden:
        await ctx.reply(
            "⛔ I lack permission to change that role. "
            "Check my Manage Roles permission and role hierarchy."
        )

    except discord.HTTPException:
        logging.exception("Role change failed")
        await ctx.reply("❌ Discord rejected the role change.")


# =========================
# PROMO / DEMO COMMANDS
# =========================

@bot.command()
@commands.guild_only()
@is_supervisor()
async def promo(ctx, staff: discord.Member, role: discord.Role = None):
    """Promotes a staff member. If no role is given, uses the rank ladder."""
    if role is None:
        ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id))
        if not ladder:
            await ctx.reply("⚠️ No rank ladder has been set up yet! Use `>setranks` or specify a role manually (`>promo @member @role`).")
            return
        
        # Determine next rank based on ladder
        user_role_ids = [r.id for r in staff.roles]
        matched_index = -1
        
        for idx, r_id in enumerate(ladder):
            if r_id in user_role_ids:
                matched_index = idx
        
        # If user has no rank in ladder, pick the first one. Otherwise, pick the next one.
        next_index = matched_index + 1
        if next_index >= len(ladder):
            await ctx.reply(f"⚠️ {staff.mention} is already at the highest rank on the ladder!")
            return
            
        role = ctx.guild.get_role(ladder[next_index])
        if role is None:
            await ctx.reply("❌ The configured next rank role no longer exists in this server.")
            return

    await change_staff_role(ctx, staff, role, "promote")


@bot.command()
@commands.guild_only()
@is_supervisor()
async def demo(
    ctx,
    staff: discord.Member,
    role: discord.Role
):
    await change_staff_role(ctx, staff, role, "demote")


# =========================
# SETUP COMMANDS
# =========================

@bot.command()
@commands.guild_only()
@is_owner()
async def setranks(ctx):
    """Opens an interactive dropdown menu to configure the staff rank ladder sequence."""
    view = RankSelectView(ctx.guild)
    embed = discord.Embed(
        title="📊 Staff Rank Ladder Setup",
        description="Select the staff roles below **in order from lowest to highest rank** using the dropdown menu.\n\n*This allows automatic promotion using `>promo @member`.*",
        color=discord.Color.blurple()
    )
    await ctx.reply(embed=embed, view=view)


@bot.command()
@commands.guild_only()
@is_owner()
async def setstaffsupervisor(ctx, role: discord.Role):
    if role.is_default() or role.managed:
        await ctx.reply("⚠️ Choose a normal server role.")
        return

    config["supervisor_roles"][str(ctx.guild.id)] = role.id
    save_config()

    embed = discord.Embed(
        title="🛡️ Staff Supervisor Configured",
        description=(
            f"Authorized staff supervisors: {role.mention}\n\n"
            "Members with this role can use `>promo` and `>demo`."
        ),
        color=discord.Color.blue()
    )

    await ctx.reply(embed=embed)
    await audit(ctx.guild, f"Supervisor role set to {role.name} by {ctx.author}")


@bot.command()
@commands.guild_only()
@is_owner()
async def setpromodemo(ctx, channel: discord.TextChannel):
    config["promodemo_channels"][str(ctx.guild.id)] = channel.id
    save_config()

    embed = discord.Embed(
        title="📢 Promotion & Demotion Channel Set",
        description=(
            f"Channel: {channel.mention}\n\n"
            "Promotion and demotion announcements will appear here."
        ),
        color=discord.Color.green()
    )

    await ctx.reply(embed=embed)
    await audit(ctx.guild, f"Promotion/demotion channel set to #{channel.name} by {ctx.author}")


@bot.command()
@commands.guild_only()
@is_owner()
async def setaudit(ctx, channel: discord.TextChannel):
    config["audit_channels"][str(ctx.guild.id)] = channel.id
    save_config()
    await ctx.reply(f"✅ Audit log channel set to {channel.mention}")


# =========================
# SHOW CURRENT SETTINGS
# =========================

@bot.command()
@commands.guild_only()
@is_owner()
async def staffsettings(ctx):
    supervisor_id = guild_setting("supervisor_roles", ctx.guild.id)
    promo_id = guild_setting("promodemo_channels", ctx.guild.id)
    audit_id = guild_setting("audit_channels", ctx.guild.id)
    ladder = config.get("rank_ladders", {}).get(str(ctx.guild.id), [])

    supervisor = ctx.guild.get_role(int(supervisor_id)) if supervisor_id else None
    promo_channel = ctx.guild.get_channel(int(promo_id)) if promo_id else None
    audit_channel = ctx.guild.get_channel(int(audit_id)) if audit_id else None
    
    ladder_str = " -> ".join([f"<@&{r_id}>" for r_id in ladder]) if ladder else "Not configured"

    embed = discord.Embed(
        title="⚙️ Staff Bot Settings",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛡️ Supervisor Role",
        value=supervisor.mention if supervisor else "Not configured",
        inline=False
    )
    embed.add_field(
        name="📢 Promo/Demo Channel",
        value=promo_channel.mention if promo_channel else "Not configured",
        inline=False
    )
    embed.add_field(
        name="📋 Audit Channel",
        value=audit_channel.mention if audit_channel else "Not configured",
        inline=False
    )
    embed.add_field(
        name="📊 Rank Ladder Sequence",
        value=ladder_str,
        inline=False
    )

    await ctx.reply(embed=embed)


# =========================
# HELP COMMAND
# =========================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="📋 Staff Management Bot - Help Center",
        description="Here is a complete list of commands with custom visual categories:",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="🛡️ Staff Supervisor Commands",
        value=(
            "`>promo @member [@role]` — Promote a staff member (Auto-promotes to next rank if role is omitted)\n"
            "`>demo @member @role` — Demote a staff member by removing a role"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Bot Owner Setup Commands",
        value=(
            "`>setranks` — Open interactive menu to configure the server rank ladder\n"
            "`>setstaffsupervisor @role` — Set the designated supervisor role\n"
            "`>setpromodemo #channel` — Set the promotion/demotion announcement channel\n"
            "`>setaudit #channel` — Set the audit log channel\n"
            "`>staffsettings` — View the current server configuration settings"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"Requested by {ctx.author.display_name}",
        icon_url=ctx.author.display_avatar.url
    )

    await ctx.reply(embed=embed, mention_author=False)


# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)
    logging.info("Connected to %s server(s)", len(bot.guilds))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.reply("⛔ You don't have permission to use this command.")

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("⚠️ Missing argument. Use `>help` to see command syntax.")

    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ Member not found. Mention a valid member.")

    elif isinstance(error, commands.RoleNotFound):
        await ctx.reply("❌ Role not found. Mention a valid role.")

    elif isinstance(error, commands.ChannelNotFound):
        await ctx.reply("❌ Channel not found. Mention a valid text channel.")

    elif isinstance(error, commands.BadArgument):
        await ctx.reply("⚠️ Invalid argument. Check your mentions or types.")

    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.reply("⚠️ This command can only be used in a server.")

    else:
        logging.exception("Unhandled command error", exc_info=error)
        await ctx.reply("❌ An unexpected error occurred.")


# =========================
# START BOT
# =========================

load_config()

if not TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")

if OWNER_ID == 0:
    raise RuntimeError("Missing BOT_OWNER_ID environment variable.")

bot.run(TOKEN)
