"""Assign a category to a receipt item from the keyword rule table (issue #23).

The database worker (ProcessResultFunction, inside the VPC) calls categorize() for every item
it writes. A rule maps a lowercase keyword to a category; an item that matches no keyword gets
'Sonstiges'.

When several keywords match, the one whose match *ends furthest right* in the item name wins,
ties broken by the longer keyword. German compounds put the head noun last ('Apfelsaft' is a
juice, 'Erdbeerjoghurt' a yoghurt), so the rightmost match is the right category; a plain
"longest wins" would file both under the left part ('Apfel', 'Erdbeer').

The rules are seeded by migration 0006 and change rarely, so they are loaded once per Lambda
container and cached.
"""

from functools import cache

from bonbon import db

# Every item that matches no rule falls back to this category (seeded in migration 0002).
DEFAULT_CATEGORY = "Sonstiges"


@cache
def _rules() -> list[tuple[str, str]]:
    """(keyword, category_name) pairs; loaded once per container."""
    rows = db.query(
        "SELECT r.keyword, c.name FROM category_rules r JOIN categories c ON c.id = r.category_id"
    )
    return [(keyword, name) for keyword, name in rows]


def reset() -> None:
    """Forget the cached rules (used by tests; a container reload would do the same)."""
    _rules.cache_clear()


def categorize(item_name: str) -> str:
    """Category name for one item; DEFAULT_CATEGORY if no keyword matches.

    The match ending furthest right wins (head noun of a German compound), ties broken by the
    longer keyword.
    """
    name = item_name.casefold()
    best: tuple[int, int] | None = None
    best_category = DEFAULT_CATEGORY
    for keyword, category in _rules():
        start = name.rfind(keyword)  # last occurrence, so the match ends as far right as possible
        if start == -1:
            continue
        rank = (start + len(keyword), len(keyword))  # end position, then keyword length
        if best is None or rank > best:
            best, best_category = rank, category
    return best_category
