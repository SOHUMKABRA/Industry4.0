"""Production entry point: one platform process listening on several ports.

The telemetry runtime and control engine keep live state in memory, so the
platform must run as a single process (no uvicorn --workers). Several listen
addresses are served by that one process.

  PLATFORM_LISTEN="0.0.0.0:8000,0.0.0.0:5173" python serve.py
"""

import asyncio
import logging
import os
import socket

import uvicorn


def bind(addr: str) -> socket.socket:
    host, port = addr.rsplit(":", 1)
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, int(port)))
    s.listen(2048)
    s.set_inheritable(True)
    return s


def main() -> None:
    addrs = [a.strip() for a in os.environ.get("PLATFORM_LISTEN", "127.0.0.1:8000").split(",") if a.strip()]
    sockets = [bind(a) for a in addrs]
    config = uvicorn.Config(
        "app.main:app", proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        timeout_keep_alive=30, ws_ping_interval=20, ws_ping_timeout=20, log_level="info", access_log=False,
    )
    server = uvicorn.Server(config)
    logging.getLogger("twin").info("Listening on %s", ", ".join(addrs))
    asyncio.run(server.serve(sockets=sockets))


if __name__ == "__main__":
    main()
