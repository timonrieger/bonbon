"""Authorization helpers. Every route that touches household data calls require_membership."""

from typing import Literal
from uuid import UUID

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.event_handler.openapi.types import OpenAPIResponse
from aws_lambda_powertools.utilities.data_classes import APIGatewayProxyEvent

from bonbon import db

Role = Literal["owner", "member"]

# Pass as `responses=` on every route that calls require_membership, so the 404 is in the spec.
# Custom responses replace Powertools' defaults: 200 has no `content`, so Powertools fills in the
# route's return model; 404 states the error body explicitly, otherwise it would get that model too.
MEMBERSHIP_RESPONSES: dict[int, OpenAPIResponse] = {
    200: {"description": "Successful Response"},
    404: {
        "description": "Household not found, or the caller is not a member",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "statusCode": {"type": "integer"},
                        "message": {"type": "string"},
                    },
                    "required": ["statusCode", "message"],
                }
            }
        },
    },
}


def current_user_id(router: Router) -> str:
    """The Cognito user id ('sub') of the current request. API Gateway already verified the JWT."""
    event = APIGatewayProxyEvent(router.current_event.raw_event)
    return event.request_context.authorizer.claims["sub"]


def require_membership(household_id: str, user_id: str) -> Role:
    """Return the user's role in the household, or 404.

    Checked against the database on every request so that leaving a household takes
    effect immediately. Non-members get 404 rather than 403 so household ids can't be probed.
    A malformed id is a 404 too, not a database error.
    """
    try:
        parsed = UUID(household_id)
    except ValueError:
        raise NotFoundError("Household not found") from None
    role = role_in_household(parsed, user_id)
    if role is None:
        raise NotFoundError("Household not found")
    return role


def role_in_household(household_id: UUID, user_id: str) -> Role | None:
    """The membership lookup itself. Tests replace it with an in-memory fake."""
    rows = db.query(
        "SELECT role FROM memberships WHERE household_id = :household_id AND user_id = :user_id",
        household_id=household_id,
        user_id=user_id,
    )
    return rows[0][0] if rows else None
