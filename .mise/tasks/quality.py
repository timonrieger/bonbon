#!/usr/bin/env -S uv run --script
# [MISE] description="Measure item recognition quality on the test receipts (#24)"
# [MISE] dir="{{ config_root }}/packages/api"
# /// script
# requires-python = ">=3.14"
# dependencies = ["pg8000"]
# ///

"""Recognition-quality harness for the ~20 real receipts (issue #24).

For every receipt it runs the real pipeline functions — parse_expense() and the categorize()
rules — against a human-written ground truth and reports, per store, how many items are
recognized correctly (target >= 90 %), plus the typical errors for the report.

An item counts as correct when parse_expense() reads a usable name AND categorize() returns the
expected category. Store, date and total are reported separately. Per issue #24 and Timon's note,
the total is NOT scored against the sum of items (discounts, Cumulus, Pfand and rounding make
them differ legitimately).

Inputs live in tests/data/:
  <name>.json            the raw Textract AnalyzeExpense response
  <name>.expected.json   ground truth: store, purchase_date, total_rappen, items[{name, category}]

It uses the worker's own categorize() (so it can't drift from the deployed behavior) with the
rules read from the migration files, and parse_expense() on the stored Textract JSON. Importing
bonbon.receipts.categories pulls in bonbon.db, hence pg8000 as a script dependency; no database
connection is opened (categorize() is called with explicit rules). Run it after adding receipts
or changing the rules.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "packages" / "api"
DATA = API / "tests" / "data"
sys.path.insert(0, str(API / "src"))

from bonbon.receipts.categories import categorize  # noqa: E402
from bonbon.receipts.expense import parse_expense  # noqa: E402

TARGET = 0.90


def load_seed_rules() -> list[tuple[str, str]]:
    """(keyword, category) pairs from every migration that seeds category_rules.

    Reads all INSERT INTO category_rules statements across the migration files (0006 seeds them,
    0007+ tune them), so the harness categorizes exactly like the deployed worker.
    """
    migrations = sorted((API / "src" / "bonbon" / "migrations").glob("*.sql"))
    rules: list[tuple[str, str]] = []
    for path in migrations:
        for block in re.findall(r"INSERT INTO category_rules.*?;", path.read_text(), re.DOTALL):
            rules += re.findall(r"\(\s*'([^']+)',\s*'([^']+)'\)", block)
    assert rules, "no category_rules INSERT found in any migration"
    return rules


@dataclass
class ItemError:
    store: str
    name: str
    got: str
    expected: str


def main() -> int:
    # The seeded rules, straight from the migrations (same set the deployed worker loads from DB).
    rules = load_seed_rules()

    expected_files = sorted(DATA.glob("*.expected.json"))
    if not expected_files:
        sys.exit(
            "No ground-truth files in tests/data/ yet. Add <name>.json (Textract output) and a"
            " <name>.expected.json next to it (see tests/data/textract_migros.expected.json)."
        )

    per_store_correct: dict[str, int] = {}
    per_store_total: dict[str, int] = {}
    errors: list[ItemError] = []
    store_hits = date_hits = total_hits = header_count = 0

    for expected_path in expected_files:
        raw_name = expected_path.name.replace(".expected.json", ".json")
        raw_path = expected_path.with_name(raw_name)
        if not raw_path.exists():
            # The Textract mock fixture lives under src/ so the Lambda packages it (#35), not
            # next to its ground truth; fall back to there before giving up.
            packaged = API / "src" / "bonbon" / "receipts" / "mock_data" / raw_name
            if packaged.exists():
                raw_path = packaged
            else:
                sys.exit(f"{expected_path.name} has no matching Textract file {raw_name}")

        expected = json.loads(expected_path.read_text())
        receipt = parse_expense(json.loads(raw_path.read_text()))
        store = expected.get("store") or "Unbekannt"

        # Header fields (reported, not part of the item score).
        header_count += 1
        store_hits += receipt.store == expected.get("store")
        got_date = receipt.purchase_date.isoformat() if receipt.purchase_date else None
        date_hits += got_date == expected.get("purchase_date")
        total_hits += receipt.total_rappen == expected.get("total_rappen")

        # Items: match by name, not by position, so one missing or extra item doesn't shift
        # every item after it. A parsed item is consumed once it matches, so a name that appears
        # twice on the receipt (e.g. 'Poulet Schnitzel') needs two parsed copies to score twice.
        exp_items = expected.get("items", [])
        remaining = list(receipt.items)
        per_store_total[store] = per_store_total.get(store, 0) + len(exp_items)
        per_store_correct.setdefault(store, 0)

        for want in exp_items:
            match = next((it for it in remaining if it.name == want["name"]), None)
            if match is None:
                errors.append(ItemError(store, want["name"], "<not read>", want["category"]))
                continue
            remaining.remove(match)
            got_cat = categorize(match.name, rules)
            if got_cat == want["category"]:
                per_store_correct[store] += 1
            else:
                errors.append(ItemError(store, want["name"], got_cat, want["category"]))

        for extra in remaining:
            errors.append(ItemError(store, extra.name, "<extra, not in ground truth>", "—"))

    _report(
        per_store_correct,
        per_store_total,
        errors,
        header_count,
        store_hits,
        date_hits,
        total_hits,
    )

    overall_total = sum(per_store_total.values())
    overall_correct = sum(per_store_correct.values())
    rate = overall_correct / overall_total if overall_total else 0.0
    return 0 if rate >= TARGET else 1


def _report(correct, total, errors, n, store_hits, date_hits, total_hits) -> None:
    print("=" * 64)
    print(f"Recognition quality — {n} receipt(s), target {TARGET:.0%} of items per store")
    print("=" * 64)
    print(f"Header   store {store_hits}/{n}   date {date_hits}/{n}   total {total_hits}/{n}")
    print("-" * 64)
    for store in sorted(total):
        c, t = correct[store], total[store]
        rate = c / t if t else 0.0
        flag = "OK " if rate >= TARGET else "LOW"
        print(f"[{flag}] {store:24} {c:3}/{t:<3}  {rate:6.1%}")
    overall_t = sum(total.values())
    overall_c = sum(correct.values())
    overall = overall_c / overall_t if overall_t else 0.0
    print("-" * 64)
    print(f"      {'OVERALL':24} {overall_c:3}/{overall_t:<3}  {overall:6.1%}")

    if errors:
        print("Misrecognized items (ground-truth category -> what the worker produced):")
        for e in errors:
            print(f"  [{e.store}] {e.name[:38]:38} expected {e.expected!r}, got {e.got!r}")


if __name__ == "__main__":
    raise SystemExit(main())
