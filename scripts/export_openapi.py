"""Export the OpenAPI schema for validation."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    out = Path("docs/openapi.json")
    out.write_text(json.dumps(schema, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
