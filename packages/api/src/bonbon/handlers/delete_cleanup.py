"""Account deletion, database and S3 part (feature 05, ADR 0007). Runs INSIDE the VPC, so it can
reach PostgreSQL and S3 (gateway endpoint) but not Cognito or SQS. Invoked synchronously by the
deletion worker (handlers/delete_account.py), which does the Cognito part outside the VPC.

Event: {"user_id": "<cognito sub>"}. Steps run in order and must each survive a second run,
because the worker's SQS job is retried as a whole on any failure. Any failure raises, so the
worker sees a FunctionError and lets the message reach the DLQ.
"""

from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.utilities.typing import LambdaContext

from bonbon.households import repo as households
from bonbon.receipts import storage
from bonbon.users import repo as users

logger = Logger()


def _delete_files(household_id: str) -> None:
    """Delete a household's S3 files, raising if S3 refuses any so the whole job retries."""
    deleted, failed = storage.delete_household_files(household_id)
    if failed:
        raise RuntimeError(f"S3 refused {len(failed)} file(s) of household {household_id}")
    logger.info("Deleted household files", household_id=household_id, files=deleted)


def _cleanup(user_id: str) -> None:
    # 1. Block the user: any request with a still-valid token is rejected from now on.
    users.tombstone(user_id)

    # 2 + 3. For each household the user is in: if they're the only member, delete its invite
    # codes (prepare_deletion, under the lock) and its S3 files BEFORE remove_member deletes the
    # household row, so a retry after an S3 error can still find the files. Then remove_member
    # deletes the household (sole member) or hands the owner role on (shared).
    for household_id in [h.id for h in households.list_for_user(user_id)]:
        sole_member = households.prepare_deletion(household_id, user_id)
        if sole_member:
            _delete_files(household_id)
        try:
            deleted = households.remove_member(household_id, user_id, hand_over=True)
        except NotFoundError:
            # Already removed in an earlier attempt; a retry skips it.
            logger.info("Household already left", household_id=household_id)
            continue
        if deleted and not sole_member:
            # Race: the last other member left between prepare_deletion (which saw them and
            # returned False) and remove_member, so the household was deleted after all and its
            # files were not cleaned up above. Delete them now. (If the job dies before this
            # succeeds, the household is already gone from list_for_user, so a retry can't find
            # the files again — the same accepted limitation as the sole-member path.)
            _delete_files(household_id)

    # 4. All memberships are gone now, so the users row can go (FK without cascade).
    # Tombstone stays.
    users.delete(user_id)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict[str, Any]:
    _cleanup(event["user_id"])
    return {"user_id": event["user_id"], "status": "cleaned"}
