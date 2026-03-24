#!/usr/bin/env python
import os
import sys

from backend.main import main


if __name__ == "__main__":
    translated_args = []
    args = sys.argv[1:]
    idx = 0

    while idx < len(args):
        arg = args[idx]
        if arg == "migrate":
            translated_args.append("--migrate")
        elif arg in {"runserver", "serve"}:
            translated_args.append("--serve")
        elif arg == "--host" and idx + 1 < len(args):
            os.environ["FASTAPI_SERVE_HOST"] = args[idx + 1]
            idx += 1
        elif arg == "--port" and idx + 1 < len(args):
            os.environ["FASTAPI_SERVE_PORT"] = args[idx + 1]
            idx += 1
        elif ":" in arg:
            host, _, port = arg.partition(":")
            if host:
                os.environ["FASTAPI_SERVE_HOST"] = host
            if port.isdigit():
                os.environ["FASTAPI_SERVE_PORT"] = port
        else:
            translated_args.append(arg)
        idx += 1

    sys.argv = [sys.argv[0], *translated_args]
    main()
