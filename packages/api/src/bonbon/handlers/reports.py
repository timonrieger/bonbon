from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from bonbon.http import make_resolver
from bonbon.reports.routes import router

logger = Logger()
app = make_resolver(router)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
