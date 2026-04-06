from pathlib import Path

from dotenv import load_dotenv

# Project root (one level above this backend package)
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR    = BASE_DIR / "data"
ENV_FILE    = BASE_DIR / ".env"


def load_project_env(override: bool = True) -> None:
    """Load the project's .env file, overriding any stale system env vars."""
    if ENV_FILE.exists():
        load_dotenv(dotenv_path=ENV_FILE, override=override)
    else:
        import warnings
        warnings.warn(f".env file not found at {ENV_FILE}. SMTP config may be missing.")
