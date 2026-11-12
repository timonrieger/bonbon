import re

from bonbon.http import make_resolver
from bonbon.openapi import ROUTERS


def test_every_route_has_a_readable_operation_id() -> None:
    """operationId becomes the frontend function name (getHousehold), so set it explicitly."""
    spec = make_resolver(*ROUTERS).get_openapi_schema(title="Bonbon API", version="0")
    assert spec.paths
    for path, item in spec.paths.items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = getattr(item, method)
            if operation is not None:
                assert re.fullmatch(r"[a-z][a-zA-Z]+", operation.operationId or ""), (
                    f"{method.upper()} {path}: add operation_id='camelCaseName' to the route"
                )


def test_household_routes_document_404() -> None:
    """Non-members get 404 from require_membership; the frontend client should know about it."""
    spec = make_resolver(*ROUTERS).get_openapi_schema(title="Bonbon API", version="0")
    assert spec.paths
    for path, item in spec.paths.items():
        if "{household_id}" not in path:
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = getattr(item, method)
            if operation is not None:
                assert operation.responses and 404 in {int(c) for c in operation.responses}, (
                    f"{method.upper()} {path}: add responses=MEMBERSHIP_RESPONSES to the route"
                )
                ok = operation.responses.get(200) or operation.responses.get("200")
                missing = operation.responses.get(404) or operation.responses.get("404")
                assert ok and ok.content and missing and missing.content
                # The 404 must describe the error body, not the route's return model.
                assert (
                    ok.content["application/json"].schema_
                    != missing.content["application/json"].schema_
                )
