from ha_archive_search.engine import (
    Match,
    SearchResult,
    main,
)

# Internal typed model — exposed for testability.
# No backward compatibility guarantee before v1.0.
from ha_archive_search.webapp import (
    Hit,
    FileResult,
    VersionResult,
    Summary,
    ParsedResults,
)

from ha_archive_search._version import __version__

__all__ = [
    "Match",
    "SearchResult",
    "main",
    "__version__",
    # Internal model — see comment above.
    "Hit",
    "FileResult",
    "VersionResult",
    "Summary",
    "ParsedResults",
]
