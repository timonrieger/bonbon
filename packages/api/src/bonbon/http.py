"""Shared API Gateway resolver setup for all API functions."""

import os

from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.event_handler.api_gateway import Router


def make_resolver(*routers: Router) -> APIGatewayRestResolver:
    # Must match the API's Cors.AllowOrigin in template.yaml: with proxy integration the browser
    # sees this header, not API Gateway's. The default only matters outside Lambda (openapi.py).
    origin = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")
    app = APIGatewayRestResolver(enable_validation=True, cors=CORSConfig(allow_origin=origin))
    for router in routers:
        app.include_router(router)
    return app
