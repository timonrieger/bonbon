from datetime import datetime
from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError

from bonbon import db
from bonbon.auth import Role
from bonbon.households.models import Household, Member


def create(name: str, owner_id: str) -> Household:
    # Household and owner membership are written together or not at all.
    with db.transaction() as conn:
        [[household_id, created_at]] = conn.run(
            "INSERT INTO households (name) VALUES (:name) RETURNING id, created_at",
            name=name,
        )
        conn.run(
            "INSERT INTO memberships (household_id, user_id, role)"
            " VALUES (:household_id, :user_id, 'owner')",
            household_id=household_id,
            user_id=owner_id,
        )
    return _household(household_id, name, created_at, "owner")


def get(household_id: str, my_role: Role) -> Household:
    rows = db.query("SELECT name, created_at FROM households WHERE id = :id", id=UUID(household_id))
    if not rows:
        # Deleted between the membership check and this read.
        raise NotFoundError("Household not found")
    [[name, created_at]] = rows
    return _household(household_id, name, created_at, my_role)


def list_for_user(user_id: str) -> list[Household]:
    rows = db.query(
        "SELECT h.id, h.name, h.created_at, m.role"
        " FROM households h JOIN memberships m ON m.household_id = h.id"
        " WHERE m.user_id = :user_id"
        " ORDER BY h.name, h.created_at",
        user_id=user_id,
    )
    return [_household(*row) for row in rows]


def list_members(household_id: str) -> list[Member]:
    rows = db.query(
        "SELECT m.user_id, u.display_name, m.role, m.joined_at"
        " FROM memberships m JOIN users u ON u.user_id = m.user_id"
        " WHERE m.household_id = :household_id"
        # Owner first, then in the order they joined.
        " ORDER BY m.role = 'owner' DESC, m.joined_at, u.display_name",
        household_id=UUID(household_id),
    )
    return [
        Member(user_id=user_id, display_name=name, role=role, joined_at=joined_at)
        for user_id, name, role, joined_at in rows
    ]


def _household(household_id: UUID | str, name: str, created_at: datetime, role: Role) -> Household:
    return Household(id=str(household_id), name=name, created_at=created_at, my_role=role)
