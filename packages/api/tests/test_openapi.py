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
