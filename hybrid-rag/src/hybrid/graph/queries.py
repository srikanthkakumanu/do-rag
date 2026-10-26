"""Read-only Cypher templates. The ONLY Cypher the query path may run; values are
parameters, never interpolated. Every template filters to facts current on `$as_of`."""

from __future__ import annotations

from typing import Final, LiteralString

_RETURN: Final = """
RETURN coalesce(rc.network, '') AS network, rc.code AS code, type(r) AS kind,
       properties(t) AS target, r.doc_id AS doc_id, r.section_path AS section_path,
       r.effective_date AS effective_date, r.quote AS quote
ORDER BY network, code, kind
LIMIT $limit
"""
_CURRENT: Final = "r.effective_date <= $as_of AND r.superseded_on > $as_of"
_TYPES: Final = "HAS_DEADLINE|REMEDIED_BY|NOT_SUFFICIENT|IN_CATEGORY"

FACTS_FOR_CODES: Final[LiteralString] = (
    f"MATCH (rc:ReasonCode)-[r:{_TYPES}]->(t) "
    f"WHERE rc.code IN $codes AND type(r) IN $kinds AND {_CURRENT}" + _RETURN
)
FACTS_FOR_NETWORKS: Final[LiteralString] = (
    f"MATCH (rc:ReasonCode)-[r:{_TYPES}]->(t) "
    f"WHERE rc.network IN $networks AND type(r) IN $kinds AND {_CURRENT}" + _RETURN
)
CODES_BY_DEADLINE: Final[LiteralString] = (
    "MATCH (rc:ReasonCode)-[r:HAS_DEADLINE]->(t:Deadline) "
    f"WHERE t.days = $days AND ($networks = [] OR rc.network IN $networks) AND {_CURRENT}" + _RETURN
)
CODES_BY_CATEGORY: Final[LiteralString] = (
    "MATCH (rc:ReasonCode)-[r:IN_CATEGORY]->(t:Category {name: $category}) "
    f"WHERE ($networks = [] OR rc.network IN $networks) AND {_CURRENT}" + _RETURN
)
