from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from bonbon.households.routes import router
from bonbon.http import make_resolver

logger = Logger()
app = make_resolver(router)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
