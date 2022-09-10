import asyncio
import logging
import math
import os
import time
from io import BytesIO
from operator import itemgetter

import discord
import matplotlib.pyplot as plt
from discord import Color, Embed, File
from discord.ext import commands

from constants import ADMIN_PRIVILEGE_ROLES, PREFIX
from data import dbconn
from utils import cf_api, codeforces, discord_, elo, paginator, updation

LOWER_RATING = 800
UPPER_RATING = 3600
MATCH_DURATION = [5, 180]
RESPONSE_WAIT_TIME = 30
ONGOING_PER_PAGE = 10
RECENT_PER_PAGE = 5


async def plot_graph(ctx, data, handle):
    x_axis, y_axis = [], []
    for i in range(0, len(data)):
        x_axis.append(i + 1)
        y_axis.append(data[i])
    ends = [-100000, 1300, 1400, 1500, 1600, 1700, 1750, 1800, 1850, 1900, 100000]
    colors = ['#CCCCCC', '#77FF77', '#77DDBB', '#AAAAFF', '#FF88FF', '#FFCC88', '#FFBB55', '#FF7777', '#FF3333',
              '#AA0000']
    plt.plot(x_axis, y_axis, linestyle='-', marker='o', markersize=3, markerfacecolor='white', markeredgewidth=0.5)
    ymin, ymax = plt.gca().get_ylim()
    bgcolor = plt.gca().get_facecolor()
    for i in range(1, 11):
        plt.axhspan(ends[i - 1], ends[i], facecolor=colors[i - 1], alpha=0.8, edgecolor=bgcolor, linewidth=0.5)
    locs, labels = plt.xticks()
    for loc in locs:
        plt.axvline(loc, color=bgcolor, linewidth=0.5)
    plt.ylim(min(1250, ymin - 100), max(ymax + 100, 1650))
    plt.legend(["%s (%d)" % (handle, y_axis[-1])], loc='upper left')

    filename = "%s.png" % str(ctx.message.id)
    plt.savefig(filename)
    with open(filename, 'rb') as file:
        discord_file = File(BytesIO(file.read()), filename='plot.png')
    os.remove(filename)
    plt.clf()
    plt.close()
    embed = Embed(title="Match rating for for %s" % handle, color=Color.blue())
    embed.set_image(url="attachment://plot.png")
    embed.set_footer(text="Requested by " + str(ctx.author), icon_url=ctx.author.avatar_url)
    await ctx.channel.send(embed=embed, file=discord_file)


async def get_time_response(client, ctx, message, time, author, range_):
    await ctx.send(message)

    def check(m):
        if not m.content.isdigit() or not m.author == author:
            return False
        i = m.content
        if int(i) < range_[0] or int(i) > range_[1]:
            return False
        return True
    try:
        msg = await client.wait_for('message', timeout=time, check=check)
        return [True, int(msg.content)]
    except asyncio.TimeoutError:
        return [False]


class Match(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.db = dbconn.DbConn()
        self.cf = cf_api.CodeforcesAPI()
        self.logger = logging.getLogger(self.__class__.__name__)

    @commands.group(
        brief=f'Commands related to matches. Type {PREFIX}match for more details', invoke_without_command=True)
    @commands.check(discord_.is_channel_allowed)
    async def match(self, ctx):
        await ctx.send(embed=discord_.make_command_help_embed(self.client, ctx, 'match'))

    @match.command(brief="Challenge someone to a match")
    async def challenge(self, ctx, member: discord.Member, rating: int):
        if member.id == ctx.author.id:
            await discord_.send_message(ctx, "You cannot challenge yourself!!")
            return
        if not self.db.get_handle(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, "Set your handle first before challenging someone")
            return
        if not self.db.get_handle(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"Handle for your opponent {member.mention} not set")
            return
        if self.db.is_challenging(ctx.guild.id, ctx.author.id) or self.db.is_challenged(
                ctx.guild.id, ctx.author.id) or self.db.in_a_match(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, "You are already challenging someone/being challenged/in a match. Pls try again later")
            return
        if self.db.is_challenging(ctx.guild.id, member.id) or self.db.is_challenged(
                ctx.guild.id, member.id) or self.db.in_a_match(ctx.guild.id, member.id):
            await discord_.send_message(ctx, "Your opponent is already challenging someone/being challenged/in a match. Pls try again later")
            return
        if rating not in range(LOWER_RATING, UPPER_RATING - 400 + 1):
            await discord_.send_message(ctx, f"Invalid Rating Range, enter an integer between {LOWER_RATING}-{UPPER_RATING-400}")
            return
        rating = rating - rating % 100
        resp = await get_time_response(self.client, ctx,
                                       f"{ctx.author.mention}, enter the duration of the match in minutes between {MATCH_DURATION}",
                                       RESPONSE_WAIT_TIME, ctx.author, MATCH_DURATION)
        if not resp[0]:
            await ctx.send(f"You took too long to decide! Match invalidated {ctx.author.mention}")
            return

        duration = resp[1]

        await ctx.send(f"{ctx.author.mention} has challenged {member.mention} to a match with problem ratings from "
                       f"{rating} to {rating+400} and lasting {duration} minutes. Type `{PREFIX}match accept` within 60 seconds to accept")
        tme = int(time.time())
        self.db.add_to_challenge(ctx.guild.id, ctx.author.id, member.id, rating, tme, ctx.channel.id, duration)
        await asyncio.sleep(60)
        if self.db.is_challenging(ctx.guild.id, ctx.author.id, tme):
            await ctx.send(f"{ctx.author.mention} your time to challenge {member.mention} has expired.")
            self.db.remove_challenge(ctx.guild.id, ctx.author.id)

    @match.command(brief="Withdraw your challenge")
    async def withdraw(self, ctx):
        if not self.db.is_challenging(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, "You are not challenging anyone")
            return
        self.db.remove_challenge(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Challenge by {ctx.author.mention} has been removed")

    @match.command(brief="Decline a challenge")
    async def decline(self, ctx):
        if not self.db.is_challenged(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, "No-one is challenging you")
            return
        self.db.remove_challenge(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Challenge to {ctx.author.mention} has been removed")

    @match.command(brief="Accept a challenge")
    async def accept(self, ctx):
        if not self.db.is_challenged(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, "No-one is challenging you")
            return
        embed = Embed(description=f"Preparing to start the match...", color=Color.green())
        embed.set_footer(text=f"You can now conduct tournaments using the bot.\n"
                              f"Type {PREFIX}tournament faq for more info")
        await ctx.send(embed=embed)

        data = self.db.get_challenge_info(ctx.guild.id, ctx.author.id)
        self.db.remove_challenge(ctx.guild.id, ctx.author.id)

        handle1, handle2 = self.db.get_handle(ctx.guild.id, data.p1_id), self.db.get_handle(ctx.guild.id, data.p2_id)
        problems = await codeforces.find_problems([handle1, handle2], [data.rating + i * 100 for i in range(0, 5)])

        if not problems[0]:
            await discord_.send_message(ctx, problems[1])
            return

        problems = problems[1]
        self.db.add_to_ongoing(data, int(time.time()), problems)

        match_info = self.db.get_match_info(ctx.guild.id, ctx.author.id)
        await ctx.send(embed=discord_.match_problems_embed(match_info))

    @match.command(brief="Invalidate a match (Admin/Mod/Lockout Manager only)")
    async def _invalidate(self, ctx, member: discord.Member):
        if not discord_.has_admin_privilege(ctx):
            await discord_.send_message(ctx, f"{ctx.author.mention} you require 'manage server' permission or one of the "
                                        f"following roles: {', '.join(ADMIN_PRIVILEGE_ROLES)} to use this command")
            return
        if not self.db.in_a_match(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"User {member.mention} is not in a match.")
            return
        self.db.delete_match(ctx.guild.id, member.id)
        await ctx.send(embed=discord.Embed(description="Match has been invalidated", color=discord.Color.green()))

    @match.command(brief="Invalidate your match", aliases=["forfeit", "cancel"])
    async def invalidate(self, ctx):
        if not self.db.in_a_match(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, f"User {ctx.author.mention} is not in a match.")
            return
        match_info = self.db.get_match_info(ctx.guild.id, ctx.author.id)
        opponent = await discord_.fetch_member(ctx.guild, match_info.p1_id if match_info.p1_id != ctx.author.id else match_info.p2_id)
        await ctx.send(f"{opponent.mention} you opponent {ctx.author.mention} has proposed to forfeit the match, type `yes` within 30 seconds to accept")

        try:
            message = await self.client.wait_for('message', timeout=30, check=lambda message: message.author == opponent and message.content.lower() == 'yes' and message.channel.id == ctx.channel.id)
            self.db.delete_match(ctx.guild.id, ctx.author.id)
            await ctx.send(embed=discord.Embed(description=f"{ctx.author.mention} {opponent.mention}, match has been invalidated", color=discord.Color.green()))
        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} your opponent didn't respond in time")

    @match.command(brief="Draw your current match")
    async def draw(self, ctx):
        if not self.db.in_a_match(ctx.guild.id, ctx.author.id):
            await discord_.send_message(ctx, f"User {ctx.author.mention} is not in a match.")
            return
        match = self.db.get_match_info(ctx.guild.id, ctx.author.id)
        opponent = await discord_.fetch_member(ctx.guild,
                                               match.p1_id if match.p1_id != ctx.author.id else match.p2_id)
        await ctx.send(
            f"{opponent.mention} you opponent {ctx.author.mention} has proposed to draw the match, type `yes` within 30 seconds to accept")

        try:
            message = await self.client.wait_for('message', timeout=30, check=lambda
                                                 message: message.author == opponent and message.content.lower() == 'yes' and message.channel.id == ctx.channel.id)
            channel = self.client.get_channel(match.channel)
            a, b = updation.match_score("00000")
            p1_rank, p2_rank = 1 if a >= b else 2, 1 if b >= a else 2
            ranklist = []
            ranklist.append([await discord_.fetch_member(ctx.guild, match.p1_id), p1_rank,
                             self.db.get_match_rating(ctx.guild.id, match.p1_id)[-1]])
            ranklist.append([await discord_.fetch_member(ctx.guild, match.p2_id), p2_rank,
                             self.db.get_match_rating(ctx.guild.id, match.p2_id)[-1]])
            ranklist = sorted(ranklist, key=itemgetter(1))
            res = elo.calculateChanges(ranklist)

            self.db.add_rating_update(ctx.guild.id, match.p1_id, res[match.p1_id][0])
            self.db.add_rating_update(ctx.guild.id, match.p2_id, res[match.p2_id][0])
            self.db.delete_match(match.guild, match.p1_id)
            self.db.add_to_finished(match, "00000")

            embed = discord.Embed(color=discord.Color.dark_magenta())
            pos, name, ratingChange = '', '', ''
            for user in ranklist:
                pos += f"{':first_place:' if user[1] == 1 else ':second_place:'}\n"
                name += f"{user[0].mention}\n"
                ratingChange += f"{res[user[0].id][0]} (**{'+' if res[user[0].id][1] >= 0 else ''}{res[user[0].id][1]}**)\n"
            embed.add_field(name="Position", value=pos)
            embed.add_field(name="User", value=name)
            embed.add_field(name="Rating changes", value=ratingChange)
            embed.set_author(name=f"Match over! Final standings\nScore: {a}-{b}")
            await channel.send(embed=embed)
        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} your opponent didn't respond in time")

    @match.command(brief="Display ongoing matches")
    async def ongoing(self, ctx):
        data = self.db.get_all_matches(ctx.guild.id)
        if len(data) == 0:
            await discord_.send_message(ctx, "No ongoing matches")
            return
        content = discord_.ongoing_matches_embed(data)

        currPage = 0
        totPage = math.ceil(len(content) / ONGOING_PER_PAGE)
        text = '\n'.join(content[currPage * ONGOING_PER_PAGE: min(len(content), (currPage + 1) * ONGOING_PER_PAGE)])
        embed = discord.Embed(description=text, color=discord.Color.gold())
        embed.set_author(name="Ongoing matches")
        embed.set_footer(text=f"Page {currPage+1} of {totPage}")
        message = await ctx.send(embed=embed)

        await message.add_reaction("⏮")
        await message.add_reaction("◀")
        await message.add_reaction("▶")
        await message.add_reaction("⏭")

        def check(reaction, user):
            return reaction.message.id == message.id and reaction.emoji in [
                "⏮", "◀", "▶", "⏭"] and user != self.client.user

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
                    content[currPage * ONGOING_PER_PAGE: min(len(content), (currPage + 1) * ONGOING_PER_PAGE)])
                embed = discord.Embed(description=text, color=discord.Color.gold())
                embed.set_author(name="Ongoing matches")
                embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
                await message.edit(embed=embed)

            except asyncio.TimeoutError:
                break

    @match.command(brief="Show recent matches")
    async def recent(self, ctx, member: discord.Member = None):
        data = self.db.get_recent_matches(ctx.guild.id, member.id if member else None)
        if len(data) == 0:
            await discord_.send_message(ctx, "No recent matches")
            return

        content = discord_.recent_matches_embed(data)

        currPage = 0
        totPage = math.ceil(len(content) / RECENT_PER_PAGE)
        text = '\n'.join(content[currPage * RECENT_PER_PAGE: min(len(content), (currPage + 1) * RECENT_PER_PAGE)])
        embed = discord.Embed(description=text, color=discord.Color.gold())
        embed.set_author(name="Finished matches")
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
                    content[currPage * RECENT_PER_PAGE: min(len(content), (currPage + 1) * RECENT_PER_PAGE)])
                embed = discord.Embed(description=text, color=discord.Color.gold())
                embed.set_author(name="Finished matches")
                embed.set_footer(text=f"Page {currPage + 1} of {totPage}")
                await message.edit(embed=embed)

            except asyncio.TimeoutError:
                break

    @match.command(brief="Show problems left from someone's ongoing match")
    async def problems(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author
        if not self.db.in_a_match(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"User {member.mention} is not in a match!")
            return
        await ctx.send(embed=discord_.match_problems_embed(self.db.get_match_info(ctx.guild.id, member.id)))

    @match.command(brief="Plot match rating")
    async def rating(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author
        data = self.db.get_match_rating(ctx.guild.id, member.id)
        if not self.db.get_handle(ctx.guild.id, member.id):
            await discord_.send_message(ctx, f"Handle for user {member.mention} not set")
            return
        if len(data) <= 1:
            await ctx.send(embed=discord.Embed(description=f"User {member.mention} is unrated! Compete in matches to become rated"))
            return
        await plot_graph(ctx, data[1:], self.db.get_handle(ctx.guild.id, member.id))

    @match.command(brief="Show match ratings of all the users")
    async def ranklist(self, ctx):
        res = self.db.get_ranklist(ctx.guild.id)
        if len(res) == 0:
            await discord_.send_message(ctx, "No user has played a match so far")
            return
        res = sorted(res, key=itemgetter(1), reverse=True)
        data = []
        for x in res:
            try:
                data.append([(await discord_.fetch_member(ctx.guild, x[0])).name, str(x[1])])
            except Exception:
                pass
        await paginator.Paginator(data, ["User", "Rating"], f"Match Ratings", 10).paginate(ctx, self.client)


def setup(client):
    client.add_cog(Match(client))
