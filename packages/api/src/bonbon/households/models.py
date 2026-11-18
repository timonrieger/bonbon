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


class TransferOwnerRequest(BaseModel):
    # A Cognito user id ('sub') from listMembers.
    user_id: str = Field(min_length=1, max_length=128)


class InviteCode(BaseModel):
    # Shown once: only its hash is stored. Formatted as XXXX-XXXX; joining ignores case,
    # dashes and spaces.
    code: str = Field(examples=["K7QM-X3PD"])
    expires_at: datetime


class JoinRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20, examples=["K7QM-X3PD"])
