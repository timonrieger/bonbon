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
        # Household before invite codes, like join() and remove_member(), so this can't
        # deadlock with the last member leaving.
        conn.run("SELECT 1 FROM households WHERE id = :id FOR KEY SHARE", id=UUID(household_id))
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
        # Household before invite, the lock order of remove_member (whose household delete
        # cascades to the invite codes); the opposite order could deadlock with the last member
        # leaving. KEY SHARE doesn't block other joins. If the household is gone, so is the code.
        conn.run(
            "SELECT 1 FROM households WHERE id ="
            " (SELECT household_id FROM invite_codes WHERE code_hash = :code_hash)"
            " FOR KEY SHARE",
            code_hash=codes.code_hash(code),
        )
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


def remove_member(
    household_id: str, user_id: str, *, hand_over: bool = False, removed_by: str | None = None
) -> bool:
    """End a membership in one transaction. Returns True if the household was deleted with it.

    - The last member: the household goes, and with it (ON DELETE CASCADE) memberships,
      invite codes, receipts and their items. Its files in S3 are left to the caller.
    - The owner while others remain: 409, or with `hand_over` the role passes to the member
      who joined first. Only account deletion hands over (feature 05); leaving never does.
    - `removed_by` another user: they must be the owner (403), checked under the same lock,
      so an owner who just handed over the role can't remove anyone any more.

    404 if the user (or the household) is gone.
    """
    with db.transaction() as conn:
        # Lock the household: of two members leaving at once, the second one sees the first
        # gone, so a household can't end up without members or without an owner.
        if not conn.run(
            "SELECT 1 FROM households WHERE id = :id FOR UPDATE", id=UUID(household_id)
        ):
            raise NotFoundError("Household not found")
        roles: dict[str, Role] = dict(
            conn.run(
                "SELECT user_id, role FROM memberships WHERE household_id = :household_id"
                " ORDER BY joined_at, user_id",
                household_id=UUID(household_id),
            )
        )
        if removed_by is not None and removed_by != user_id and roles.get(removed_by) != "owner":
            raise ServiceError(403, "Only the owner can remove members")
        if user_id not in roles:
            raise NotFoundError("Member not found")
        others = [other for other in roles if other != user_id]
        if not others:
            conn.run("DELETE FROM households WHERE id = :id", id=UUID(household_id))
            return True
        if roles[user_id] == "owner" and not hand_over:
            raise ServiceError(409, "The owner must hand over the role before leaving")
        conn.run(
            "DELETE FROM memberships WHERE household_id = :household_id AND user_id = :user_id",
            household_id=UUID(household_id),
            user_id=user_id,
        )
        if roles[user_id] == "owner":
            conn.run(
                "UPDATE memberships SET role = 'owner'"
                " WHERE household_id = :household_id AND user_id = :user_id",
                household_id=UUID(household_id),
                user_id=others[0],
            )
    return False


def transfer_owner(household_id: str, owner_id: str, new_owner_id: str) -> None:
    """Make another member the owner; the old owner stays as a member.

    403 if `owner_id` isn't (any more) the owner, 404 if `new_owner_id` isn't a member.
    Handing over to oneself changes nothing.
    """
    with db.transaction() as conn:
        if not conn.run(
            "SELECT 1 FROM households WHERE id = :id FOR UPDATE", id=UUID(household_id)
        ):
            raise NotFoundError("Household not found")
        roles: dict[str, Role] = dict(
            conn.run(
                "SELECT user_id, role FROM memberships WHERE household_id = :household_id",
                household_id=UUID(household_id),
            )
        )
        if roles.get(owner_id) != "owner":
            raise ServiceError(403, "Only the owner can hand over the role")
        if new_owner_id not in roles:
            raise NotFoundError("Member not found")
        if new_owner_id == owner_id:
            return
        # Old owner first: the unique index allows only one owner per household at any time.
        for user_id, role in ((owner_id, "member"), (new_owner_id, "owner")):
            conn.run(
                "UPDATE memberships SET role = :role"
                " WHERE household_id = :household_id AND user_id = :user_id",
                role=role,
                household_id=UUID(household_id),
                user_id=user_id,
            )


def _household(household_id: UUID | str, name: str, created_at: datetime, role: Role) -> Household:
    return Household(id=str(household_id), name=name, created_at=created_at, my_role=role)
