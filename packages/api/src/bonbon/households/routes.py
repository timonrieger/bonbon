"""Household endpoints. The reference pattern for every API route, see packages/api/AGENTS.md."""

from aws_lambda_powertools.event_handler.api_gateway import Router

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.households import repo
from bonbon.households.models import CreateHouseholdRequest, Household, HouseholdList, MemberList

router = Router()


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
