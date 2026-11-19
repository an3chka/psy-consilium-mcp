"""In-process protocol log for demonstrable MCP request/response packets."""

from __future__ import annotations

import threading
import uuid
from typing import Any

from psy_consilium.models import MCPPacket, SourceKind


class ProtocolRecorder:
    def __init__(self, max_packets: int = 100) -> None:
        self.max_packets = max_packets
        self._packets: list[MCPPacket] = []
        self._lock = threading.Lock()

    def append(
        self,
        *,
        source: SourceKind,
        transport: str,
        method: str,
        params: dict[str, Any],
        response: dict[str, Any],
        elapsed_ms: int,
        cached: bool = False,
        request_id: str | None = None,
    ) -> MCPPacket:
        packet_id = request_id or uuid.uuid4().hex[:12]
        packet = MCPPacket(
            packet_id=packet_id,
            source=source,
            transport=transport,
            elapsed_ms=elapsed_ms,
            cached=cached,
            request={"jsonrpc": "2.0", "id": packet_id, "method": method, "params": params},
            response={"jsonrpc": "2.0", "id": packet_id, **response},
        )
        with self._lock:
            self._packets.append(packet)
            self._packets = self._packets[-self.max_packets :]
        return packet

    def list(self) -> list[MCPPacket]:
        with self._lock:
            return list(reversed(self._packets))

    def clear(self) -> None:
        with self._lock:
            self._packets.clear()


recorder = ProtocolRecorder()

