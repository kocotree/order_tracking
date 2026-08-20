import argparse
import json
from pathlib import Path

from app.main import create_app

OUTPUT = Path("openapi/openapi.json")
DUMMY_DATABASE_URL = "mysql+pymysql://openapi:openapi@127.0.0.1:3306/openapi"


def rendered_openapi() -> str:
    app = create_app(database_url=DUMMY_DATABASE_URL)
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_openapi()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            print(f"OpenAPI file is stale: {OUTPUT}")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
