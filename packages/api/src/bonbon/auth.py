"""Authorization helpers. Every route that touches household data calls require_membership."""

from typing import Literal

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.utilities.data_classes import APIGatewayProxyEvent

from bonbon import db

Role = Literal["owner", "member"]


def current_user_id(router: Router) -> str:
    """The Cognito user id ('sub') of the current request. API Gateway already verified the JWT."""
    event = APIGatewayProxyEvent(router.current_event.raw_event)
    return event.request_context.authorizer.claims["sub"]


def require_membership(household_id: str, user_id: str) -> Role:
    """Return the user's role in the household, or 404.

    Checked against the database on every request so that leaving a household takes
    effect immediately. Non-members get 404 rather than 403 so household ids can't be probed.
    """
    item = (
        db.table()
        .get_item(Key={"PK": db.household_pk(household_id), "SK": db.member_sk(user_id)})
        .get("Item")
    )
    if item is None:
        raise NotFoundError("Household not found")
    return item["role"]
