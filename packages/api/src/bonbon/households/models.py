from datetime import datetime

from pydantic import BaseModel, Field

from bonbon.auth import Role


class CreateHouseholdRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class Household(BaseModel):
    id: str
    name: str
    created_at: datetime
    my_role: Role


class HouseholdList(BaseModel):
    # Wrapped in an object so fields can be added later without breaking clients.
    households: list[Household]


class Member(BaseModel):
    user_id: str
    display_name: str
    role: Role
    joined_at: datetime


class MemberList(BaseModel):
    members: list[Member]
