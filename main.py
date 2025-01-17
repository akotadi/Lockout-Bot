import datetime
import logging
import os
from logging.handlers import TimedRotatingFileHandler

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext.commands import (BadArgument, Bot, CommandNotFound,
                                  CommandOnCooldown, MemberNotFound,
                                  MissingPermissions, MissingRequiredArgument,
                                  when_mentioned_or)

from constants import AUTO_UPDATE_TIME, LOG_FILE_PATH, PREFIX
from utils import tasks

intents = discord.Intents.default()
intents.members = False
client = Bot(
    case_insensitive=True,
    description="Lockout Bot",
    command_prefix=when_mentioned_or(PREFIX),
    intents=intents)


@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game(name="in matches ⚔️"))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(update, 'interval', seconds=AUTO_UPDATE_TIME)
    scheduler.add_job(tasks.create_backup, CronTrigger(hour="0, 6, 12, 18", timezone="Asia/Kolkata"), [client])
    scheduler.add_job(tasks.update_ratings, CronTrigger(minute="30", timezone="Asia/Kolkata"), [client])
    scheduler.add_job(tasks.update_problemset, CronTrigger(hour="8", timezone="Asia/Kolkata"), [client])
    scheduler.add_job(tasks.scrape_authors, CronTrigger(day_of_week="0", timezone="Asia/Kolkata"), [client])
    scheduler.start()


async def update():
    await tasks.update_matches(client)
    await tasks.update_rounds(client)


@client.event
async def on_command_error(ctx: discord.ext.commands.Context, error: Exception):
    if isinstance(error, CommandNotFound):
        pass

    elif isinstance(error, CommandOnCooldown):
        tot = error.cooldown.per
        rem = error.retry_after
        msg = f"{ctx.author.mention} That command has a default cooldown of {str(datetime.timedelta(seconds=tot)).split('.')[0]}.\n"
        msg += f"Please retry after {str(datetime.timedelta(seconds=rem)).split('.')[0]}."
        embed = discord.Embed(description=msg, color=discord.Color.red())
        embed.set_author(name=f"Slow down!")
        await ctx.send(embed=embed)

    elif isinstance(error, MemberNotFound):
        command = ctx.command
        command.reset_cooldown(ctx)
        await ctx.send(embed=discord.Embed(description=f"`{str(error)}`\nTry mentioning the user instead of typing name/id", color=discord.Color.gold()))

    elif isinstance(error, BadArgument) or isinstance(error, MissingRequiredArgument):
        command = ctx.command
        command.reset_cooldown(ctx)
        usage = f"`.{str(command)} "
        params = []
        for key, value in command.params.items():
            if key not in ['self', 'ctx']:
                params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
        usage += ' '.join(params)
        usage += '`'
        if command.help:
            usage += f"\n\n{command.help}"
        await ctx.send(embed=discord.Embed(description=f"The correct usage is: {usage}", color=discord.Color.gold()))

    elif isinstance(error, MissingPermissions):
        await ctx.send(f"{str(error)}")

    else:
        desc = f"{ctx.author.name}({ctx.author.id}) {ctx.guild.name}({ctx.guild.id}) {ctx.message.content}\n"
        desc += f"**{str(error)}**"


if __name__ == "__main__":
    # Logging setup
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(format='{asctime}:{levelname}:{name}:{message}', style='{',
                        datefmt='%d-%m-%Y %H:%M:%S', level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  TimedRotatingFileHandler(LOG_FILE_PATH, when='D',
                                                           backupCount=3, utc=True)])

    token = os.environ.get('LOCKOUT_BOT_TOKEN')
    if not token:
        logging.error('Token required')
        exit

    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                client.load_extension(f'cogs.{filename[:-3]}')
            except Exception as e:
                logging.info(f'Failed to load file {filename}: {str(e)}')

    client.run(token)
