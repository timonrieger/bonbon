"""Assign a category to a receipt item from the keyword rule table (issue #23).

The database worker (ProcessResultFunction, inside the VPC) calls categorize() for every item
it writes. A rule maps a lowercase keyword to a category; the first keyword that appears in the
lowercased item name wins. An item that matches no keyword gets 'Sonstiges'.

The rules are seeded by migration 0006 and change rarely, so they are loaded once per Lambda
container and cached. Longer keywords are tried first, so a specific rule ('vollmilch') beats a
shorter one ('milch') when both would match.
"""

from functools import cache

from bonbon import db

# Every item that matches no rule falls back to this category (seeded in migration 0002).
DEFAULT_CATEGORY = "Sonstiges"


@cache
def _rules() -> list[tuple[str, str]]:
    """(keyword, category_name) pairs, longest keyword first; loaded once per container."""
    rows = db.query(
        "SELECT r.keyword, c.name FROM category_rules r JOIN categories c ON c.id = r.category_id"
    )
    return sorted(((keyword, name) for keyword, name in rows), key=lambda kv: -len(kv[0]))


def reset() -> None:
    """Forget the cached rules (used by tests; a container reload would do the same)."""
    _rules.cache_clear()


def categorize(item_name: str) -> str:
    """Category name for one item; DEFAULT_CATEGORY if no keyword matches."""
    name = item_name.casefold()
    for keyword, category in _rules():
        if keyword in name:
            return category
    return DEFAULT_CATEGORY
