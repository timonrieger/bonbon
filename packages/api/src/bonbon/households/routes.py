"""Household endpoints. The reference pattern for every API route, see packages/api/AGENTS.md."""

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.openapi.types import OpenAPIResponse

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.households import repo
from bonbon.households.models import (
    CreateHouseholdRequest,
    Household,
    HouseholdList,
    InviteCode,
    JoinRequest,
    MemberList,
)

router = Router()


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
