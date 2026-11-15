from uuid import UUID

from bonbon.handlers.households import handler
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
