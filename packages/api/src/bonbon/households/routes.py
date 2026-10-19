"""Household endpoints. The reference pattern for every API route, see packages/api/AGENTS.md."""

from aws_lambda_powertools.event_handler.api_gateway import Router

from bonbon.auth import current_user_id, require_membership
from bonbon.households import repo
from bonbon.households.models import CreateHouseholdRequest, Household

router = Router()


@router.post("/households", operation_id="createHousehold", tags=["households"])
def create_household(body: CreateHouseholdRequest) -> Household:
    return repo.create(body.name, owner_id=current_user_id(router))


@router.get("/households/<household_id>", operation_id="getHousehold", tags=["households"])
def get_household(household_id: str) -> Household:
    role = require_membership(household_id, current_user_id(router))
    return repo.get(household_id, my_role=role)
