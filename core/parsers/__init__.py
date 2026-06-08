"""
Parsers package — auto-imports all parser modules to trigger
@register_parser decorator registration at import time.
"""

from . import adidas  # noqa: F401
from . import nike    # noqa: F401
from . import nb      # noqa: F401
