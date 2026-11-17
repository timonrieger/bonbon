"""Checks on template.yaml that a deploy catches late, or for prod-only parts never on dev."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[3] / "template.yaml"


class Loader(yaml.SafeLoader):
    pass


# Keep CloudFormation tags as {"!Tag": value}, so tests can compare them.
Loader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: {
        f"!{suffix}": (
            loader.construct_scalar(node)
            if isinstance(node, yaml.ScalarNode)
            else loader.construct_sequence(node, deep=True)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_mapping(node, deep=True)
        )
    },
)


@pytest.fixture(scope="module")
def template() -> dict[str, Any]:
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)


def unquote(origin: Any) -> Any:
    """API Gateway header values carry extra single quotes; the bucket and the env var don't."""
    if isinstance(origin, str):
        return origin.strip("'")
    if isinstance(origin, dict):
        return {k: unquote(v) for k, v in origin.items()}
    if isinstance(origin, list):
        return [unquote(v) for v in origin]
    return origin


def test_every_cors_origin_is_the_same(template: dict[str, Any]) -> None:
    """API Gateway, the Lambdas and the receipts bucket must allow exactly the same origin."""
    resources = template["Resources"]
    api = resources["Api"]["Properties"]
    origins = {
        "Globals ALLOWED_ORIGIN": template["Globals"]["Function"]["Environment"]["Variables"][
            "ALLOWED_ORIGIN"
        ],
        "Api Cors": unquote(api["Cors"]["AllowOrigin"]),
        **{
            f"Api {name}": unquote(
                response["ResponseParameters"]["Headers"]["Access-Control-Allow-Origin"]
            )
            for name, response in api["GatewayResponses"].items()
        },
        "ReceiptsBucket CORS": resources["ReceiptsBucket"]["Properties"]["CorsConfiguration"][
            "CorsRules"
        ][0]["AllowedOrigins"][0],
    }
    expected = origins["Globals ALLOWED_ORIGIN"]
    assert expected == {
        "!If": ["IsProd", {"!Sub": "https://main.${WebApp.DefaultDomain}"}, "http://localhost:5173"]
    }
    for where, origin in origins.items():
        assert origin == expected, f"{where} allows a different origin"


def test_web_hosting_is_prod_only(template: dict[str, Any]) -> None:
    """Dev stacks have no hosted frontend, so nothing may reference it without the condition."""
    for name, resource in template["Resources"].items():
        if resource["Type"].startswith("AWS::Amplify::"):
            assert resource.get("Condition") == "IsProd", f"{name} must be prod-only"
    for name in ("WebUrl", "WebAppId"):
        assert template["Outputs"][name].get("Condition") == "IsProd"


@pytest.mark.parametrize(
    ("path", "serves_index"),
    [
        ("/", True),
        ("/households", True),
        ("/households/0b8e6b9a-3c1f-4e1e-9a57-0f6a1c2b3d4e/receipts", True),
        ("/assets/index-BX3k9a1F.js", False),
        ("/assets/index-C1d2e3F4.css", False),
        ("/favicon.ico", False),
    ],
)
def test_spa_rewrite_rule(template: dict[str, Any], path: str, serves_index: bool) -> None:
    """Amplify's rewrite must send app routes to index.html but leave real files alone."""
    rule = template["Resources"]["WebApp"]["Properties"]["CustomRules"][0]
    assert (rule["Target"], rule["Status"]) == ("/index.html", "200")
    pattern = re.fullmatch(r"</(.*)/>", rule["Source"])
    assert pattern, "Amplify regex rules are written as </regex/>"
    assert bool(re.search(pattern[1], path)) is serves_index
