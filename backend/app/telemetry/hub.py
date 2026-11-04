"""WebSocket fan-out with per-client coalescing.

Ingestion may produce many updates per second per key; each client receives
at most one value per key per flush interval (latest wins). History is written
independently, so coalescing never loses stored data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

FLUSH_INTERVAL_S = 0.25
MAX_PENDING_KEYS = 20_000  # per client; beyond this the oldest keys are dropped from the frame


@dataclass(eq=False)
class Subscriber:
    org_id: str
    factory_id: str | None = None
    asset_ids: set[str] | None = None
    pending: dict[tuple[str, str], list[Any]] = field(default_factory=dict)
    # Discrete events (alerts, command updates) are never coalesced.
    events: list[dict[str, Any]] = field(default_factory=list)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    dropped: int = 0

    def wants(self, org_id: str, factory_id: str, asset_id: str) -> bool:
        return (
            org_id == self.org_id
            and self.factory_id == factory_id
            and (self.asset_ids is None or asset_id in self.asset_ids)
        )

    def offer(self, key: tuple[str, str], frame: list[Any]) -> None:
        if key not in self.pending and len(self.pending) >= MAX_PENDING_KEYS:
            self.dropped += 1
            return
        self.pending[key] = frame
        self.wake.set()

    def push_event(self, event: dict[str, Any]) -> None:
        if len(self.events) < 1000:
            self.events.append(event)
        self.wake.set()

    def take_events(self) -> list[dict[str, Any]]:
        ev, self.events = self.events, []
        return ev

    def take(self) -> list[list[Any]]:
        frames = list(self.pending.values())
        self.pending.clear()
        self.wake.clear()
        return frames


class Hub:
    def __init__(self) -> None:
        self.subscribers: set[Subscriber] = set()

    def add(self, s: Subscriber) -> None:
        self.subscribers.add(s)

    def remove(self, s: Subscriber) -> None:
        self.subscribers.discard(s)

    def publish_event(self, org_id: str, factory_id: str, event: dict[str, Any]) -> None:
        for s in self.subscribers:
            if s.org_id == org_id and s.factory_id == factory_id:
                s.push_event(event)

    def publish(self, org_id: str, factory_id: str, asset_id: str, measurement: str, frame: list[Any]) -> None:
        for s in self.subscribers:
            if s.wants(org_id, factory_id, asset_id):
                s.offer((asset_id, measurement), frame)
