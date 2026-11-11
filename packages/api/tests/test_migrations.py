import re

from bonbon.handlers.migrate import migration_files


def test_migrations_are_numbered_without_gaps() -> None:
    """Files run in name order and are recorded by name, so numbering must be strict."""
    files = migration_files()
    assert files, "no migrations found; are they still in src/bonbon/migrations/?"
    for number, path in enumerate(files, start=1):
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", path.name), path.name
        assert int(path.name[:4]) == number, f"{path.name}: expected number {number:04d}"


def test_migrations_do_not_control_transactions() -> None:
    """migrate.py wraps each file in a transaction; a COMMIT inside would break that."""
    for path in migration_files():
        sql = re.sub(r"--.*", "", path.read_text()).upper()
        assert not re.search(r"\b(BEGIN|COMMIT|ROLLBACK)\b", sql), path.name
