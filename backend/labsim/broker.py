"""Local MQTT broker for the lab (aMQTT). For production use Mosquitto/EMQX with auth + TLS."""

import asyncio
import logging
import os

from amqtt.broker import Broker


async def main() -> None:
    bind = os.environ.get("MQTT_BIND", "127.0.0.1:1883")
    broker = Broker({"listeners": {"default": {"type": "tcp", "bind": bind, "max_connections": 200}}})
    await broker.start()
    logging.getLogger("labsim.broker").info("MQTT broker listening on %s", bind)
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("amqtt").setLevel(logging.WARNING)
    asyncio.run(main())
