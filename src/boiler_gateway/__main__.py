"""Run the gateway: `python -m boiler_gateway` (settings from the environment or `.env`)."""

import logging
import os

import uvicorn

from boiler_gateway.audit import AuditLog
from boiler_gateway.config import Settings
from boiler_gateway.device import EsphomeDevice
from boiler_gateway.server import build_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # In production the service manager supplies the environment and sets
    # GATEWAY_ENV_FILE to an empty value, so no file next to the code is read.
    env_file = os.environ.get("GATEWAY_ENV_FILE", ".env") or None
    settings = Settings(_env_file=env_file)
    audit = AuditLog(settings.gateway_audit_db)
    app = build_app(settings, EsphomeDevice(settings), audit)
    try:
        # proxy_headers off: the gateway trusts no forwarded headers for decisions.
        uvicorn.run(
            app,
            host=settings.gateway_bind_host,
            port=settings.gateway_port,
            proxy_headers=False,
            server_header=False,
            # Clients hold long-lived streams (subscriptions/listen); don't wait forever
            # for them on shutdown. They reconnect.
            timeout_graceful_shutdown=5,
            log_level="info",
        )
    finally:
        audit.close()


if __name__ == "__main__":
    main()
