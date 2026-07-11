"""
Package init: load the project's .env once, on first import of anything under
`app`, before any module reads os.getenv. override=True so a value in
backend/.env wins over an empty/stale system env var. Previously each of
main.py/auth.py/supabase.py resolved and loaded this same file itself.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)
