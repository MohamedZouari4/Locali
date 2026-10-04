"""Writes the backend's OpenAPI description to desktop/electron/api/openapi.json, the contract the
desktop API client is generated from. With --check, exits 1 instead if the committed file is out of date.

Run from the backend folder: uv run python -m scripts.export_openapi [--check]
"""

import argparse
import json
import os
import sys

from app.api.main import app
from app.core.config import REPO_ROOT

OUTPUT = os.path.join(REPO_ROOT, "desktop", "electron", "api", "openapi.json")


def render():
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is out of date")
    args = parser.parse_args()
    expected = render()

    if args.check:
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            current = None
        if current != expected:
            print(
                f"{OUTPUT} is out of date. Run `uv run python -m scripts.export_openapi` in backend/, "
                "then `npm run generate:api` in desktop/.",
                file=sys.stderr,
            )
            return 1
        print("openapi.json is up to date")
        return 0

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(expected)
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
