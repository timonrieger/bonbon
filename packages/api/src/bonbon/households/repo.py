from datetime import datetime
from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError, ServiceError

from bonbon import db
from bonbon.auth import Role
from bonbon.households import codes
from bonbon.households.models import Household, InviteCode, Member

INVITE_VALID_HOURS = 48
# Failed join attempts per user within the last hour; the next one gets 429.
MAX_FAILED_JOINS = 5


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


def create_invite(household_id: str) -> InviteCode:
    """A new single-use invite code, valid for 48 h. Only its hash is stored."""
    code = codes.generate()
    with db.transaction() as conn:
        # Codes that can't be used any more are only clutter; nothing reads them.
        conn.run(
            "DELETE FROM invite_codes WHERE household_id = :household_id"
            " AND (used_at IS NOT NULL OR expires_at <= now())",
            household_id=UUID(household_id),
        )
        [[expires_at]] = conn.run(
            "INSERT INTO invite_codes (code_hash, household_id, expires_at)"
            " VALUES (:code_hash, :household_id, now() + make_interval(hours => :hours))"
            " RETURNING expires_at",
            code_hash=codes.code_hash(code),
            household_id=UUID(household_id),
            hours=INVITE_VALID_HOURS,
        )
    return InviteCode(code=code, expires_at=expires_at)


def join(code: str, user_id: str) -> Household:
    """Join the household of an invite code as a member and use the code up, in one transaction.

    404 for an unknown, expired or used code, which also counts as a failed attempt; 409 if the
    user is a member already (the code stays valid); 429 after MAX_FAILED_JOINS failed attempts
    in the last hour, also for parallel requests.
    """
    with db.transaction() as conn:
        # One join per user at a time, so counting and recording attempts can't interleave.
        # The users row always exists (current_user_id syncs it first). NO KEY UPDATE doesn't
        # block inserts elsewhere that reference the user through a foreign key.
        conn.run("SELECT 1 FROM users WHERE user_id = :user_id FOR NO KEY UPDATE", user_id=user_id)
        conn.run(
            "DELETE FROM join_attempts WHERE user_id = :user_id"
            " AND attempted_at <= now() - interval '1 hour'",
            user_id=user_id,
        )
        [[failed]] = conn.run(
            "SELECT count(*) FROM join_attempts WHERE user_id = :user_id", user_id=user_id
        )
        if failed >= MAX_FAILED_JOINS:
            raise ServiceError(429, "Too many failed attempts, try again later")
        # FOR UPDATE: of two people using the same code at once, the second one waits and then
        # finds it used.
        rows = conn.run(
            "SELECT household_id FROM invite_codes WHERE code_hash = :code_hash"
            " AND used_at IS NULL AND expires_at > now() FOR UPDATE",
            code_hash=codes.code_hash(code),
        )
        if not rows:
            # Committed with the transaction, so the attempt counts although the request fails.
            conn.run("INSERT INTO join_attempts (user_id) VALUES (:user_id)", user_id=user_id)
            household = None
        else:
            [[household_id]] = rows
            # Checked by the insert itself; the rollback leaves the code valid.
            if not conn.run(
                "INSERT INTO memberships (household_id, user_id, role)"
                " VALUES (:household_id, :user_id, 'member')"
                " ON CONFLICT (household_id, user_id) DO NOTHING RETURNING 1",
                household_id=household_id,
                user_id=user_id,
            ):
                raise ServiceError(409, "Already a member of this household")
            conn.run(
                "UPDATE invite_codes SET used_at = now() WHERE code_hash = :code_hash",
                code_hash=codes.code_hash(code),
            )
            [[name, created_at]] = conn.run(
                "SELECT name, created_at FROM households WHERE id = :id", id=household_id
            )
            household = _household(household_id, name, created_at, "member")
    if household is None:
        raise NotFoundError("Invite code not found, expired or already used")
    return household


def _household(household_id: UUID | str, name: str, created_at: datetime, role: Role) -> Household:
    return Household(id=str(household_id), name=name, created_at=created_at, my_role=role)
