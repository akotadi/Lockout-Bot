import asyncio
import logging
import random
import string
from operator import itemgetter

import discord
from discord import Color, Embed
from discord.ext import commands
from discord.ext.commands import BucketType, CommandOnCooldown, cooldown

from constants import ADMIN_PRIVILEGE_ROLES, PREFIX
from data import dbconn
from utils import cf_api, discord_, paginator

HANDLE_IDENTIFY_WAIT_TIME = 60
HANDLES_PER_PAGE = 15

cf_colors = {
    'unrated': 0x000000,
    'newbie': 0x808080,
    'pupil': 0x008000,
    'specialist': 0x03a89e,
    'expert': 0x0000ff,
    'candidate master': 0xaa00aa,
    'master': 0xff8c00,
    'international master': 0xf57500,
    'grandmaster': 0xff3030,
    'international grandmaster': 0xff0000,
    'legendary grandmaster': 0xcc0000
}


class Handle(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.db = dbconn.DbConn()
        self.cf = cf_api.CodeforcesAPI()
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.group(
        brief=f'Commands related to handle! Type {PREFIX}handle for more details', invoke_without_command=True)
    @commands.check(discord_.is_channel_allowed)
    async def handle(self, ctx):
        await ctx.send(embed=discord_.make_command_help_embed(self.client, ctx, 'handle'))

    @handle.command(brief="Set someone's handle (Admin/Mod/Lockout Manager only)")
    async def set(self, ctx, member: discord.Member, handle: str):
        if not discord_.has_admin_privilege(ctx):
            await discord_.send_message(ctx, f"{ctx.author.mention} you require 'manage server' permission or one of the "
                                        f"following roles: {', '.join(ADMIN_PRIVILEGE_ROLES)} to use this command")
            return

        data = await self.cf.check_handle(handle)
        if not data[0]:
            await discord_.send_message(ctx, data[1])
            return

        handle = data[1]['handle']
        if self.db.get_handle(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"Handle for user {member.mention} already set to {self.db.get_handle(ctx.guild.id, member.id)}")
            return
        # 2 discord users setting same handle
        handles = list(
            filter(lambda x: x[2] == handle, self.db.get_all_handles(ctx.guild.id)))
        if len(handles):
            handle_user = await discord_.fetch_member(ctx.guild, handles[0][1])
            await discord_.send_message(ctx, f"{member.mention} Handle {handle} is already in use by {handle_user.mention}")
            return

        # all conditions met
        data = data[1]
        if "rating" not in data:
            rating = 0
            rank = "unrated"
        else:
            rating = data['rating']
            rank = data['rank']
        self.db.add_handle(ctx.guild.id, member.id, handle, rating)
        self.db.add_rated_user(ctx.guild.id, member.id)
        embed = discord.Embed(
            description=f'Handle for user {member.mention} successfully set to [{handle}](https://codeforces.com/profile/{handle})',
            color=Color(cf_colors[rank.lower()]))
        embed.add_field(name='Rank', value=f'{rank}', inline=True)
        embed.add_field(name='Rating', value=f'{rating}', inline=True)
        embed.set_thumbnail(url=f"{data['titlePhoto']}")
        await ctx.send(embed=embed)

    @handle.command(brief="Remove someone's handle (Admin/Mod/Lockout Manager only)")
    async def remove(self, ctx, member: discord.Member):
        if not discord_.has_admin_privilege(ctx):
            await discord_.send_message(ctx, f"{ctx.author.mention} you require 'manage server' permission or one of the "
                                        f"following roles: {', '.join(ADMIN_PRIVILEGE_ROLES)} to use this command")
            return
        if not self.db.get_handle(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"Handle for {member.mention} not set")
            return
        if self.db.in_a_round(ctx.guild.id, member.id) or self.db.in_a_match(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"{member.mention} is currently in a match/round. Try again later")
            return

        self.db.remove_handle(ctx.guild.id, member.id)
        await ctx.send(
            embed=Embed(description=f"Handle for {member.mention} removed successfully", color=Color.green()))

    @handle.command(brief="Set your Codeforces handle")
    @cooldown(1, HANDLE_IDENTIFY_WAIT_TIME, BucketType.user)
    async def identify(self, ctx, handle: str):
        if self.db.get_handle(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, f"Your handle is already set to {self.db.get_handle(ctx.guild.id, ctx.author.id)}, "
                                        f"ask an admin or mod to remove it first and try again.")
            ctx.command.reset_cooldown(ctx)
            return

        data = await self.cf.check_handle(handle)
        if not data[0]:
            await discord_.send_message(ctx, data[1])
            ctx.command.reset_cooldown(ctx)
            return

        data = data[1]
        handle = data['handle']

        # 2 discord users setting same handle
        handles = list(
            filter(lambda x: x[2] == handle, self.db.get_all_handles(ctx.guild.id)))
        if len(handles):
            handle_user = await discord_.fetch_member(ctx.guild, handles[0][1])
            await discord_.send_message(ctx, f"{ctx.author.mention} Handle {handle} is already in use by {handle_user.mention}")
            return

        res = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=15))
        await discord_.send_message(ctx,
                                    f"Please change your first name on this [link](https://codeforces.com/settings/social) to "
                                    f"`{res}` within {HANDLE_IDENTIFY_WAIT_TIME} seconds {ctx.author.mention}")
        await asyncio.sleep(HANDLE_IDENTIFY_WAIT_TIME)

        if res != await self.cf.get_first_name(handle):
            await discord_.send_message(ctx, f"Unable to set handle, please try again {ctx.author.mention}")
            return

        try:
            member = ctx.author
            if "rating" not in data:
                rating = 0
                rank = "unrated"
            else:
                rating = data['rating']
                rank = data['rank']
            self.db.add_handle(ctx.guild.id, member.id, handle, rating)
            self.db.add_rated_user(ctx.guild.id, member.id)
            embed = discord.Embed(
                description=f'Handle for {member.mention} successfully set to [{handle}](https://codeforces.com/profile/{handle})',
                color=Color(cf_colors[rank.lower()]))
            embed.add_field(name='Rank', value=f'{rank}', inline=True)
            embed.add_field(name='Rating', value=f'{rating}', inline=True)
            embed.set_thumbnail(url=f"https:{data['titlePhoto']}")
            await ctx.send(embed=embed)
        except Exception as err:
            self.logger.error(f"Error while setting handle {err}")

    @identify.error
    async def identify_error(self, ctx, exc):
        if isinstance(exc, CommandOnCooldown):
            await ctx.send(embed=discord.Embed(
                description=f"Slow down!\nThe cooldown of command is **{HANDLE_IDENTIFY_WAIT_TIME}s**, pls retry after "
                            f"**{exc.retry_after:,.2f}s**",
                color=discord.Color.red()))

    @handle.command(brief="Get someone's handle")
    async def get(self, ctx, member: discord.Member):
        if not self.db.get_handle(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f'Handle for {member.mention} is not set currently')
            return
        handle = self.db.get_handle(ctx.guild.id, member.id)
        data = await self.cf.check_handle(handle)
        if not data[0]:
            await discord_.send_message(ctx, data[1])
            ctx.command.reset_cooldown(ctx)
            return

        data = data[1]
        if "rating" not in data:
            rating = 0
            rank = "unrated"
        else:
            rating = data['rating']
            rank = data['rank']
        embed = discord.Embed(
            description=f'Handle for {member.mention} currently set to [{handle}](https://codeforces.com/profile/{handle})',
            color=Color(cf_colors[rank.lower()]))
        embed.add_field(name='Rank', value=f'{rank}', inline=True)
        embed.add_field(name='Rating', value=f'{rating}', inline=True)
        embed.set_thumbnail(url=f"{data['titlePhoto']}")
        await ctx.send(embed=embed)

    @handle.command(brief="Get handle list")
    async def list(self, ctx):
        data = self.db.get_all_handles(ctx.guild.id)
        if len(data) == 0:
            await discord_.send_message(ctx, "No one has set their handle yet")
            return
        data1 = []
        for x in data:
            try:
                data1.append([(await discord_.fetch_member(ctx.guild, int(x[1]))).name, x[2], x[3]])
            except Exception as e:
                self.logger.error(f"Handle list error: {e}")
        data = data1
        data = sorted(data, key=itemgetter(2), reverse=True)
        data = [[x[0], x[1], str(x[2])] for x in data]
        await paginator.Paginator(data, ["User", "Handle", "Rating"], f"Handle List", HANDLES_PER_PAGE).paginate(ctx, self.client)


def setup(client):
    client.add_cog(Handle(client))
