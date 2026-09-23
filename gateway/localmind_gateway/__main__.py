"""Run the gateway: `python -m localmind_gateway` (settings come from LMG_* environment variables)."""
from __future__ import annotations

import logging


def main() -> None:
    import uvicorn

    from .app import create_app
    from .settings import Settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info", proxy_headers=True)


if __name__ == "__main__":
    main()
