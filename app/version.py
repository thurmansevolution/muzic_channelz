"""Application version identifiers used for runtime diagnostics."""
from __future__ import annotations

import os

# Keep backend version explicit in logs so deployment mismatches are obvious.
APP_VERSION = (os.environ.get("MUZIC_APP_VERSION") or "stream-fix-v15").strip() or "stream-fix-v15"

# Optional frontend build string if injected at deploy time.
FRONTEND_VERSION = (os.environ.get("MUZIC_FRONTEND_VERSION") or "").strip()

