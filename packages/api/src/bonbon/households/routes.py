"""Household endpoints. The reference pattern for every API route, see packages/api/AGENTS.md."""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import Response
from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.exceptions import ServiceError
from aws_lambda_powertools.event_handler.openapi.types import OpenAPIResponse
from botocore.exceptions import BotoCoreError, ClientError

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.households import repo
from bonbon.households.models import (
    CreateHouseholdRequest,
    Household,
    HouseholdList,
    InviteCode,
    JoinRequest,
    MemberList,
    TransferOwnerRequest,
)
from bonbon.receipts import storage

router = Router()
logger = Logger()


def _error(description: str) -> OpenAPIResponse:
    """An error response with the same body as the membership 404."""
    return {**MEMBERSHIP_RESPONSES[404], "description": description}


@router.get("/households", operation_id="listHouseholds", tags=["households"])
def list_households() -> HouseholdList:
    """The households the caller is a member of, with their role in each, sorted by name."""
    return HouseholdList(households=repo.list_for_user(current_user_id(router)))


@router.post("/households", operation_id="createHousehold", tags=["households"])
def create_household(body: CreateHouseholdRequest) -> Household:
    return repo.create(body.name, owner_id=current_user_id(router))


@router.get(
    "/households/<household_id>",
    operation_id="getHousehold",
    tags=["households"],
    responses=MEMBERSHIP_RESPONSES,
)
def get_household(household_id: str) -> Household:
    role = require_membership(household_id, current_user_id(router))
    return repo.get(household_id, my_role=role)


@router.get(
    "/households/<household_id>/members",
    operation_id="listMembers",
    tags=["households"],
    responses=MEMBERSHIP_RESPONSES,
)
def list_members(household_id: str) -> MemberList:
    """Members of the household, owner first, then in the order they joined."""
    require_membership(household_id, current_user_id(router))
    return MemberList(members=repo.list_members(household_id))


@router.post(
    "/households/<household_id>/invites",
    operation_id="createInvite",
    tags=["households"],
    status_code=201,
    responses={201: {"description": "Invite code created"}, 404: MEMBERSHIP_RESPONSES[404]},
)
def create_invite(household_id: str) -> InviteCode:
    """A single-use invite code, valid for 48 hours. Every member can create one.

    The code is only returned here; the database keeps its hash.
    """
    require_membership(household_id, current_user_id(router))
    return repo.create_invite(household_id)


@router.post(
    "/households/join",
    operation_id="joinHousehold",
    tags=["households"],
    responses={
        200: {"description": "Joined; the household with my_role 'member'"},
        404: _error("Invite code unknown, expired or already used (counts as a failed attempt)"),
        409: _error("Already a member of this household; the code stays valid"),
        429: _error("5 failed attempts within the last hour; try again later"),
    },
)
def join_household(body: JoinRequest) -> Household:
    """Join a household with an invite code. Case, dashes and spaces in the code don't matter."""
    return repo.join(body.code, user_id=current_user_id(router))


# Registered before removeMember: Powertools takes the first route that matches, and
# <user_id> would match "me" too.
@router.delete(
    "/households/<household_id>/members/me",
    operation_id="leaveHousehold",
    tags=["households"],
    status_code=204,
    responses={
        204: {"description": "Left; if the caller was the last member, the household is deleted"},
        404: MEMBERSHIP_RESPONSES[404],
        409: _error("The owner can't leave while other members remain; hand over the role first"),
    },
)
def leave_household(household_id: str) -> Response[None]:
    """Leave the household. Access ends immediately.

    The last member leaving deletes the household with all its receipts and images.
    """
    user_id = current_user_id(router)
    require_membership(household_id, user_id)
    _remove(household_id, user_id, removed_by=user_id)
    return Response(status_code=204)


@router.delete(
    "/households/<household_id>/members/<user_id>",
    operation_id="removeMember",
    tags=["households"],
    status_code=204,
    responses={
        204: {"description": "Removed; their access ends immediately"},
        403: _error("Only the owner can remove other members"),
        404: _error("Household not found, the caller is not a member, or the user is not one"),
        409: _error("Removing oneself as the owner while other members remain, as in leaving"),
    },
)
def remove_member(household_id: str, user_id: str) -> Response[None]:
    """Remove a member (owner only). The caller's own id works like leaveHousehold."""
    caller = current_user_id(router)
    role = require_membership(household_id, caller)
    if user_id != caller and role != "owner":
        # Checked again in the repo under the household lock.
        raise ServiceError(403, "Only the owner can remove members")
    _remove(household_id, user_id, removed_by=caller)
    return Response(status_code=204)


@router.put(
    "/households/<household_id>/owner",
    operation_id="transferOwnership",
    tags=["households"],
    responses={
        **MEMBERSHIP_RESPONSES,
        200: {"description": "Handed over; the members with their new roles"},
        403: _error("Only the owner can hand over the role"),
        404: _error("Household not found, the caller is not a member, or the user is not one"),
    },
)
def transfer_ownership(household_id: str, body: TransferOwnerRequest) -> MemberList:
    """Make another member the owner (owner only). The old owner stays as a member."""
    caller = current_user_id(router)
    require_membership(household_id, caller)
    repo.transfer_owner(household_id, owner_id=caller, new_owner_id=body.user_id)
    return MemberList(members=repo.list_members(household_id))


def _remove(household_id: str, user_id: str, *, removed_by: str) -> None:
    if not repo.remove_member(household_id, user_id, removed_by=removed_by):
        return
    # The household is gone from the database; its files go now. Best effort: the request
    # succeeded either way. Leftover files are unreachable (no receipt points to them) and
    # logged as ERROR, so they can be removed by hand.
    try:
        deleted, failed = storage.delete_household_files(household_id)
    except BotoCoreError, ClientError:
        logger.exception(
            "Deleting the files of a deleted household failed", household_id=household_id
        )
        return
    if failed:
        logger.error(
            "Some files of a deleted household could not be deleted",
            household_id=household_id,
            files=deleted,
            failed=failed,
        )
    else:
        logger.info(
            "Deleted the files of a deleted household", household_id=household_id, files=deleted
        )
