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

import inspect
import math
import re

import aiocontextvars
import discord

connection = aiocontextvars.ContextVar('connection')

attrdict = type('attrdict', (dict,), {
	'__getattr__': dict.__getitem__,
	'__setattr__': dict.__setitem__,
	'__delattr__': dict.__delitem__})

def escape_code_blocks(s):
	return s.replace('`', '`\N{zero width non-joiner}')

def format_datetime(d) -> str:
	return d.strftime("%Y-%m-%d %I:%M:%S %p UTC")

def code_block(s, *, language=''):
	return f'```{language}\n{s}\n```'

def convert_emoji(s) -> discord.PartialEmoji:
	match = re.search(r'<?(a?):([A-Za-z0-9_]+):([0-9]{17,})>?', s)
	if match:
		return discord.PartialEmoji(animated=match[1], name=match[2], id=int(match[3]))
	return discord.PartialEmoji(animated=None, name=s, id=None)

# this function is Public Domain
# https://creativecommons.org/publicdomain/zero/1.0/
def load_sql(fp):
	"""given a file-like object, read the queries delimited by `-- :name foo` comment lines
	return a dict mapping these names to their respective SQL queries
	the file-like is not closed afterwards.
	"""
	# tag -> list[lines]
	queries = attrdict()
	current_tag = ''

	for line in fp:
		match = re.match(r'\s*--\s*:name\s*(\S+).*?$', line)
		if match:
			current_tag = match[1]
			continue
		if current_tag:
			queries.setdefault(current_tag, []).append(line)

	for tag, query in queries.items():
		queries[tag] = ''.join(query)

	return queries

def bytes_to_int(x):
	return int.from_bytes(x, byteorder='big')

def int_to_bytes(n):
	num_bytes = int(math.ceil(n.bit_length() / 8))
	return n.to_bytes(num_bytes, byteorder='big')

def optional_connection(func):
	"""Decorator that acquires a connection for the decorated function if the contextvar is not set."""
	# XXX idk how to avoid duplicating this code
	if inspect.isasyncgenfunction(func):
		async def inner(self, *args, **kwargs):
			try:
				connection.get()
			except LookupError:
				async with self.bot.pool.acquire() as conn:
					connection.set(conn)
					# XXX this doesn't handle two-way generators
					# but I don't have any of those anyway.
					# If I add one, make sure to use async_generator.yield_from_ here
					async for x in func(self, *args, **kwargs):
						yield x
			else:
				async for x in func(self, *args, **kwargs):
					yield x
	else:
		async def inner(self, *args, **kwargs):
			try:
				connection.get()
			except LookupError:
				async with self.bot.pool.acquire() as conn:
					connection.set(conn)
					return await func(self, *args, **kwargs)
			else:
				return await func(self, *args, **kwargs)

	return inner