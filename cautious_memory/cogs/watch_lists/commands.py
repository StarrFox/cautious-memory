# Copyright © 2019 lambda#0987
#
# Cautious Memory is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Cautious Memory is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Cautious Memory.  If not, see <https://www.gnu.org/licenses/>.

from bot_bin.sql import connection, optional_connection
from discord.ext import commands

from ...utils.paginator import Pages

clean_content = commands.clean_content(use_nicknames=False)

class WatchLists(commands.Cog, name='Watch Lists'):
	def __init__(self, bot):
		self.bot = bot
		self.db = self.bot.cogs['WatchListsDatabase']
		self.wiki_db = self.bot.cogs['WikiDatabase']

	def cog_check(self, ctx):
		if not ctx.guild:
			raise commands.NoPrivateMessage
		return True

	@commands.command()
	async def watch(self, ctx, *, title: clean_content):
		"""Adds a page to your watch list. You will be notified when it's edited."""
		await self.db.watch_page(ctx.author, title)
		await ctx.message.add_reaction(self.bot.config['success_emojis'][True])

	@commands.command()
	@optional_connection
	async def unwatch(self, ctx, *, title: clean_content):
		"""Removes a page from your watch list."""
		async with connection().transaction():
			await self.wiki_db.get_page(ctx.author, title, partial=True, check_permissions=False)
			await self.db.unwatch_page(ctx.author, title)
		await ctx.message.add_reaction(self.bot.config['success_emojis'][True])

	@commands.command(name='watch-list', aliases=['watchlist'])
	async def watch_list(self, ctx):
		"""Shows your watch list."""
		entries = [title async for page_id, title in self.db.watch_list(ctx.author)]
		if not entries:
			await ctx.send(f'You are not watching any pages. Use the {ctx.prefix}watch command to do so.')
			return
		await Pages(ctx, entries=entries).begin()

def setup(bot):
	bot.add_cog(WatchLists(bot))
