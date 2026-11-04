"""Minimal Modbus TCP server (slave) for the lab PLC.

Implements function codes 1, 2, 3, 4, 5, 6, 15, 16 with standard exception
responses. Independent of any Modbus library so the platform's client
(pymodbus) is exercised against a separate implementation.
"""

from __future__ import annotations

import asyncio
import logging
import struct

log = logging.getLogger("labsim.modbus")

ILLEGAL_FUNCTION, ILLEGAL_ADDRESS, ILLEGAL_VALUE = 1, 2, 3


class DataStore:
    def __init__(self, coils: int = 64, discrete: int = 64, holding: int = 128, inputs: int = 64):
        self.co = [False] * coils
        self.di = [False] * discrete
        self.hr = [0] * holding
        self.ir = [0] * inputs


def _pack_bits(bits: list[bool]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


class ModbusTcpSlave:
    def __init__(self, store: DataStore, unit_ids: set[int] | None = None):
        self.store = store
        self.unit_ids = unit_ids or {1}
        self.server: asyncio.base_events.Server | None = None
        self.requests = 0

    def handle_pdu(self, pdu: bytes) -> bytes:
        fc = pdu[0]
        s = self.store
        try:
            if fc in (1, 2, 3, 4):
                addr, qty = struct.unpack(">HH", pdu[1:5])
                table = {1: s.co, 2: s.di, 3: s.hr, 4: s.ir}[fc]
                limit = 2000 if fc in (1, 2) else 125
                if not 1 <= qty <= limit:
                    return bytes([fc | 0x80, ILLEGAL_VALUE])
                if addr + qty > len(table):
                    return bytes([fc | 0x80, ILLEGAL_ADDRESS])
                vals = table[addr:addr + qty]
                if fc in (1, 2):
                    data = _pack_bits(vals)
                else:
                    data = b"".join(struct.pack(">H", v & 0xFFFF) for v in vals)
                return bytes([fc, len(data)]) + data
            if fc == 5:
                addr, val = struct.unpack(">HH", pdu[1:5])
                if val not in (0x0000, 0xFF00):
                    return bytes([fc | 0x80, ILLEGAL_VALUE])
                if addr >= len(s.co):
                    return bytes([fc | 0x80, ILLEGAL_ADDRESS])
                s.co[addr] = val == 0xFF00
                return pdu[:5]
            if fc == 6:
                addr, val = struct.unpack(">HH", pdu[1:5])
                if addr >= len(s.hr):
                    return bytes([fc | 0x80, ILLEGAL_ADDRESS])
                s.hr[addr] = val
                return pdu[:5]
            if fc == 15:
                addr, qty, _n = struct.unpack(">HHB", pdu[1:6])
                if addr + qty > len(s.co):
                    return bytes([fc | 0x80, ILLEGAL_ADDRESS])
                raw = pdu[6:]
                for i in range(qty):
                    s.co[addr + i] = bool(raw[i // 8] >> (i % 8) & 1)
                return pdu[:5]
            if fc == 16:
                addr, qty, _n = struct.unpack(">HHB", pdu[1:6])
                if addr + qty > len(s.hr):
                    return bytes([fc | 0x80, ILLEGAL_ADDRESS])
                for i in range(qty):
                    s.hr[addr + i] = struct.unpack(">H", pdu[6 + 2 * i:8 + 2 * i])[0]
                return pdu[:5]
        except (struct.error, IndexError):
            return bytes([fc | 0x80, ILLEGAL_VALUE])
        return bytes([fc | 0x80, ILLEGAL_FUNCTION])

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                head = await reader.readexactly(7)
                tid, pid, length, unit = struct.unpack(">HHHB", head)
                pdu = await reader.readexactly(length - 1)
                if pid != 0 or (unit not in self.unit_ids and unit != 0):
                    continue  # not for us; real gateways time out
                self.requests += 1
                resp = self.handle_pdu(pdu)
                writer.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def serve(self, host: str, port: int) -> None:
        self.server = await asyncio.start_server(self._client, host, port)
        log.info("Modbus TCP slave on %s:%d", host, port)
        async with self.server:
            await self.server.serve_forever()

    async def stop(self) -> None:
        if self.server:
            self.server.close()
