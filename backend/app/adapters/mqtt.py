"""MQTT adapter (aiomqtt), push-based.

Point syntax:  <topic>[#<json.path>]
  plant/hall-a/tt-101#temp       JSON payload {"temp": 64.2, "ts": 1730000000000, "seq": 17}
  plant/hall-a/tt-101            raw payload "64.2"
Optional payload fields `ts` (epoch ms or ISO 8601) and `seq` are used for
timestamps and duplicate detection.

Commands publish to the control-mapped topic as JSON {"value": ..., "command_id": ...}.
A broker acknowledgement is NOT device confirmation; the control engine verifies
the outcome through telemetry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import aiomqtt

from app.adapters.base import CommandAck, DeviceAdapter, DeviceStatus, Sample
from app.schemas.devices import ConfigField, DiscoveredPoint

log = logging.getLogger("twin.mqtt")


def split_point(point: str) -> tuple[str, list[str]]:
    topic, _, path = point.partition("#")
    path = path[2:] if path.startswith("$.") else path
    return topic, [p for p in path.split(".") if p] if path else []


def extract(payload: Any, path: list[str]) -> Any:
    cur = payload
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return None
    return cur


def parse_ts(v: Any) -> datetime | None:
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, UTC)
        if isinstance(v, str):
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=UTC)
    except (ValueError, OSError, OverflowError):
        return None
    return None


def decode_payload(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return float(text)
        except ValueError:
            return text


class MqttAdapter(DeviceAdapter):
    key = "mqtt"
    name = "MQTT"
    description = "Subscribe to broker topics (JSON or plain payloads); publish commands."
    config_schema = [
        ConfigField(key="host", label="Broker host", type="string", required=True),
        ConfigField(key="port", label="Port", type="integer", default=1883, help="1883 plain, 8883 TLS"),
        ConfigField(key="topic_filter", label="Discovery topic filter", type="string", default="#",
                    help="Used by 'Discover' to list topics, e.g. plant/#"),
        ConfigField(key="qos", label="QoS", type="enum", default="1", options=["0", "1"]),
        ConfigField(key="tls", label="Use TLS", type="boolean", default=False),
        ConfigField(key="client_id", label="Client ID", type="string", default="", help="Blank = generated"),
        ConfigField(key="username", label="Username", type="string", secret=True),
        ConfigField(key="password", label="Password", type="string", secret=True),
    ]
    supports_discovery = True
    supports_write = True
    push = True

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any] | None = None):
        super().__init__(config, credentials)
        self._task: asyncio.Task | None = None
        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._messages = 0
        self._errors = 0
        self._last_error = ""
        self._connected_since: float | None = None

    def _client_kwargs(self, suffix: str = "") -> dict[str, Any]:
        cid = self.config.get("client_id") or f"twin-{uuid.uuid4().hex[:10]}"
        kw: dict[str, Any] = {
            "hostname": self.config["host"], "port": int(self.config.get("port", 1883)),
            "identifier": cid + suffix, "timeout": 5,
        }
        if self.credentials.get("username"):
            kw["username"] = self.credentials["username"]
            kw["password"] = self.credentials.get("password")
        if self.config.get("tls"):
            kw["tls_context"] = ssl.create_default_context()
        return kw

    async def connect(self) -> None:  # connection is managed by start()
        return None

    async def disconnect(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._connected = False

    async def test_connection(self) -> tuple[bool, str]:
        t0 = time.perf_counter()
        try:
            async with aiomqtt.Client(**self._client_kwargs("-test")):
                pass
            return True, f"Connected to broker {self.config['host']}:{self.config.get('port', 1883)} in {(time.perf_counter() - t0) * 1000:.0f} ms"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    async def start(self, points: list[str], on_samples: Callable[[list[Sample]], None]) -> None:
        by_topic: dict[str, list[tuple[str, list[str]]]] = {}
        for p in points:
            topic, path = split_point(p)
            by_topic.setdefault(topic, []).append((p, path))
        qos = int(self.config.get("qos", 1))

        async def run():
            backoff = 1.0
            while True:
                try:
                    async with aiomqtt.Client(**self._client_kwargs()) as client:
                        self._client = client
                        self._connected = True
                        self._connected_since = time.time()
                        backoff = 1.0
                        for topic in by_topic:
                            await client.subscribe(topic, qos=qos)
                        async for msg in client.messages:
                            self._messages += 1
                            payload = decode_payload(msg.payload)
                            ts = parse_ts(extract(payload, ["ts"])) if isinstance(payload, dict) else None
                            seq = payload.get("seq") if isinstance(payload, dict) and isinstance(payload.get("seq"), int) else None
                            now = datetime.now(UTC)
                            samples = []
                            for point, path in by_topic.get(str(msg.topic), []):
                                v = extract(payload, path) if path else payload
                                samples.append(Sample(point, v, ts or now, "good" if v is not None else "bad", seq))
                            if samples:
                                on_samples(samples)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - keep reconnecting
                    self._errors += 1
                    self._last_error = f"{type(e).__name__}: {e}"
                    log.warning("MQTT %s: %s; retrying in %.0fs", self.config.get("host"), self._last_error, backoff)
                finally:
                    self._connected = False
                    self._client = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

        self._task = asyncio.create_task(run(), name=f"mqtt-{self.config.get('host')}")

    async def read_telemetry(self, points: list[str]) -> list[Sample]:
        return []  # push adapter

    async def write_command(self, point: str, value: Any) -> CommandAck:
        topic, _ = split_point(point)
        body = json.dumps({"value": value, "command_id": uuid.uuid4().hex, "ts": int(time.time() * 1000)})
        if self._client is not None and self._connected:
            await self._client.publish(topic, body, qos=1)
        else:
            async with aiomqtt.Client(**self._client_kwargs("-cmd")) as c:
                await c.publish(topic, body, qos=1)
        return CommandAck(True, f"Published to {topic} (broker accepted; device outcome verified via telemetry)")

    async def discover_capabilities(self) -> list[DiscoveredPoint]:
        seen: dict[str, DiscoveredPoint] = {}
        try:
            async with aiomqtt.Client(**self._client_kwargs("-disc")) as client:
                await client.subscribe(self.config.get("topic_filter") or "#")
                async with asyncio.timeout(4):
                    async for msg in client.messages:
                        payload = decode_payload(msg.payload)
                        t = str(msg.topic)
                        if isinstance(payload, dict):
                            for k, v in payload.items():
                                if k in ("ts", "seq") or isinstance(v, (dict, list)):
                                    continue
                                seen[f"{t}#{k}"] = DiscoveredPoint(
                                    point=f"{t}#{k}", label=f"{k} = {v}", suggested_measurement=k,
                                    data_type="number" if isinstance(v, (int, float)) and not isinstance(v, bool) else "string")
                        else:
                            seen[t] = DiscoveredPoint(point=t, label=f"{t} = {payload}",
                                                      data_type="number" if isinstance(payload, float) else "string")
                        if len(seen) > 300:
                            break
        except TimeoutError:
            pass
        return sorted(seen.values(), key=lambda p: p.point)

    async def get_device_status(self) -> DeviceStatus:
        return DeviceStatus(connected=self._connected, detail=self._last_error,
                            diagnostics={"messages": self._messages, "errors": self._errors})
