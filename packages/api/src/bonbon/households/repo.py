from datetime import UTC, datetime
from uuid import uuid4

from bonbon import db
from bonbon.auth import Role
from bonbon.households.models import Household


def create(name: str, owner_id: str) -> Household:
    household_id = str(uuid4())
    now = datetime.now(UTC)
    pk = db.household_pk(household_id)
    # Household and owner membership are written together or not at all.
    db.table().meta.client.transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": db.table().name,
                    "Item": {
                        "PK": pk,
                        "SK": db.HOUSEHOLD_META_SK,
                        "name": name,
                        "created_at": now.isoformat(),
                    },
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
            {
                "Put": {
                    "TableName": db.table().name,
                    "Item": {
                        "PK": pk,
                        "SK": db.member_sk(owner_id),
                        "role": "owner",
                        "joined_at": now.isoformat(),
                    },
                }
            },
        ]
    )
    return Household(id=household_id, name=name, created_at=now, my_role="owner")


def get(household_id: str, my_role: Role) -> Household:
    item = db.table().get_item(
        Key={"PK": db.household_pk(household_id), "SK": db.HOUSEHOLD_META_SK}
    )["Item"]
    return Household(
        id=household_id,
        name=item["name"],
        created_at=datetime.fromisoformat(item["created_at"]),
        my_role=my_role,
    )
