import logging

import discord
from discord.ext import commands
from discord.ext.commands import BucketType

from constants import PREFIX
from utils.discord_ import is_channel_allowed


class Help(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.client.remove_command("help")
        self.logger = logging.getLogger(self.__class__.__name__)

    def make_help_embed(self, ctx):
        headers = f"Information about commands are given below!\nFor general information about the bot,  type `{PREFIX}botinfo`"
        handle = self.client.get_command('handle')
        match = self.client.get_command('match')
        round = self.client.get_command('round')
        tournament = self.client.get_command('tournament')
        footers = "\n```cpp\nReact to change pages\nPage 1: Handle related commands\nPage 2: Match related " \
                  "commands\nPage 3: Round related commands\nPage 4: Tournament related commands``` "

        content = []
        desc = f"\n\n:crossed_swords: [Handle related commands](https://github.com/pseudocoder10/Lockout-Bot/wiki/Handle-related-commands) **[use {PREFIX}handle <command>]**\n\n"
        for cmd in handle.commands:
            desc += f"`{cmd.name}`: **{cmd.brief}**\n"
        content.append(desc)

        desc = f"\n\n:crossed_swords: [Match related commands](https://github.com/pseudocoder10/Lockout-Bot/wiki/Match-related-commands) **[use {PREFIX}match <command>]**\n\n"
        for cmd in match.commands:
            desc += f"`{cmd.name}`: **{cmd.brief}**\n"
        content.append(desc)

        desc = f"\n\n:crossed_swords: [Round related commands](https://github.com/pseudocoder10/Lockout-Bot/wiki/Round-related-commands) **[use {PREFIX}round <command>]**\n\n"
        for cmd in round.commands:
            desc += f"`{cmd.name}`: **{cmd.brief}**\n"
        content.append(desc)

        desc = f"\n\n:crossed_swords: [Tournament related commands](https://github.com/pseudocoder10/Lockout-Bot/wiki/Tournament-related-commands) **[use {PREFIX}tournament <command>]**\n\n"
        for cmd in tournament.commands:
            desc += f"`{cmd.name}`: **{cmd.brief}**\n"
        content.append(desc)

        embeds = []
        for desc in content:
            embed = discord.Embed(description=headers + desc + footers, color=discord.Color.dark_magenta())
            embed.set_author(name="Lockout commands help", icon_url=ctx.me.avatar_url)
            embed.set_footer(
                text=f"Use the prefix {PREFIX} before each command. For detailed usage about a particular command, type {PREFIX}help <command>")
            embeds.append(embed)

        return embeds

    def make_cmd_embed(self, command):
        usage = f".{str(command)} "
        params = []
        for key, value in command.params.items():
            if key not in ['self', 'ctx']:
                params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
        usage += ' '.join(params)
        aliases = [str(command), *command.aliases]
        embed = discord.Embed(title=f"Information about {str(command)}", color=discord.Color.dark_magenta())
        embed.add_field(name="Description", value=command.brief, inline=False)
        embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
        embed.add_field(name="Aliases", value=f"{' '.join([f'`{x}`' for x in aliases])}", inline=False)
        return embed

    @commands.command(name="help")
    @commands.cooldown(1, 5, BucketType.user)
    @commands.check(is_channel_allowed)
    async def help(self, ctx, *, cmd: str = None):
        """Shows help for various commands"""
        if cmd is None:
            embeds = self.make_help_embed(ctx)
            emotes = ['1⃣', '2⃣', '3⃣', '4⃣']
            msg = await ctx.send(embed=embeds[0])
            for emote in emotes:
                await msg.add_reaction(emote)

            def check(reaction, user):
                return reaction.message.id == msg.id and reaction.emoji in emotes and user != self.client.user

            while True:
                try:
                    reaction, user = await self.client.wait_for('reaction_add', timeout=60, check=check)
                    try:
                        await reaction.remove(user)
                    except Exception:
                        pass
                    await msg.edit(embed=embeds[emotes.index(reaction.emoji)])
                except Exception:
                    break
        else:
            command = self.client.get_command(cmd)
            if command is None or command.hidden:
                await ctx.send(f"{ctx.author.mention} that command does not exists")
                return
            await ctx.send(embed=self.make_cmd_embed(command))


def setup(client):
    client.add_cog(Help(client))
