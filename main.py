
import os
import logging
import discord
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=">",
    intents=intents,
    help_command=None
)

supervisor_roles = {}
audit_channels = {}


async def audit(guild, message):
    channel_id = audit_channels.get(guild.id)

    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.send(message)
            except discord.HTTPException:
                logging.warning("Could not send audit log.")


def is_owner():
    async def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)


def is_supervisor():
    async def predicate(ctx):
        if ctx.author.id == OWNER_ID:
            return True

        role_id = supervisor_roles.get(ctx.guild.id, 0)
        return any(role.id == role_id for role in ctx.author.roles)

    return commands.check(predicate)


async def change_staff_role(ctx, member, role, action):
    if member.id == ctx.author.id:
        await ctx.reply("You cannot change your own staff role.")
        return

    if member.id == ctx.guild.owner_id:
        await ctx.reply("You cannot modify the server owner's roles.")
        return

    if role.is_default() or role.managed:
        await ctx.reply("That role cannot be assigned.")
        return

    bot_member = ctx.guild.me

    if role >= bot_member.top_role:
        await ctx.reply("My highest role must be above that role.")
        return

    if role >= ctx.author.top_role and ctx.author.id != OWNER_ID:
        await ctx.reply("You cannot manage a role equal to or above yours.")
        return

    try:
        if action == "promote":
            await member.add_roles(
                role, reason=f"Staff promotion by {ctx.author}"
            )
        else:
            await member.remove_roles(
                role, reason=f"Staff demotion by {ctx.author}"
            )

        await ctx.reply(
            f"{member.mention} was {action}d: {role.mention}"
        )

        await audit(
            ctx.guild,
            f"Staff {action}: {member} ({member.id}) | "
            f"Role: {role.name} | By: {ctx.author}"
        )

    except discord.Forbidden:
        await ctx.reply("I lack the required Discord permissions.")
    except discord.HTTPException:
        await ctx.reply("Discord rejected the role change. Try again.")


@bot.command()
@is_supervisor()
async def promo(ctx, staff: discord.Member, role: discord.Role):
    await change_staff_role(ctx, staff, role, "promote")


@bot.command()
@is_supervisor()
async def demo(ctx, staff: discord.Member, role: discord.Role):
    await change_staff_role(ctx, staff, role, "demote")


@bot.command()
@is_owner()
async def setstaffsupervisor(ctx, role: discord.Role):
    if role.is_default() or role.managed:
        await ctx.reply("Choose a normal, assignable server role.")
        return

    supervisor_roles[ctx.guild.id] = role.id

    await ctx.reply(
        f"Staff supervisor role set to {role.mention}"
    )

    await audit(
        ctx.guild,
        f"Supervisor role configured: {role.name} by {ctx.author}"
    )


@bot.command()
@is_owner()
async def setaudit(ctx, channel: discord.TextChannel):
    audit_channels[ctx.guild.id] = channel.id
    await ctx.reply(f"Audit channel set to {channel.mention}")


@bot.command()
async def help(ctx):
    await ctx.reply(
        "**Staff Bot Commands**\n"
        "`>promo @member @role` — Promote staff\n"
        "`>demo @member @role` — Demote staff\n"
        "`>setstaffsupervisor @role` — Owner only\n"
        "`>setaudit #channel` — Owner only"
    )


@bot.event
async def on_ready():
    logging.info("Logged in as %s", bot.user)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Missing argument. Use `>help` for examples.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("Member not found.")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.reply("Role not found.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Invalid argument. Check the member and role.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        logging.error("Command error: %s", error)
        await ctx.reply("An unexpected error occurred.")


if not TOKEN or OWNER_ID == 0:
    raise RuntimeError("Set BOT_TOKEN and BOT_OWNER_ID first.")

bot.run(TOKEN)
