"""Print the OpenAPI spec of all routes. Run via `mise run generate`, never by hand."""

from bonbon.households.routes import router as households
from bonbon.http import make_resolver

# Every router must be listed here, otherwise its endpoints are missing from the frontend client.
ROUTERS = [households]

if __name__ == "__main__":
    print(make_resolver(*ROUTERS).get_openapi_json_schema(title="Bonbon API", version="0.1.0"))
