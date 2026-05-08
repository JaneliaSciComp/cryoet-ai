"""Allow ``python -m cryoet_catalog ...`` to dispatch to the CLI."""
from __future__ import annotations

import sys

from cryoet_catalog.cli import main

if __name__ == "__main__":
    sys.exit(main())
