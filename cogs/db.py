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

import datetime
import enum
import operator
import typing

import asyncpg
import discord
from discord.ext import commands

from utils import attrdict, errors

class Permissions(enum.Flag):
	none = 0
	view = enum.auto()
	rename = enum.auto()
	edit = enum.auto()
	delete = enum.auto()
	manage_permissions = enum.auto()
	default = view | rename | edit

class Database(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	## Pages

	async def get_page(self, guild_id, title):
		row = await self.bot.pool.fetchrow("""
			SELECT *
			FROM
				pages
				INNER JOIN revisions
					ON pages.latest_revision = revisions.revision_id
			WHERE
				guild = $1
				AND LOWER(title) = LOWER($2)
		""", guild_id, title)
		if row is None:
			raise errors.PageNotFoundError(title)

		return attrdict(row)

	async def get_page_revisions(self, guild_id, title):
		async for row in self.cursor("""
			SELECT *
			FROM pages INNER JOIN revisions USING (page_id)
			WHERE
				guild = $1
				AND LOWER(title) = LOWER($2)
			ORDER BY revision_id DESC
		""", guild_id, title):
			yield row

	async def get_all_pages(self, guild_id):
		"""return an async iterator over all pages for the given guild"""
		async for row in self.cursor("""
			SELECT *
			FROM
				pages
				INNER JOIN revisions
					ON pages.latest_revision = revisions.revision_id
			WHERE guild = $1
			ORDER BY LOWER(title) ASC
		""", guild_id):
			yield row

	async def get_recent_revisions(self, guild_id, cutoff: datetime.datetime):
		"""return an async iterator over recent (after cutoff) revisions for the given guild, sorted by time"""
		async for row in self.cursor("""
			SELECT title, revision_id, page_id, author, revised
			FROM revisions INNER JOIN pages USING (page_id)
			WHERE guild = $1 AND revised > $2
			ORDER BY revised DESC
		""", guild_id, cutoff):
			yield row

	async def search_pages(self, guild_id, query):
		"""return an async iterator over all pages whose title is similar to query"""
		async for row in self.cursor("""
			SELECT *
			FROM
				pages
				INNER JOIN revisions
					ON pages.latest_revision = revisions.revision_id
			WHERE
				guild = $1
				AND title % $2
			ORDER BY similarity(title, $2) DESC
			LIMIT 100
		""", guild_id, query):
			yield row

	async def cursor(self, query, *args):
		"""return an async iterator over all rows matched by query and args. Lazy equivalent to fetch()"""
		async with self.bot.pool.acquire() as conn, conn.transaction():
			async for row in conn.cursor(query, *args):
				yield attrdict(row)

	async def get_individual_revisions(self, guild_id, revision_ids):
		"""return a list of page revisions for the given guild.
		the revisions are sorted by their revision ID.
		"""
		results = list(map(attrdict, await self.bot.pool.fetch("""
			SELECT *
			FROM pages INNER JOIN revisions USING (page_id)
			WHERE
				guild = $1
				AND revision_id = ANY ($2)
			ORDER BY revision_id ASC  -- usually this is used for diffs so we want oldest-newest
		""", guild_id, revision_ids)))

		if len(results) != len(set(revision_ids)):
			raise ValueError('one or more revision IDs not found')

		return results

	async def create_page(self, title, content, *, guild_id, author_id):
		async with self.bot.pool.acquire() as conn:
			tr = conn.transaction()
			await tr.start()

			try:
				page_id = await conn.fetchval("""
					INSERT INTO pages (title, guild, latest_revision)
					VALUES ($1, $2, 0)  -- revision = 0 until we have a revision ID
					RETURNING page_id
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
				SELECT page_id
				FROM pages
				WHERE
					LOWER(title) = LOWER($1)
					AND guild = $2
			""", title, guild_id)
			if page_id is None:
				raise errors.PageNotFoundError(title)

			await self._create_revision(conn, page_id, new_content, author_id)

	async def rename_page(self, guild_id, title, new_title):
		try:
			command_tag = await self.bot.pool.execute("""
				UPDATE pages
				SET title = $3
				WHERE
					LOWER(title) = LOWER($2)
					AND guild = $1
			""", guild_id, title, new_title)
		except asyncpg.UniqueViolationError:
			raise errors.PageExistsError

		# UPDATE 1 -> 1
		rows_updated = int(command_tag.split()[1])
		if not rows_updated:
			raise errors.PageNotFoundError(title)

	async def _create_revision(self, connection, page_id, content, author_id):
		await connection.execute("""
			WITH revision AS (
				INSERT INTO revisions (page_id, author, content)
				VALUES ($1, $2, $3)
				RETURNING revision_id
			)
			UPDATE pages
			SET latest_revision = (SELECT * FROM revision)
			WHERE page_id = $1
		""", page_id, author_id, content)

	## Permissions

	async def permissions_for(self, member: discord.Member, title):
		roles = list(map(operator.attrgetter('id'), member.roles)) + [member.guild.id]
		perms = await self.bot.pool.fetchval("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			SELECT bit_or(permissions) | bit_or(allow) & ~bit_or(deny)
			FROM role_permissions LEFT JOIN page_permissions USING (role)
			WHERE
				role = ANY ($3)
				AND page_id = (SELECT * FROM page_id)
				OR page_id IS NULL  -- in case there's no page permissions for some role
		""", member.guild.id, title, roles)
		if perms is None:
			return Permissions.default
		return Permissions(perms)

	async def get_role_permissions(self, role_id):
		perms = await self.bot.pool.fetchval('SELECT permissions FROM role_permissions WHERE role = $1', role_id)
		if perms is None:
			return Permissions.default
		return Permissions(perms)

	async def set_role_permissions(self, role_id, permissions: Permissions):
		await self.bot.pool.execute("""
			INSERT INTO role_permissions(role, permissions)
			VALUES ($1, $2)
			ON CONFLICT (role) DO UPDATE SET
				permissions = EXCLUDED.permissions
		""", role_id, permissions.value)

	# no unset_role_permissions because unset means to give the default permissions
	# to deny all perms just use deny_role_permissions

	async def allow_role_permissions(self, role_id, new_perms: Permissions):
		await self.bot.pool.execute("""
			INSERT INTO role_permissions(role, permissions)
			VALUES ($1, $3)
			ON CONFLICT (role) DO UPDATE SET
				permissions = role_permissions.permissions | $2
		""", role_id, new_perms.value, (new_perms | Permissions.default).value)

	async def deny_role_permissions(self, role_id, perms):
		"""revoke a set of permissions from a role"""
		await self.bot.pool.execute("""
			UPDATE role_permissions
			SET permissions = role_permissions.permissions & ~$2::INTEGER
			WHERE role = $1
		""", role_id, perms.value)

	async def get_page_overwrites(self, guild_id, title) -> typing.List[typing.Tuple[Permissions, Permissions]]:
		"""get the allowed and denied permissions for a particular page"""
		return list(map(lambda row: tuple(map(Permissions, row)), await self.bot.pool.fetch("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			SELECT allow, deny
			FROM page_permissions
			WHERE page_id = (SELECT * FROM page_id)
		""", guild_id, title)))

	async def set_page_overwrites(
		self,
		guild_id,
		title,
		role_id,
		allow_perms: Permissions = Permissions.none,
		deny_perms: Permissions = Permissions.none
	):
		"""set the allowed, denied, or both permissions for a particular page and role"""
		await self.bot.pool.execute("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			INSERT INTO page_permissions (page_id, role, allow, deny)
			VALUES ((SELECT * FROM page_id), $3, $4, $5)
			ON CONFLICT (page_id, role) DO UPDATE SET
				allow = EXCLUDED.allow,
				deny = EXCLUDED.deny
		""", guild_id, title, role_id, allow_perms.value, deny_perms.value)

	async def unset_page_overwrites(self, guild_id, title, role_id):
		"""remove all of the allowed and denied overwrites for a page"""
		await self.bot.pool.execute("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			DELETE FROM page_permissions
			WHERE page_id = (SELECT * FROM page_id)
		""")

	async def add_page_permissions(
		self,
		guild_id,
		title,
		role_id,
		new_allow_perms: Permissions = Permissions.none,
		new_deny_perms: Permissions = Permissions.none
	):
		"""add permissions to the set of "allow" overwrites for a page"""
		await self.bot.pool.execute("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			INSERT INTO page_permissions (page_id, role, allow, deny)
			VALUES ((SELECT * FROM page_id), $3, $4, $5)
			ON CONFLICT (page_id, role) DO UPDATE SET
				allow = page_permissions.allow | EXCLUDED.allow,
				deny = page_permissions.deny | EXCLUDED.deny
		""", guild_id, title, role_id, new_allow_perms.value, new_deny_perms.value)

	async def unset_page_permissions(self, guild_id, title, role_id, perms):
		"""remove a permission from either the allow or deny overwrites for a page

		This is equivalent to the "grey check" in Discord's UI.
		"""
		await self.bot.pool.execute("""
			WITH page_id AS (SELECT page_id FROM pages WHERE guild = $1 AND LOWER(title) = LOWER($2))
			UPDATE page_permissions SET
				allow = allow & ~$3::INTEGER,
				deny = deny & ~$3::INTEGER
		""", guild_id, title, perms.value)

def setup(bot):
	bot.add_cog(Database(bot))
