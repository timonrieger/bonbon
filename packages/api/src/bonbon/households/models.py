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
