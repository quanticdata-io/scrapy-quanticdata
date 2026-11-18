"""Send Scrapy requests through the QuanticData Web Unlocker or scrape API."""

from ._version import __version__
from .middleware import (
    META_KEY,
    RESULT_META_KEY,
    QuanticDataAPIError,
    QuanticDataConfigError,
    QuanticDataError,
    QuanticDataMiddleware,
)

__all__ = [
    "META_KEY",
    "RESULT_META_KEY",
    "QuanticDataAPIError",
    "QuanticDataConfigError",
    "QuanticDataError",
    "QuanticDataMiddleware",
    "__version__",
]
