# encoding: utf-8

# Copyright © 2019 lambda#0987
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncpg

from utils import errors

class Database:
	def __init__(self, bot):
		self.bot = bot

	async def get_page(self, guild_id, title):
		row = await self.bot.pool.fetchrow("""
			SELECT *
			FROM pages
			INNER JOIN revisions
			ON pages.latest_revision = revisions.id
			WHERE guild = $1
			AND title = $2
		""", guild_id, title)
		if row is None:
			raise errors.PageNotFoundError(title)

		return row

	async def get_page_revisions(self, guild_id, title):
		return await self.bot.pool.fetch("""
			SELECT *
			FROM pages
			LEFT JOIN revisions
			ON pages.id = revisions.page_id
			WHERE guild = $1
			AND title = $2
			ORDER BY revisions.id DESC
		""", guild_id, title)

	async def create_page(self, title, content, *, guild_id, author_id):
		"""creates a new page

		- locked: whether to restrict editing this page to moderators
		"""

		async with self.bot.pool.acquire() as conn:
			tr = conn.transaction()
			await tr.start()

			try:
				page_id = await conn.fetchval("""
					INSERT INTO pages (title, guild, latest_revision)
					VALUES ($1, $2, 0)  -- revision = 0 until we have a revision ID
					RETURNING id
				""", title, guild_id)
			except asyncpg.UniqueViolationError:
				await tr.rollback()
				raise errors.PageExistsError

			try:
				await self._create_revision(conn, page_id, content, author_id)
			except:
				await tr.rollback()
				raise

			await tr.commit()

	async def revise_page(self, title, new_content, *, guild_id, author_id):
		async with self.bot.pool.acquire() as conn, conn.transaction():
			page_id = await conn.fetchval("""
				SELECT id
				FROM pages
				WHERE title = $1
				AND guild = $2
			""", title, guild_id)
			if page_id is None:
				raise errors.PageNotFoundError

			await self._create_revision(conn, page_id, new_content, author_id)

	async def _create_revision(self, connection, page_id, content, author_id):
		await connection.execute("""
			WITH revision AS (
				INSERT INTO revisions (page_id, author, content)
				VALUES ($1, $2, $3)
				RETURNING id
			)
			UPDATE pages
			SET latest_revision = (SELECT id FROM revision)
			WHERE id = $1
		""", page_id, author_id, content)

def setup(bot):
	bot.add_cog(Database(bot))
