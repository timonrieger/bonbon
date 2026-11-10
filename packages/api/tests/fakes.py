"""In-memory stand-ins for the SQL repo functions.

moto can't fake PostgreSQL and Docker is off the table (docs/decisions/0004), so route tests
replace the repo layer with these. They check routing, validation and membership rules, not
the SQL itself; that runs against the dev stack (open question in docs/decisions/0006).
Keep the behavior in line with the real functions in bonbon/*/repo.py and bonbon/auth.py.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from bonbon.auth import Role
from bonbon.households.models import Household


class FakeDatabase:
    def __init__(self) -> None:
        self.households: dict[UUID, tuple[str, datetime]] = {}
        self.memberships: dict[tuple[UUID, str], Role] = {}

    # bonbon.auth
    def role_in_household(self, household_id: UUID, user_id: str) -> Role | None:
        return self.memberships.get((household_id, user_id))

    # bonbon.households.repo
    def create_household(self, name: str, owner_id: str) -> Household:
        household_id = uuid4()
        created_at = datetime.now(UTC)
        self.households[household_id] = (name, created_at)
        self.memberships[(household_id, owner_id)] = "owner"
        return Household(id=str(household_id), name=name, created_at=created_at, my_role="owner")

    def get_household(self, household_id: str, my_role: Role) -> Household:
        if UUID(household_id) not in self.households:
            raise NotFoundError("Household not found")
        name, created_at = self.households[UUID(household_id)]
        return Household(id=household_id, name=name, created_at=created_at, my_role=my_role)
