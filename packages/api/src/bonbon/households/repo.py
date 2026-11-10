from datetime import datetime
from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError

from bonbon import db
from bonbon.auth import Role
from bonbon.households.models import Household


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


def _household(household_id: UUID | str, name: str, created_at: datetime, role: Role) -> Household:
    return Household(id=str(household_id), name=name, created_at=created_at, my_role=role)
