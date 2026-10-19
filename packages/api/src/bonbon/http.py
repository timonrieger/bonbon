"""Shared API Gateway resolver setup for all API functions."""

from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.event_handler.api_gateway import Router


def make_resolver(*routers: Router) -> APIGatewayRestResolver:
    app = APIGatewayRestResolver(enable_validation=True, cors=CORSConfig(allow_origin="*"))
    for router in routers:
        app.include_router(router)
    return app
