import re
from pathlib import Path

import pytest
from bonbon.handlers.migrate import migration_files
from bonbon.receipts import categories

# A small rule set that mirrors the shape of migration 0006, longest keyword first (as _rules()
# returns it), so the tests don't depend on the real database.
RULES = sorted(
    [
        ("vollmilch", "Milchprodukte & Eier"),
        ("milch", "Milchprodukte & Eier"),
        ("apfel", "Früchte & Gemüse"),
        ("brot", "Brot & Backwaren"),
    ],
    key=lambda kv: -len(kv[0]),
)


@pytest.fixture(autouse=True)
def rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fixed rules so categorize() never touches the database."""
    monkeypatch.setattr(categories, "_rules", lambda: RULES)


def test_matches_keyword_anywhere_in_the_name() -> None:
    assert categories.categorize("Bio Apfel Gala") == "Früchte & Gemüse"
    assert categories.categorize("Ruchbrot 500g") == "Brot & Backwaren"


def test_matching_is_case_insensitive() -> None:
    assert categories.categorize("APFEL") == "Früchte & Gemüse"
    assert categories.categorize("MILCH DRINK") == "Milchprodukte & Eier"


def test_longer_keyword_wins_over_shorter_one() -> None:
    # Both 'vollmilch' and 'milch' match; the more specific rule must win.
    assert categories.categorize("Vollmilch UHT") == "Milchprodukte & Eier"


def test_no_match_falls_back_to_sonstiges() -> None:
    assert categories.categorize("Batterien AA") == categories.DEFAULT_CATEGORY
    assert categories.categorize("") == categories.DEFAULT_CATEGORY


def test_default_category_is_seeded() -> None:
    """categorize() returns 'Sonstiges' for no match; migration 0002 must create that row."""
    seed = (Path(migration_files()[1])).read_text()
    assert "INSERT INTO categories (name) VALUES ('Sonstiges')" in seed


# --- Migration 0006 consistency (no database needed) -------------------------------------------


def _migration_0006() -> str:
    [path] = [p for p in migration_files() if p.name.startswith("0006")]
    return path.read_text()


def test_every_rule_references_a_seeded_category() -> None:
    """Each category_rules row joins categories by name; a typo would silently drop the rule."""
    sql = _migration_0006()
    seeded = set(re.findall(r"\('([^']+)'\)(?:,|\s*ON CONFLICT)", _categories_block(sql)))
    used = set(re.findall(r"'[^']+',\s*'([^']+)'\)", _rules_block(sql)))
    assert used, "no keyword rules found in migration 0006"
    assert used <= seeded, f"rules reference categories that are not seeded: {used - seeded}"


def test_keywords_are_unique() -> None:
    """category_rules.keyword is UNIQUE; a repeat would make the seed fail on a real database."""
    keywords = re.findall(r"\(\s*'([^']+)',\s*'[^']+'\)", _rules_block(_migration_0006()))
    assert keywords, "no keywords found in migration 0006"
    duplicates = {k for k in keywords if keywords.count(k) > 1}
    assert not duplicates, f"duplicate keywords in migration 0006: {duplicates}"


def _categories_block(sql: str) -> str:
    """The INSERT INTO categories ... VALUES (...) statement."""
    match = re.search(r"INSERT INTO categories.*?;", sql, re.DOTALL)
    assert match, "no categories INSERT in migration 0006"
    return match.group(0)


def _rules_block(sql: str) -> str:
    """The VALUES block of the INSERT INTO category_rules statement."""
    match = re.search(r"INSERT INTO category_rules.*?;", sql, re.DOTALL)
    assert match, "no category_rules INSERT in migration 0006"
    return match.group(0)
