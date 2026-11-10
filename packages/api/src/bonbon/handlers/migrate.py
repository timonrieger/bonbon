"""Schema migrations, run inside the VPC because the database is private.

Invoked by `mise run db:migrate` (aws lambda invoke) after every `mise run stack:up`, never by
API Gateway. Connects as the master user from DbMasterSecret; only this function gets it.

Payload:
  {"action": "migrate"}  apply new files from bonbon/migrations/, then sync the app user (default)
  {"action": "status"}   applied migrations, row counts and the latest households (smoke test)
"""

import os
from pathlib import Path
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from pg8000.native import Connection, identifier, literal

from bonbon import db

logger = Logger()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def migrate(conn: Connection) -> dict[str, Any]:
    conn.run(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {version for [version] in conn.run("SELECT version FROM schema_migrations")}
    new = []
    for path in migration_files():
        if path.stem in applied:
            continue
        logger.info("Applying migration", version=path.stem)
        # One transaction per file: a failing migration leaves no half-applied schema.
        conn.run("START TRANSACTION")
        try:
            conn.execute_simple(path.read_text())
            conn.run("INSERT INTO schema_migrations (version) VALUES (:v)", v=path.stem)
            conn.run("COMMIT")
        except Exception:
            conn.run("ROLLBACK")
            raise
        new.append(path.stem)

    # The app user's password lives only in DbAppSecret. Setting it on every run also picks up
    # a changed secret. ALTER ROLE takes no bind parameters, hence literal() for quoting.
    app_user = os.environ["DB_APP_USER"]
    conn.run(
        f"ALTER ROLE {identifier(app_user)} LOGIN PASSWORD {literal(os.environ['DB_APP_PASSWORD'])}"
    )
    return {"applied": new, "already_applied": sorted(applied)}


def status(conn: Connection) -> dict[str, Any]:
    migrations = conn.run("SELECT version, applied_at FROM schema_migrations ORDER BY version")
    [counts] = conn.run(
        "SELECT"
        " (SELECT count(*) FROM households),"
        " (SELECT count(*) FROM memberships),"
        " (SELECT count(*) FROM receipts),"
        " (SELECT count(*) FROM receipt_items)"
    )
    households = conn.run(
        "SELECT h.id, h.name, h.created_at, count(m.user_id)"
        " FROM households h LEFT JOIN memberships m ON m.household_id = h.id"
        " GROUP BY h.id ORDER BY h.created_at DESC LIMIT 5"
    )
    return {
        "migrations": [{"version": v, "applied_at": str(at)} for v, at in migrations],
        "row_counts": dict(
            zip(["households", "memberships", "receipts", "receipt_items"], counts, strict=True)
        ),
        "latest_households": [
            {"id": str(i), "name": n, "created_at": str(at), "members": m}
            for i, n, at, m in households
        ],
    }


ACTIONS = {"migrate": migrate, "status": status}


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict[str, Any]:
    action = ACTIONS[(event or {}).get("action", "migrate")]
    conn = db.connect(os.environ["DB_USER"], os.environ["DB_PASSWORD"])
    try:
        return action(conn)
    finally:
        conn.close()
