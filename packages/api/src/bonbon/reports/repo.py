"""Report queries. Totals are summed at query time, nothing is pre-aggregated
(docs/features/03-dashboard.md), so corrections show up immediately.

Only receipts with status 'done' count. A receipt counts towards the month of RECEIPT_DAY.

The queries are put together from the constants DONE and RECEIPT_DAY only; every value goes in
as a bind parameter. That is why bandit's B608 is silenced on those lines.
"""

from datetime import timedelta
from uuid import UUID

from bonbon import db
from bonbon.receipts.models import month_bounds
from bonbon.receipts.repo import RECEIPT_DAY
from bonbon.reports.models import (
    CategoryTotal,
    MonthlyReport,
    MonthTotal,
    SpendingTrend,
    StoreTotal,
)

# Done receipts of one household with the day they count towards.
DONE = (
    "SELECT r.id, r.store, r.total_rappen, " + RECEIPT_DAY + " AS day FROM receipts r"  # nosec B608
    " WHERE r.household_id = :household_id AND r.status = 'done'"
)


def monthly(household_id: str, month: str) -> MonthlyReport:
    start, end = month_bounds(month)
    previous = (start - timedelta(days=1)).replace(day=1)
    params = {"household_id": UUID(household_id), "start": start, "end": end}

    [[total, count, previous_total]] = db.query(
        "SELECT"  # nosec B608
        " coalesce(sum(total_rappen) FILTER (WHERE day >= :start), 0),"
        " count(*) FILTER (WHERE day >= :start),"
        " coalesce(sum(total_rappen) FILTER (WHERE day < :start), 0)"
        " FROM (" + DONE + ") r WHERE day >= :previous AND day < :end",
        previous=previous,
        **params,
    )
    by_category = db.query(
        "SELECT c.name, sum(i.amount_rappen) FROM (" + DONE + ") r"  # nosec B608
        " JOIN receipt_items i ON i.receipt_id = r.id"
        " JOIN categories c ON c.id = i.category_id"
        " WHERE r.day >= :start AND r.day < :end"
        " GROUP BY c.name ORDER BY 2 DESC, c.name",
        **params,
    )
    by_store = db.query(
        "SELECT r.store, coalesce(sum(r.total_rappen), 0) FROM (" + DONE + ") r"  # nosec B608
        " WHERE r.day >= :start AND r.day < :end"
        " GROUP BY r.store ORDER BY 2 DESC, r.store NULLS LAST",
        **params,
    )
    return MonthlyReport(
        month=month,
        total_rappen=total,
        receipt_count=count,
        previous_month_total_rappen=previous_total,
        by_category=[CategoryTotal(category=c, total_rappen=t) for c, t in by_category],
        by_store=[StoreTotal(store=s, total_rappen=t) for s, t in by_store],
    )


def trend(household_id: str, months: int) -> SpendingTrend:
    """The last `months` months up to the current one in Swiss time, oldest first."""
    rows = db.query(
        "WITH m AS (SELECT generate_series("  # nosec B608
        "   date_trunc('month', now() AT TIME ZONE 'Europe/Zurich')"
        "     - make_interval(months => :months::int - 1),"
        "   date_trunc('month', now() AT TIME ZONE 'Europe/Zurich'),"
        "   interval '1 month')::date AS start)"
        " SELECT to_char(m.start, 'YYYY-MM'), coalesce(sum(r.total_rappen), 0)"
        " FROM m LEFT JOIN (" + DONE + ") r"
        "   ON r.day >= m.start AND r.day < (m.start + interval '1 month')::date"
        " GROUP BY m.start ORDER BY m.start",
        household_id=UUID(household_id),
        months=months,
    )
    return SpendingTrend(months=[MonthTotal(month=m, total_rappen=t) for m, t in rows])
