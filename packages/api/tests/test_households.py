from bonbon.handlers.households import handler
from conftest import api_request


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


def test_rejects_empty_name() -> None:
    status, _ = api_request(handler, "POST", "/households", body={"name": ""})
    assert status == 422
