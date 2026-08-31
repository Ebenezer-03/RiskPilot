"""Loads apps/web/.env.local (pulled via `vercel env pull`) before the test
session starts, so `@pytest.mark.integration` tests that need real Supabase
credentials actually run instead of always skipping. Does nothing if the
file isn't present (e.g. a fresh clone, or CI without it) - integration
tests degrade to skipped in that case, same as before this existed.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.local")
