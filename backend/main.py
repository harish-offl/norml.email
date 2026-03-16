import argparse
import os

import django
from django.conf import settings
from django.core.management import execute_from_command_line

from backend.campaign_runner import run_campaign


def main():
    # Ensure Django is configured
    if not settings.configured:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.app.settings")
        django.setup()

    parser = argparse.ArgumentParser(description="Email automation utility")
    parser.add_argument("--serve", action="store_true", help="start the Django development server")
    parser.add_argument("--migrate", action="store_true", help="run database migrations")
    args = parser.parse_args()

    if args.migrate:
        execute_from_command_line(['manage.py', 'migrate'])
    elif args.serve:
        execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])
    else:
        run_campaign()


if __name__ == "__main__":
    main()
