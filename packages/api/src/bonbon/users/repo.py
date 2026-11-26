from bonbon import db


def is_tombstoned(user_id: str) -> bool:
    """Whether this account is being (or has been) deleted (feature 05)."""
    return bool(db.query("SELECT 1 FROM tombstones WHERE user_id = :user_id", user_id=user_id))


def tombstone(user_id: str) -> None:
    """Mark an account for deletion; idempotent, so a retried deletion job changes nothing."""
    with db.transaction() as conn:
        conn.run(
            "INSERT INTO tombstones (user_id) VALUES (:user_id) ON CONFLICT DO NOTHING",
            user_id=user_id,
        )


def delete(user_id: str) -> None:
    """Remove the users row after all memberships are gone (feature 05, account deletion step 4).

    memberships.user_id references users without ON DELETE CASCADE, so every membership must be
    removed first (remove_member). receipts.uploaded_by is ON DELETE SET NULL, so receipts stay
    without an uploader. Idempotent: deleting an absent row is a no-op. The tombstone is kept.
    """
    with db.transaction() as conn:
        conn.run("DELETE FROM users WHERE user_id = :user_id", user_id=user_id)


def sync(user_id: str, display_name: str, email: str | None) -> None:
    """Create the user or update name and e-mail; writes nothing if both are unchanged."""
    with db.transaction() as conn:
        conn.run(
            "INSERT INTO users (user_id, display_name, email)"
            " VALUES (:user_id, :display_name, :email)"
            " ON CONFLICT (user_id) DO UPDATE"
            " SET display_name = EXCLUDED.display_name, email = EXCLUDED.email"
            " WHERE (users.display_name, users.email)"
            " IS DISTINCT FROM (EXCLUDED.display_name, EXCLUDED.email)",
            user_id=user_id,
            display_name=display_name,
            email=email,
        )
