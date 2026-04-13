import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

from backend.app.database import initialize_database
from backend.campaign_runner import run_campaign


def main():
    parser = argparse.ArgumentParser(description="Email automation utility")
    parser.add_argument("--serve", action="store_true", help="start the FastAPI development server")
    parser.add_argument("--migrate", action="store_true", help="initialize the SQLite schema")
    args = parser.parse_args()

    if args.migrate:
        initialize_database()
    elif args.serve:
        import uvicorn

        host = os.getenv("FASTAPI_SERVE_HOST", os.getenv("DJANGO_SERVE_HOST", "127.0.0.1"))
        port = int(os.getenv("FASTAPI_SERVE_PORT", os.getenv("DJANGO_SERVE_PORT", "8000")))
        uvicorn.run("backend.app.main:app", host=host, port=port, reload=False)
    else:
        initialize_database()
        run_campaign()


if __name__ == "__main__":
    main()
