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
from bonbon.households.models import Household, Member


class FakeDatabase:
    def __init__(self) -> None:
        self.households: dict[UUID, tuple[str, datetime]] = {}
        self.memberships: dict[tuple[UUID, str], Role] = {}
        self.joined_at: dict[tuple[UUID, str], datetime] = {}
        # user id -> (display_name, email)
        self.users: dict[str, tuple[str, str | None]] = {}

    # bonbon.auth
    def role_in_household(self, household_id: UUID, user_id: str) -> Role | None:
        return self.memberships.get((household_id, user_id))

    # bonbon.households.repo
    def create_household(self, name: str, owner_id: str) -> Household:
        household_id = uuid4()
        created_at = datetime.now(UTC)
        self.households[household_id] = (name, created_at)
        self.add_member(household_id, owner_id, "owner")
        return Household(id=str(household_id), name=name, created_at=created_at, my_role="owner")

    def get_household(self, household_id: str, my_role: Role) -> Household:
        if UUID(household_id) not in self.households:
            raise NotFoundError("Household not found")
        name, created_at = self.households[UUID(household_id)]
        return Household(id=household_id, name=name, created_at=created_at, my_role=my_role)

    def list_households(self, user_id: str) -> list[Household]:
        mine = [
            Household(
                id=str(h),
                name=self.households[h][0],
                created_at=self.households[h][1],
                my_role=role,
            )
            for (h, u), role in self.memberships.items()
            if u == user_id
        ]
        return sorted(mine, key=lambda h: (h.name, h.created_at))

    def list_members(self, household_id: str) -> list[Member]:
        members = [
            Member(
                user_id=u,
                display_name=self.users[u][0],
                role=role,
                joined_at=self.joined_at[(h, u)],
            )
            for (h, u), role in self.memberships.items()
            if h == UUID(household_id)
        ]
        return sorted(members, key=lambda m: (m.role != "owner", m.joined_at, m.display_name))

    # bonbon.users.repo
    def sync_user(self, user_id: str, display_name: str, email: str | None) -> None:
        self.users[user_id] = (display_name, email)

    # Test setup: memberships that later features (joining by invite code) will create.
    def add_member(self, household_id: UUID, user_id: str, role: Role = "member") -> None:
        # Like the foreign key: the user must have made a request before.
        assert user_id in self.users, f"unknown user {user_id}"
        self.memberships[(household_id, user_id)] = role
        self.joined_at[(household_id, user_id)] = datetime.now(UTC)
