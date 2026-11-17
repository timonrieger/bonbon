"""Category of a receipt item (docs/features/02-extraction-categorization.md).

Placeholder until the keyword rule table (#23): every item gets the fallback category. The
database worker only calls categorize(), so #23 changes this module and nothing else.
"""

# Exists since migration 0002; items that match no rule get it.
FALLBACK = "Sonstiges"


def categorize(item_name: str) -> str:
    """Name of the category in the `categories` table for an item."""
    return FALLBACK
