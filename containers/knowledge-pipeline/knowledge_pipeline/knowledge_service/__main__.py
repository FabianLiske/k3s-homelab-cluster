"""knowledge-service Entry-Point: REST + MCP via uvicorn (PORT)."""

from .api import main

if __name__ == "__main__":
    raise SystemExit(main())
