import re

import pytest
from bonbon.handlers.migrate import migration_files
from bonbon.receipts import categories

# A small rule set that mirrors the shape of migration 0006, so the tests don't depend on the
# real database. The order is irrelevant: categorize() picks the match ending furthest right.
RULES = [
    ("apfel", "Früchte & Gemüse"),
    ("erdbeer", "Früchte & Gemüse"),
    ("paprika", "Früchte & Gemüse"),
    ("milch", "Milchprodukte & Eier"),
    ("vollmilch", "Milchprodukte & Eier"),
    ("joghurt", "Milchprodukte & Eier"),
    ("brot", "Brot & Backwaren"),
    ("saft", "Getränke"),
    ("cola", "Getränke"),
    ("tee", "Getränke"),
    ("chips", "Süsswaren & Snacks"),
    ("chocolat", "Süsswaren & Snacks"),
    ("teelicht", "Haushalt & Reinigung"),
]


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


def test_rightmost_match_wins_for_german_compounds() -> None:
    # The head noun of a compound is the last part, so the match ending furthest right wins:
    # a juice/yoghurt/snack, not a fruit.
    assert categories.categorize("Apfelsaft") == "Getränke"
    assert categories.categorize("Orangensaft") == "Getränke"
    assert categories.categorize("Kartoffelchips") == "Süsswaren & Snacks"
    assert categories.categorize("Paprika Wave Chips") == "Süsswaren & Snacks"
    assert categories.categorize("Erdbeerjoghurt") == "Milchprodukte & Eier"
    assert categories.categorize("Migros Erdbeer-Milch") == "Milchprodukte & Eier"


def test_longer_keyword_wins_on_a_tie() -> None:
    # 'vollmilch' and 'milch' end at the same position; the longer keyword breaks the tie.
    assert categories.categorize("Vollmilch UHT") == "Milchprodukte & Eier"


def test_short_keyword_does_not_hijack_a_longer_word() -> None:
    # 'cola' is inside 'Chocolat' and 'tee' inside 'Teelichter', but a more specific keyword
    # ends further right and wins.
    assert categories.categorize("Chocolat Frey") == "Süsswaren & Snacks"
    assert categories.categorize("Teelichter 50 Stk") == "Haushalt & Reinigung"


def test_no_match_falls_back_to_sonstiges() -> None:
    assert categories.categorize("Batterien AA") == categories.DEFAULT_CATEGORY
    assert categories.categorize("") == categories.DEFAULT_CATEGORY


def test_default_category_is_seeded() -> None:
    """categorize() returns 'Sonstiges' for no match; migration 0002 must create that row."""
    [path] = [p for p in migration_files() if p.name.startswith("0002")]
    assert "INSERT INTO categories (name) VALUES ('Sonstiges')" in path.read_text()


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
