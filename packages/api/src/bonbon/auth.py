"""Authorization helpers. Every route that touches household data calls require_membership."""

from typing import Literal
from uuid import UUID

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
