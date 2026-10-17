"""Serverless entrypoint (Vercel): exposes the OmniKnow FastAPI app as ``app``.

Every request is answered synchronously, so nothing depends on background threads surviving
between invocations. The packaged sample corpus (Markdown, CSV, PDF and image metadata) is
bundled through ``includeFiles`` in ``vercel.json``. Unless API keys are configured the
deployment is a public demo: packaged corpus and the offline mock provider only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omniknow.api import create_app  # noqa: E402  (path setup must run first)

app = create_app()
