"""In-memory stand-ins for the SQL repo functions.

moto can't fake PostgreSQL and Docker is off the table (docs/decisions/0004), so route tests
replace the repo layer with these. They check routing, validation and membership rules, not
the SQL itself; that runs against the dev stack (open question in docs/decisions/0006).
Keep the behavior in line with the real functions in bonbon/*/repo.py and bonbon/auth.py.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from aws_lambda_powertools.event_handler.exceptions import NotFoundError, ServiceError
from bonbon.auth import Role
from bonbon.households import codes
from bonbon.households.models import Household, InviteCode, Member
from bonbon.households.repo import INVITE_VALID_HOURS, MAX_FAILED_JOINS
from bonbon.receipts.categories import DEFAULT_CATEGORY, categorize
from bonbon.receipts.expense import ExtractedReceipt
from bonbon.receipts.models import (
    ReceiptCorrection,
    ReceiptItem,
    ReceiptStatus,
    ReceiptSummary,
    month_bounds,
)
from bonbon.receipts.repo import WorkerOutcome
from bonbon.reports.models import (
    CategoryTotal,
    MonthlyReport,
    MonthTotal,
    SpendingTrend,
    StoreTotal,
)


@dataclass
class FakeReceipt:
    household_id: UUID
    uploaded_by: str | None
    status: ReceiptStatus = "uploaded"
    store: str | None = None
    purchase_date: date | None = None
    total_rappen: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    items: list[ReceiptItem] = field(default_factory=list)
    file_hash: str | None = None
    processed_at: datetime | None = None

    @property
    def day(self) -> date:
        """Like RECEIPT_DAY in bonbon/receipts/repo.py (without the time zone)."""
        return self.purchase_date or self.created_at.date()


@dataclass
class FakeInvite:
    household_id: UUID
    expires_at: datetime
    used_at: datetime | None = None


class FakeDatabase:
    def __init__(self) -> None:
        self.households: dict[UUID, tuple[str, datetime]] = {}
        self.memberships: dict[tuple[UUID, str], Role] = {}
        self.joined_at: dict[tuple[UUID, str], datetime] = {}
        # user id -> (display_name, email)
        self.users: dict[str, tuple[str, str | None]] = {}
        # user ids marked for deletion (feature 05); see migration 0008
        self.tombstones: set[str] = set()
        self.receipts: dict[UUID, FakeReceipt] = {}
        # Migration 0002 adds 'Sonstiges'; tests add more.
        self.categories: set[str] = {"Sonstiges"}
        # (keyword, category) like category_rules; empty: every item is 'Sonstiges'
        self.category_rules: list[tuple[str, str]] = []
        # code hash -> invite; only the hash is kept, like in invite_codes
        self.invites: dict[str, FakeInvite] = {}
        # (user id, attempted_at) of failed joins
        self.join_attempts: list[tuple[str, datetime]] = []

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

    def create_invite(self, household_id: str) -> InviteCode:
        now = datetime.now(UTC)
        self.invites = {
            h: i
            for h, i in self.invites.items()
            if i.household_id != UUID(household_id) or (i.used_at is None and i.expires_at > now)
        }
        code = codes.generate()
        expires_at = now + timedelta(hours=INVITE_VALID_HOURS)
        self.invites[codes.code_hash(code)] = FakeInvite(UUID(household_id), expires_at)
        return InviteCode(code=code, expires_at=expires_at)

    def join(self, code: str, user_id: str) -> Household:
        now = datetime.now(UTC)
        self.join_attempts = [
            (u, t) for u, t in self.join_attempts if u != user_id or t > now - timedelta(hours=1)
        ]
        if sum(u == user_id for u, _ in self.join_attempts) >= MAX_FAILED_JOINS:
            raise ServiceError(429, "Too many failed attempts, try again later")
        invite = self.invites.get(codes.code_hash(code))
        if invite is None or invite.used_at is not None or invite.expires_at <= now:
            self.join_attempts.append((user_id, now))
            raise NotFoundError("Invite code not found, expired or already used")
        if (invite.household_id, user_id) in self.memberships:
            raise ServiceError(409, "Already a member of this household")
        self.add_member(invite.household_id, user_id)
        invite.used_at = now
        return self.get_household(str(invite.household_id), "member")

    def _roles(self, household_id: UUID) -> dict[str, Role]:
        """Members in the order they joined, like the ORDER BY in remove_member."""
        found = [(u, r) for (h, u), r in self.memberships.items() if h == household_id]
        found.sort(key=lambda ur: (self.joined_at[(household_id, ur[0])], ur[0]))
        return dict(found)

    def remove_member(
        self,
        household_id: str,
        user_id: str,
        *,
        hand_over: bool = False,
        removed_by: str | None = None,
    ) -> bool:
        h = UUID(household_id)
        if h not in self.households:
            raise NotFoundError("Household not found")
        roles = self._roles(h)
        if removed_by is not None and removed_by != user_id and roles.get(removed_by) != "owner":
            raise ServiceError(403, "Only the owner can remove members")
        if user_id not in roles:
            raise NotFoundError("Member not found")
        others = [other for other in roles if other != user_id]
        if not others:
            # ON DELETE CASCADE
            del self.households[h]
            self.memberships = {k: r for k, r in self.memberships.items() if k[0] != h}
            self.invites = {c: i for c, i in self.invites.items() if i.household_id != h}
            self.receipts = {k: r for k, r in self.receipts.items() if r.household_id != h}
            return True
        if roles[user_id] == "owner" and not hand_over:
            raise ServiceError(409, "The owner must hand over the role before leaving")
        del self.memberships[(h, user_id)]
        if roles[user_id] == "owner":
            self.memberships[(h, others[0])] = "owner"
        return False

    def prepare_deletion(self, household_id: str, user_id: str) -> bool:
        h = UUID(household_id)
        if h not in self.households:
            return False
        members = [u for (hh, u) in self.memberships if hh == h]
        sole_member = members == [user_id]
        if sole_member:
            self.invites = {c: i for c, i in self.invites.items() if i.household_id != h}
        return sole_member

    def transfer_owner(self, household_id: str, owner_id: str, new_owner_id: str) -> None:
        h = UUID(household_id)
        if h not in self.households:
            raise NotFoundError("Household not found")
        roles = self._roles(h)
        if roles.get(owner_id) != "owner":
            raise ServiceError(403, "Only the owner can hand over the role")
        if new_owner_id not in roles:
            raise NotFoundError("Member not found")
        if new_owner_id != owner_id:
            self.memberships[(h, owner_id)] = "member"
            self.memberships[(h, new_owner_id)] = "owner"

    # bonbon.receipts.categories
    def rules(self) -> list[tuple[str, str]]:
        return self.category_rules

    # bonbon.users.repo
    def sync_user(self, user_id: str, display_name: str, email: str | None) -> None:
        self.users[user_id] = (display_name, email)

    def is_tombstoned(self, user_id: str) -> bool:
        return user_id in self.tombstones

    def tombstone(self, user_id: str) -> None:
        self.tombstones.add(user_id)

    def delete_user(self, user_id: str) -> None:
        self.users.pop(user_id, None)

    # Test setup: a member without going through an invite code.
    def add_member(self, household_id: UUID, user_id: str, role: Role = "member") -> None:
        # Like the foreign key: the user must have made a request before.
        assert user_id in self.users, f"unknown user {user_id}"
        self.memberships[(household_id, user_id)] = role
        self.joined_at[(household_id, user_id)] = datetime.now(UTC)

    # bonbon.receipts.repo
    def create_receipt(self, household_id: str, uploaded_by: str) -> str:
        return str(self.add_receipt(UUID(household_id), uploaded_by))

    def list_receipts(self, household_id: str, month: str | None) -> list[ReceiptSummary]:
        abandoned_before = datetime.now(UTC) - timedelta(minutes=30)
        start, end = month_bounds(month) if month else (date.min, date.max)
        found = [
            (receipt_id, r)
            for receipt_id, r in self.receipts.items()
            if r.household_id == UUID(household_id)
            and not (r.status == "uploaded" and r.created_at < abandoned_before)
            and start <= r.day < end
        ]
        found.sort(key=lambda found: (found[1].day, found[1].created_at), reverse=True)
        return [self._summary(receipt_id, r) for receipt_id, r in found]

    def get_receipt(
        self, household_id: str, receipt_id: str
    ) -> tuple[ReceiptSummary, list[ReceiptItem]]:
        try:
            r = self.receipts.get(UUID(receipt_id))
        except ValueError:
            r = None
        if r is None or r.household_id != UUID(household_id):
            raise NotFoundError("Receipt not found")
        return self._summary(UUID(receipt_id), r), r.items

    def correct_receipt(
        self, household_id: str, receipt_id: str, correction: ReceiptCorrection
    ) -> None:
        self.get_receipt(household_id, receipt_id)  # 404 like the real one
        r = self.receipts[UUID(receipt_id)]
        if r.status != "done":
            raise ServiceError(409, "Only processed receipts can be corrected")
        given = correction.model_fields_set
        if correction.items is not None:
            unknown = sorted({i.category for i in correction.items} - self.categories)
            if unknown:
                raise ServiceError(422, f"Unknown category: {', '.join(unknown)}")
        if "store" in given:
            r.store = correction.store
        if "purchase_date" in given:
            r.purchase_date = correction.purchase_date
        if "total_rappen" in given:
            r.total_rappen = correction.total_rappen
        if correction.items is not None:
            r.items = sorted(
                (ReceiptItem(**item.model_dump()) for item in correction.items),
                key=lambda item: item.position,
            )

    def category_names(self) -> list[str]:
        return sorted(self.categories, key=lambda name: (name == DEFAULT_CATEGORY, name))

    def _summary(self, receipt_id: UUID, r: FakeReceipt) -> ReceiptSummary:
        same = (r.store, r.purchase_date, r.total_rappen)
        duplicate = r.status == "done" and any(
            other_id != receipt_id
            and o.household_id == r.household_id
            and o.status == "done"
            and None not in same
            and (o.store, o.purchase_date, o.total_rappen) == same
            for other_id, o in self.receipts.items()
        )
        return ReceiptSummary(
            id=str(receipt_id),
            status=r.status,
            store=r.store,
            purchase_date=r.purchase_date,
            total_rappen=r.total_rappen,
            uploaded_by_name=self.users[r.uploaded_by][0] if r.uploaded_by else None,
            created_at=r.created_at,
            possible_duplicate=duplicate,
        )

    def finish_extracted(
        self, household_id: UUID, receipt_id: UUID, file_hash: str, receipt: ExtractedReceipt
    ) -> WorkerOutcome:
        r = self.receipts.get(receipt_id)
        if r is None or r.household_id != household_id:
            return "missing"
        if r.status != "uploaded":
            return "unchanged"
        same_file = any(
            other_id != receipt_id
            and o.household_id == household_id
            and o.file_hash == file_hash
            and o.status not in ("duplicate", "failed")
            for other_id, o in self.receipts.items()
        )
        outcome: Literal["done", "duplicate"] = "duplicate" if same_file else "done"
        r.status = outcome
        r.file_hash = file_hash
        r.store, r.purchase_date = receipt.store, receipt.purchase_date
        r.total_rappen = receipt.total_rappen
        r.processed_at = datetime.now(UTC)
        if outcome == "done":
            r.items = [
                ReceiptItem(
                    position=position,
                    name=item.name,
                    quantity=float(item.quantity),
                    unit_price_rappen=item.unit_price_rappen,
                    amount_rappen=item.amount_rappen,
                    category=categorize(item.name),
                )
                for position, item in enumerate(receipt.items, start=1)
            ]
        return outcome

    def finish_failed(self, household_id: UUID, receipt_id: UUID) -> WorkerOutcome:
        r = self.receipts.get(receipt_id)
        if r is None or r.household_id != household_id:
            return "missing"
        if r.status != "uploaded":
            return "unchanged"
        r.status = "failed"
        r.processed_at = datetime.now(UTC)
        return "failed"

    # Test setup: receipts as the worker will leave them.
    def add_receipt(self, household_id: UUID, uploaded_by: str | None, **fields: Any) -> UUID:
        receipt_id = uuid4()
        self.receipts[receipt_id] = FakeReceipt(household_id, uploaded_by, **fields)
        return receipt_id

    # bonbon.reports.repo
    def _done(self, household_id: str, start: date, end: date) -> list[FakeReceipt]:
        return [
            r
            for r in self.receipts.values()
            if r.household_id == UUID(household_id) and r.status == "done" and start <= r.day < end
        ]

    def monthly_report(self, household_id: str, month: str) -> MonthlyReport:
        start, end = month_bounds(month)
        previous = (start - timedelta(days=1)).replace(day=1)
        receipts = self._done(household_id, start, end)
        by_category: dict[str, int] = defaultdict(int)
        by_store: dict[str | None, int] = defaultdict(int)
        for r in receipts:
            by_store[r.store] += r.total_rappen or 0
            for item in r.items:
                by_category[item.category] += item.amount_rappen
        return MonthlyReport(
            month=month,
            total_rappen=sum(r.total_rappen or 0 for r in receipts),
            receipt_count=len(receipts),
            previous_month_total_rappen=sum(
                r.total_rappen or 0 for r in self._done(household_id, previous, start)
            ),
            by_category=[
                CategoryTotal(category=c, total_rappen=t)
                for c, t in sorted(by_category.items(), key=lambda ct: (-ct[1], ct[0]))
            ],
            by_store=[
                StoreTotal(store=s, total_rappen=t)
                for s, t in sorted(by_store.items(), key=lambda st: (-st[1], st[0] is None, st[0]))
            ],
        )

    def spending_trend(self, household_id: str, months: int) -> SpendingTrend:
        start = date.today().replace(day=1)
        firsts = [start]
        for _ in range(months - 1):
            firsts.insert(0, (firsts[0] - timedelta(days=1)).replace(day=1))
        return SpendingTrend(
            months=[
                MonthTotal(
                    month=first.strftime("%Y-%m"),
                    total_rappen=sum(
                        r.total_rappen or 0
                        for r in self._done(household_id, *month_bounds(first.strftime("%Y-%m")))
                    ),
                )
                for first in firsts
            ]
        )
