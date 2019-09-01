-- Copyright © 2019 lambda#0987
--
-- Cautious Memory is free software: you can redistribute it and/or modify
-- it under the terms of the GNU Affero General Public License as published
-- by the Free Software Foundation, either version 3 of the License, or
-- (at your option) any later version.
--
-- Cautious Memory is distributed in the hope that it will be useful,
-- but WITHOUT ANY WARRANTY; without even the implied warranty of
-- MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
-- GNU Affero General Public License for more details.
--
-- You should have received a copy of the GNU Affero General Public License
-- along with Cautious Memory.  If not, see <https://www.gnu.org/licenses/>.

CREATE FUNCTION coalesce_agg_statefunc(state anyelement, value anyelement) RETURNS anyelement AS $$
	SELECT coalesce(value, state); $$
LANGUAGE SQL;

CREATE AGGREGATE coalesce_agg(anyelement) (
	SFUNC = coalesce_agg_statefunc,
	STYPE = anyelement);
