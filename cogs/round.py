import asyncio
import logging
import math

import discord
from discord.ext import commands

from constants import ADMIN_PRIVILEGE_ROLES, PREFIX
from data import dbconn
from utils import (cf_api, challonge_api, codeforces, discord_,
                   tournament_helper)

MAX_ROUND_USERS = 5
LOWER_RATING = 800
UPPER_RATING = 3600
MATCH_DURATION = [5, 180]
MAX_PROBLEMS = 6
MAX_ALTS = 5
ROUNDS_PER_PAGE = 5


class Round(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.db = dbconn.DbConn()
        self.cf = cf_api.CodeforcesAPI()
        self.api = challonge_api.ChallongeAPI(self.client)
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.group(brief=f'Commands related to rounds! Type {PREFIX}round for more details',
                    invoke_without_command=True)
    @commands.check(discord_.is_channel_allowed)
    async def round(self, ctx):
        await ctx.send(embed=discord_.make_command_help_embed(self.client, ctx, 'round'))

    @round.command(name="challenge", brief="Challenge multiple users to a round")
    async def challenge(self, ctx, *users: discord.Member):
        users = list(set(users))
        if len(users) == 0:
            await discord_.send_message(ctx, f"The correct usage is `{PREFIX}round challenge @user1 @user2...`")
            return
        if ctx.author not in users:
            users.append(ctx.author)
        if len(users) > MAX_ROUND_USERS:
            await ctx.send(f"{ctx.author.mention} at most {MAX_ROUND_USERS} users can compete at a time")
            return
        for i in users:
            if not self.db.get_handle(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"Handle for {i.mention} not set! Use `{PREFIX}handle identify` to register")
                return
            if self.db.in_a_round(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"{i.mention} is already in a round!")
                return

        embed = discord.Embed(
            description=f"{' '.join(x.mention for x in users)} react on the message with ✅ within 30 seconds to join the round. {'Since you are the only participant, this will be a practice round and there will be no rating changes' if len(users) == 1 else ''}",
            color=discord.Color.purple())
        message = await ctx.send(embed=embed)
        await message.add_reaction("✅")

        all_reacted = False
        reacted = []

        def check(reaction, user):
            return reaction.message.id == message.id and reaction.emoji == "✅" and user in users

        while True:
            try:
                reaction, user = await self.client.wait_for('reaction_add', timeout=30, check=check)
                reacted.append(user)
                if all(item in reacted for item in users):
                    all_reacted = True
                    break
            except asyncio.TimeoutError:
                break

        if not all_reacted:
            await discord_.send_message(ctx, f"Unable to start round, some participant(s) did not react in time!")
            return

        problem_cnt = await discord_.get_time_response(self.client, ctx, f"{ctx.author.mention} enter the number of problems between [1, {MAX_PROBLEMS}]", 30, ctx.author, [1, MAX_PROBLEMS])
        if not problem_cnt[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        problem_cnt = problem_cnt[1]

        duration = await discord_.get_time_response(self.client, ctx, f"{ctx.author.mention} enter the duration of match in minutes between {MATCH_DURATION}", 30, ctx.author, MATCH_DURATION)
        if not duration[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        duration = duration[1]

        rating = await discord_.get_seq_response(self.client, ctx, f"{ctx.author.mention} enter {problem_cnt} space seperated integers denoting the ratings of problems (between {LOWER_RATING} and {UPPER_RATING})", 60, problem_cnt, ctx.author, [LOWER_RATING, UPPER_RATING])
        if not rating[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        rating = rating[1]

        points = await discord_.get_seq_response(self.client, ctx, f"{ctx.author.mention} enter {problem_cnt} space seperated integer denoting the points of problems (between 100 and 10,000)", 60, problem_cnt, ctx.author, [100, 10000])
        if not points[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        points = points[1]

        repeat = await discord_.get_time_response(self.client, ctx, f"{ctx.author.mention} do you want a new problem to appear when someone solves a problem (type 1 for yes and 0 for no)", 30, ctx.author, [0, 1])
        if not repeat[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        repeat = repeat[1]

        for i in users:
            if self.db.in_a_round(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"{i.name} is already in a round!")
                return

        alts = await discord_.get_alt_response(self.client, ctx, f"{ctx.author.mention} Do you want to add any alts? Type none if not applicable else type `alts: handle_1 handle_2 ...` You can add upto **{MAX_ALTS}** alt(s)", MAX_ALTS, 60, ctx.author)

        if not alts:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return

        alts = alts[1]

        tournament = 0
        if len(users) == 2 and (await tournament_helper.is_a_match(ctx.guild.id, users[0].id, users[1].id, self.api, self.db)):
            tournament = await discord_.get_time_response(self.client, ctx,
                                                          f"{ctx.author.mention} this round is a part of the tournament. Do you want the result of this round to be counted in the tournament. Type `1` for yes and `0` for no",
                                                          30, ctx.author, [0, 1])
            if not tournament[0]:
                await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
                return
            tournament = tournament[1]

        await ctx.send(embed=discord.Embed(description="Starting the round...", color=discord.Color.green()))

        problems = await codeforces.find_problems([self.db.get_handle(ctx.guild.id, x.id) for x in users] + alts, rating)
        if not problems[0]:
            await discord_.send_message(ctx, problems[1])
            return

        problems = problems[1]

        self.db.add_to_ongoing_round(ctx, users, rating, points, problems, duration, repeat, alts, tournament)
        round_info = self.db.get_round_info(ctx.guild.id, users[0].id)

        await ctx.send(embed=discord_.round_problems_embed(round_info))

    @round.command(name="ongoing", brief="View ongoing rounds")
    async def ongoing(self, ctx):
        data = self.db.get_all_rounds(ctx.guild.id)

        content = discord_.ongoing_rounds_embed(data)

        if len(content) == 0:
            await discord_.send_message(ctx, f"No ongoing rounds")
            return

        currPage = 0
        totPage = math.ceil(len(content) / ROUNDS_PER_PAGE)
        text = '\n'.join(content[currPage * ROUNDS_PER_PAGE: min(len(content), (currPage + 1) * ROUNDS_PER_PAGE)])
        embed = discord.Embed(description=text, color=discord.Color.blurple())
        embed.set_author(name="Ongoing Rounds")
        embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
        message = await ctx.send(embed=embed)

        await message.add_reaction("⏮")
        await message.add_reaction("◀")
        await message.add_reaction("▶")
        await message.add_reaction("⏭")

        def check(reaction, user):
            return reaction.message.id == message.id and reaction.emoji in ["⏮", "◀", "▶",
                                                                            "⏭"] and user != self.client.user

        while True:
            try:
                reaction, user = await self.client.wait_for('reaction_add', timeout=90, check=check)
                try:
                    await reaction.remove(user)
                except Exception:
                    pass
                if reaction.emoji == "⏮":
                    currPage = 0
                elif reaction.emoji == "◀":
                    currPage = max(currPage - 1, 0)
                elif reaction.emoji == "▶":
                    currPage = min(currPage + 1, totPage - 1)
                else:
                    currPage = totPage - 1
                text = '\n'.join(
                    content[currPage * ROUNDS_PER_PAGE: min(len(content), (currPage + 1) * ROUNDS_PER_PAGE)])
                embed = discord.Embed(description=text, color=discord.Color.blurple())
                embed.set_author(name="Ongoing rounds")
                embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
                await message.edit(embed=embed)

            except asyncio.TimeoutError:
                break

    @round.command(brief="Invalidate a round (Admin/Mod/Lockout Manager only)")
    async def _invalidate(self, ctx, member: discord.Member):
        if not discord_.has_admin_privilege(ctx):
            await discord_.send_message(ctx, f"{ctx.author.mention} you require 'manage server' permission or one of the "
                                        f"following roles: {', '.join(ADMIN_PRIVILEGE_ROLES)} to use this command")
            return
        if not self.db.in_a_round(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"{member.mention} is not in a round")
            return
        self.db.delete_round(ctx.guild.id, member.id)
        await discord_.send_message(ctx, f"Round deleted")

    @round.command(name="recent", brief="Show recent rounds")
    async def recent(self, ctx, user: discord.Member = None):
        data = self.db.get_recent_rounds(ctx.guild.id, str(user.id) if user else None)

        content = discord_.recent_rounds_embed(data)

        if len(content) == 0:
            await discord_.send_message(ctx, f"No recent rounds")
            return

        currPage = 0
        totPage = math.ceil(len(content) / ROUNDS_PER_PAGE)
        text = '\n'.join(content[currPage * ROUNDS_PER_PAGE: min(len(content), (currPage + 1) * ROUNDS_PER_PAGE)])
        embed = discord.Embed(description=text, color=discord.Color.blurple())
        embed.set_author(name="Recent Rounds")
        embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
        message = await ctx.send(embed=embed)

        await message.add_reaction("⏮")
        await message.add_reaction("◀")
        await message.add_reaction("▶")
        await message.add_reaction("⏭")

        def check(reaction, user):
            return reaction.message.id == message.id and reaction.emoji in ["⏮", "◀", "▶",
                                                                            "⏭"] and user != self.client.user

        while True:
            try:
                reaction, user = await self.client.wait_for('reaction_add', timeout=90, check=check)
                try:
                    await reaction.remove(user)
                except Exception:
                    pass
                if reaction.emoji == "⏮":
                    currPage = 0
                elif reaction.emoji == "◀":
                    currPage = max(currPage - 1, 0)
                elif reaction.emoji == "▶":
                    currPage = min(currPage + 1, totPage - 1)
                else:
                    currPage = totPage - 1
                text = '\n'.join(
                    content[currPage * ROUNDS_PER_PAGE: min(len(content), (currPage + 1) * ROUNDS_PER_PAGE)])
                embed = discord.Embed(description=text, color=discord.Color.blurple())
                embed.set_author(name="Recent rounds")
                embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
                await message.edit(embed=embed)

            except asyncio.TimeoutError:
                break

    @round.command(name="problems", brief="View problems of a round")
    async def problems(self, ctx, member: discord.Member = None):
        if not member:
            member = ctx.author
        if not self.db.in_a_round(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"{member.mention} is not in a round")
            return

        round_info = self.db.get_round_info(ctx.guild.id, member.id)
        await ctx.send(embed=discord_.round_problems_embed(round_info))

    @round.command(name="custom", brief="Challenge to a round with custom problemset")
    async def custom(self, ctx, *users: discord.Member):
        users = list(set(users))
        if len(users) == 0:
            await discord_.send_message(ctx, f"The correct usage is `{PREFIX}round custom @user1 @user2...`")
            return
        if ctx.author not in users:
            users.append(ctx.author)
        if len(users) > MAX_ROUND_USERS:
            await ctx.send(f"{ctx.author.mention} at most {MAX_ROUND_USERS} users can compete at a time")
            return
        for i in users:
            if not self.db.get_handle(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"Handle for {i.mention} not set! Use `{PREFIX}handle identify` to register")
                return
            if self.db.in_a_round(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"{i.mention} is already in a round!")
                return

        embed = discord.Embed(
            description=f"{' '.join(x.mention for x in users)} react on the message with ✅ within 30 seconds to join the round. {'Since you are the only participant, this will be a practice round and there will be no rating changes' if len(users) == 1 else ''}",
            color=discord.Color.purple())
        message = await ctx.send(embed=embed)
        await message.add_reaction("✅")

        all_reacted = False
        reacted = []

        def check(reaction, user):
            return reaction.message.id == message.id and reaction.emoji == "✅" and user in users

        while True:
            try:
                reaction, user = await self.client.wait_for('reaction_add', timeout=30, check=check)
                reacted.append(user)
                if all(item in reacted for item in users):
                    all_reacted = True
                    break
            except asyncio.TimeoutError:
                break

        if not all_reacted:
            await discord_.send_message(ctx, f"Unable to start round, some participant(s) did not react in time!")
            return

        problem_cnt = await discord_.get_time_response(self.client, ctx,
                                                       f"{ctx.author.mention} enter the number of problems between [1, {MAX_PROBLEMS}]",
                                                       30, ctx.author, [1, MAX_PROBLEMS])
        if not problem_cnt[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        problem_cnt = problem_cnt[1]

        duration = await discord_.get_time_response(self.client, ctx,
                                                    f"{ctx.author.mention} enter the duration of match in minutes between {MATCH_DURATION}",
                                                    30, ctx.author, MATCH_DURATION)
        if not duration[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        duration = duration[1]

        problems = await discord_.get_problems_response(self.client, ctx,
                                                        f"{ctx.author.mention} enter {problem_cnt} space seperated problem ids denoting the problems. Eg: `123/A 455/B 242/C ...`",
                                                        60, problem_cnt, ctx.author)
        if not problems[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        problems = problems[1]

        points = await discord_.get_seq_response(self.client, ctx,
                                                 f"{ctx.author.mention} enter {problem_cnt} space seperated integer denoting the points of problems (between 100 and 10,000)",
                                                 60, problem_cnt, ctx.author, [100, 10000])
        if not points[0]:
            await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
            return
        points = points[1]

        for i in users:
            if self.db.in_a_round(ctx.guild.id, i.id):
                await discord_.send_message(ctx, f"{i.name} is already in a round!")
                return
        rating = [problem.rating for problem in problems]

        tournament = 0
        if len(users) == 2 and (await tournament_helper.is_a_match(ctx.guild.id, users[0].id, users[1].id, self.api, self.db)):
            tournament = await discord_.get_time_response(self.client, ctx,
                                                          f"{ctx.author.mention} this round is a part of the tournament. Do you want the result of this round to be counted in the tournament. Type `1` for yes and `0` for no",
                                                          30, ctx.author, [0, 1])
            if not tournament[0]:
                await discord_.send_message(ctx, f"{ctx.author.mention} you took too long to decide")
                return
            tournament = tournament[1]

        await ctx.send(embed=discord.Embed(description="Starting the round...", color=discord.Color.green()))
        self.db.add_to_ongoing_round(ctx, users, rating, points, problems, duration, 0, [], tournament)
        round_info = self.db.get_round_info(ctx.guild.id, users[0].id)

        await ctx.send(embed=discord_.round_problems_embed(round_info))


def setup(client):
    client.add_cog(Round(client))
