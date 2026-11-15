from bonbon import db


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
