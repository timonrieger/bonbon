import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import boto3
import pytest
from bonbon.handlers.households import handler
from bonbon.households import codes
from bonbon.receipts import storage
from conftest import api_request
from fakes import FakeDatabase


def test_create_and_get_household() -> None:
    status, created = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    assert status == 200
    assert created["my_role"] == "owner"

    status, household = api_request(handler, "GET", f"/households/{created['id']}")
    assert status == 200
    assert household["name"] == "WG Zürich"


def test_non_member_gets_404() -> None:
    _, created = api_request(handler, "POST", "/households", body={"name": "Familie Muster"})

    status, _ = api_request(handler, "GET", f"/households/{created['id']}", user="stranger")
    assert status == 404


def test_malformed_household_id_gets_404() -> None:
    status, _ = api_request(handler, "GET", "/households/not-a-uuid")
    assert status == 404


def test_rejects_empty_name() -> None:
    status, _ = api_request(handler, "POST", "/households", body={"name": ""})
    assert status == 422


def test_list_households_shows_only_mine() -> None:
    _, mine = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    api_request(handler, "POST", "/households", user="stranger", body={"name": "Fremd"})

    status, listed = api_request(handler, "GET", "/households")
    assert status == 200
    assert [h["id"] for h in listed["households"]] == [mine["id"]]
    assert listed["households"][0]["my_role"] == "owner"


def test_list_households_empty() -> None:
    status, listed = api_request(handler, "GET", "/households", user="newcomer")
    assert status == 200
    assert listed == {"households": []}


def test_list_members_owner_first(database: FakeDatabase) -> None:
    _, created = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    api_request(handler, "GET", "/households", user="anna", claims={"name": "Anna Muster"})
    database.add_member(UUID(created["id"]), "anna")

    status, listed = api_request(handler, "GET", f"/households/{created['id']}/members")
    assert status == 200
    assert [(m["display_name"], m["role"]) for m in listed["members"]] == [
        ("User-1", "owner"),
        ("Anna Muster", "member"),
    ]


def test_non_member_cannot_list_members() -> None:
    _, created = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    status, _ = api_request(handler, "GET", f"/households/{created['id']}/members", user="stranger")
    assert status == 404


def test_name_change_in_token_is_synced(database: FakeDatabase) -> None:
    api_request(handler, "GET", "/households", claims={"name": "Noel"})
    api_request(handler, "GET", "/households", claims={"name": "Noel N."})
    assert database.users["user-1"] == ("Noel N.", "user-1@example.ch")


def test_account_without_name_gets_email_prefix(database: FakeDatabase) -> None:
    api_request(handler, "GET", "/households", claims={"name": None, "email": "anna.m@gmx.ch"})
    assert database.users["user-1"] == ("anna.m", "anna.m@gmx.ch")


# Invite codes and joining (docs/features/04-households.md)


def household_with_invite() -> tuple[str, str]:
    """A household of user-1 and a fresh invite code for it."""
    _, created = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    status, invite = api_request(handler, "POST", f"/households/{created['id']}/invites")
    assert status == 201
    return created["id"], invite["code"]


def join(code: str, user: str = "anna") -> tuple[int, Any]:
    return api_request(handler, "POST", "/households/join", user=user, body={"code": code})


def test_create_invite_returns_code_valid_for_48_hours(database: FakeDatabase) -> None:
    household_id, code = household_with_invite()

    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", code)
    [(stored_hash, invite)] = database.invites.items()
    # Only the hash is stored, never the code itself.
    assert stored_hash == codes.code_hash(code) != code
    assert invite.household_id == UUID(household_id)
    assert invite.expires_at - datetime.now(UTC) == pytest.approx(
        timedelta(hours=48), abs=timedelta(minutes=1)
    )


def test_every_member_can_create_invites(database: FakeDatabase) -> None:
    household_id, _ = household_with_invite()
    api_request(handler, "GET", "/households", user="anna")
    database.add_member(UUID(household_id), "anna")

    status, _ = api_request(handler, "POST", f"/households/{household_id}/invites", user="anna")
    assert status == 201
    assert len(database.invites) == 2


def test_non_member_cannot_create_invites() -> None:
    household_id, _ = household_with_invite()
    status, _ = api_request(handler, "POST", f"/households/{household_id}/invites", user="stranger")
    assert status == 404


def test_join_with_code_makes_member() -> None:
    household_id, code = household_with_invite()

    status, household = join(code)
    assert status == 200
    assert (household["id"], household["my_role"]) == (household_id, "member")

    _, listed = api_request(handler, "GET", f"/households/{household_id}/members")
    assert [(m["user_id"], m["role"]) for m in listed["members"]] == [
        ("user-1", "owner"),
        ("anna", "member"),
    ]


def test_code_can_be_typed_loosely() -> None:
    _, code = household_with_invite()
    status, _ = join(f"  {code.replace('-', ' ').lower()} ")
    assert status == 200


def test_code_works_only_once() -> None:
    _, code = household_with_invite()
    join(code)
    status, _ = join(code, user="ben")
    assert status == 404


def test_expired_code_is_rejected(database: FakeDatabase) -> None:
    _, code = household_with_invite()
    database.invites[codes.code_hash(code)].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    status, _ = join(code)
    assert status == 404


def test_unknown_code_is_rejected() -> None:
    household_with_invite()
    status, body = join("AAAA-AAAA")
    assert status == 404
    assert "expired" in body["message"]


def test_member_joining_again_gets_409_and_code_stays_valid(database: FakeDatabase) -> None:
    _, code = household_with_invite()

    status, _ = join(code, user="user-1")
    assert status == 409
    assert database.join_attempts == []

    status, _ = join(code)
    assert status == 200


def test_sixth_attempt_within_an_hour_is_rejected_even_with_valid_code() -> None:
    _, code = household_with_invite()
    for _ in range(5):
        assert join("AAAA-AAAA")[0] == 404

    status, _ = join(code)
    assert status == 429
    # Other users aren't affected.
    assert join(code, user="ben")[0] == 200


def test_failed_attempts_older_than_an_hour_dont_count(database: FakeDatabase) -> None:
    _, code = household_with_invite()
    api_request(handler, "GET", "/households", user="anna")
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1, seconds=1)
    database.join_attempts = [("anna", an_hour_ago)] * 5

    status, _ = join(code)
    assert status == 200


def test_successful_joins_dont_count_as_attempts(database: FakeDatabase) -> None:
    for _ in range(6):
        _, code = household_with_invite()
        assert join(code)[0] == 200
    assert database.join_attempts == []


def test_join_rejects_empty_code() -> None:
    status, _ = join("")
    assert status == 422


def test_creating_an_invite_removes_used_and_expired_codes(database: FakeDatabase) -> None:
    household_id, used = household_with_invite()
    join(used)
    _, expired = api_request(handler, "POST", f"/households/{household_id}/invites")
    database.invites[codes.code_hash(expired["code"])].expires_at = datetime.now(UTC)

    _, fresh = api_request(handler, "POST", f"/households/{household_id}/invites")
    assert list(database.invites) == [codes.code_hash(fresh["code"])]


# Leaving, removing members and handing over the owner role (docs/features/04-households.md)


def household_of(*members: str) -> str:
    """A household owned by user-1 with the given members, who joined in this order."""
    _, created = api_request(handler, "POST", "/households", body={"name": "WG Zürich"})
    for member in members:
        _, invite = api_request(handler, "POST", f"/households/{created['id']}/invites")
        assert join(invite["code"], user=member)[0] == 200
    return created["id"]


def members(household_id: str, database: FakeDatabase) -> list[tuple[str, str]]:
    return [(m.user_id, m.role) for m in database.list_members(household_id)]


def leave(household_id: str, user: str) -> int:
    return api_request(handler, "DELETE", f"/households/{household_id}/members/me", user=user)[0]


def receipts_bucket() -> Any:
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket=os.environ["RECEIPTS_BUCKET"])
    return s3


def keys(s3: Any) -> list[str]:
    listed = s3.list_objects_v2(Bucket=os.environ["RECEIPTS_BUCKET"])
    return sorted(obj["Key"] for obj in listed.get("Contents", []))


def test_member_leaves_and_loses_access(database: FakeDatabase) -> None:
    household_id = household_of("anna")

    assert leave(household_id, "anna") == 204
    assert members(household_id, database) == [("user-1", "owner")]
    status, _ = api_request(handler, "GET", f"/households/{household_id}", user="anna")
    assert status == 404


def test_owner_cannot_leave_while_others_remain(database: FakeDatabase) -> None:
    household_id = household_of("anna")

    assert leave(household_id, "user-1") == 409
    assert members(household_id, database) == [("user-1", "owner"), ("anna", "member")]


def test_non_member_cannot_leave() -> None:
    household_id = household_of()
    assert leave(household_id, "stranger") == 404


def test_last_member_leaving_deletes_household_receipts_and_files(database: FakeDatabase) -> None:
    s3 = receipts_bucket()
    household_id = household_of()
    other_id = household_of()
    receipt_id = database.add_receipt(UUID(household_id), "user-1", status="done")
    other_key = f"households/{other_id}/receipts/{uuid4()}"
    for key in (
        f"households/{household_id}/receipts/{receipt_id}",
        f"textract-results/{household_id}/{receipt_id}.json",
        other_key,
    ):
        s3.put_object(Bucket=os.environ["RECEIPTS_BUCKET"], Key=key, Body=b"x")

    assert leave(household_id, "user-1") == 204
    assert UUID(household_id) not in database.households
    assert database.receipts == {}
    assert keys(s3) == [other_key]
    status, _ = api_request(handler, "GET", f"/households/{household_id}")
    assert status == 404


def test_household_is_deleted_even_if_s3_fails(database: FakeDatabase) -> None:
    # No bucket: S3 answers NoSuchBucket, the request still succeeds.
    household_id = household_of()

    assert leave(household_id, "user-1") == 204
    assert UUID(household_id) not in database.households


def test_partial_s3_failure_counts_only_deleted_files(monkeypatch: pytest.MonkeyPatch) -> None:
    # delete_objects answers 200 and lists the objects it couldn't delete under Errors.
    s3 = receipts_bucket()
    household_id = household_of()
    refused = f"households/{household_id}/receipts/{uuid4()}"
    for key in (refused, f"households/{household_id}/receipts/{uuid4()}"):
        s3.put_object(Bucket=os.environ["RECEIPTS_BUCKET"], Key=key, Body=b"x")
    client = storage._s3_cleanup()
    real_delete = client.delete_objects

    def delete_objects(**kwargs: Any) -> Any:
        objects = kwargs["Delete"]["Objects"]
        kwargs["Delete"]["Objects"] = [o for o in objects if o["Key"] != refused]
        response = real_delete(**kwargs)
        response["Errors"] = [{"Key": refused, "Code": "AccessDenied"}]
        return response

    monkeypatch.setattr(client, "delete_objects", delete_objects)

    assert storage.delete_household_files(household_id) == (1, [refused])
    assert keys(s3) == [refused]


def test_owner_removes_member(database: FakeDatabase) -> None:
    household_id = household_of("anna", "ben")

    status, _ = api_request(handler, "DELETE", f"/households/{household_id}/members/anna")
    assert status == 204
    assert members(household_id, database) == [("user-1", "owner"), ("ben", "member")]


def test_member_cannot_remove_others(database: FakeDatabase) -> None:
    household_id = household_of("anna", "ben")

    status, _ = api_request(
        handler, "DELETE", f"/households/{household_id}/members/ben", user="anna"
    )
    assert status == 403
    assert ("ben", "member") in members(household_id, database)


def test_removing_oneself_is_leaving(database: FakeDatabase) -> None:
    household_id = household_of("anna")

    path = f"/households/{household_id}/members"
    assert api_request(handler, "DELETE", f"{path}/anna", user="anna")[0] == 204
    assert api_request(handler, "DELETE", f"{path}/user-1")[0] == 204
    assert UUID(household_id) not in database.households


def test_removing_a_non_member_gets_404() -> None:
    household_id = household_of()
    api_request(handler, "GET", "/households", user="stranger")

    status, _ = api_request(handler, "DELETE", f"/households/{household_id}/members/stranger")
    assert status == 404


def test_non_member_cannot_remove_anyone() -> None:
    household_id = household_of("anna")
    status, _ = api_request(
        handler, "DELETE", f"/households/{household_id}/members/anna", user="stranger"
    )
    assert status == 404


def transfer(household_id: str, to: str, user: str = "user-1") -> tuple[int, Any]:
    return api_request(
        handler, "PUT", f"/households/{household_id}/owner", user=user, body={"user_id": to}
    )


def test_owner_hands_over_and_can_then_leave(database: FakeDatabase) -> None:
    household_id = household_of("anna", "ben")

    status, listed = transfer(household_id, "ben")
    assert status == 200
    assert [(m["user_id"], m["role"]) for m in listed["members"]] == [
        ("ben", "owner"),
        ("user-1", "member"),
        ("anna", "member"),
    ]
    assert leave(household_id, "user-1") == 204
    assert members(household_id, database) == [("ben", "owner"), ("anna", "member")]


def test_member_cannot_hand_over(database: FakeDatabase) -> None:
    household_id = household_of("anna")

    assert transfer(household_id, "anna", user="anna")[0] == 403
    assert members(household_id, database) == [("user-1", "owner"), ("anna", "member")]


def test_hand_over_to_non_member_gets_404() -> None:
    household_id = household_of()
    assert transfer(household_id, "stranger")[0] == 404


def test_hand_over_to_oneself_changes_nothing(database: FakeDatabase) -> None:
    household_id = household_of("anna")

    status, _ = transfer(household_id, "user-1")
    assert status == 200
    assert members(household_id, database) == [("user-1", "owner"), ("anna", "member")]


def test_non_member_cannot_hand_over() -> None:
    household_id = household_of("anna")
    assert transfer(household_id, "anna", user="stranger")[0] == 404
