"""Single high-level client path for every local and external MCP source."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from dotenv import load_dotenv

from psy_consilium.clients.cache import TTLCache
from psy_consilium.clients.recorder import recorder
from psy_consilium.clients.sanitize import sanitize_arguments
from psy_consilium.models import SourceKind, ToolDescriptor


@dataclass(frozen=True)
class SourceConfig:
    kind: SourceKind
    transport: str
    url: str | None = None
    external: bool = False


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return value
    return {"value": value}


class MCPRouter:
    """Discovers and calls tools without bypassing the MCP transport layer."""

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or float(os.getenv("MCP_TIMEOUT_SECONDS", "12"))
        self.sources: dict[SourceKind, SourceConfig] = {
            "stdio": SourceConfig("stdio", "stdio"),
            "local_http": SourceConfig("local_http", "streamable-http", os.getenv("LOCAL_MCP_URL", "http://127.0.0.1:8000/mcp")),
            "pubmed": SourceConfig("pubmed", "streamable-http", os.getenv("PUBMED_MCP_URL", "https://pubmed.caseyjhand.com/mcp"), True),
            "openfda": SourceConfig("openfda", "streamable-http", os.getenv("OPENFDA_MCP_URL", "https://openfda.caseyjhand.com/mcp"), True),
        }
        self.cache = TTLCache(ttl_seconds=900, max_size=128)

    def _client(self, source: SourceKind) -> Client:
        config = self.sources[source]
        if source == "stdio":
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "psy_consilium.server"],
                cwd=str(PROJECT_ROOT),
            )
            return Client(params)
        if config.url is None:
            raise ValueError(f"Для {source} не задан URL")
        return Client(config.url)

    async def _with_retries(self, operation: Any, retries: int) -> Any:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
            except Exception as exc:  # error is logged into the protocol by the caller
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    async def list_tools(self, source: SourceKind) -> list[ToolDescriptor]:
        config = self.sources[source]
        started = time.perf_counter()
        request_id = hashlib.sha1(f"list:{source}:{time.time_ns()}".encode()).hexdigest()[:12]

        async def operation() -> Any:
            async with self._client(source) as client:
                return await client.list_tools()

        try:
            result = await self._with_retries(operation, retries=1 if config.external else 0)
            dumped = _model_dump(result)
            tools = [
                ToolDescriptor(
                    source=source,
                    name=tool.name,
                    title=getattr(tool, "title", None),
                    description=getattr(tool, "description", None),
                    input_schema=getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", {}),
                )
                for tool in result.tools
            ]
            recorder.append(source=source, transport=config.transport, method="tools/list", params={}, response={"result": dumped}, elapsed_ms=round((time.perf_counter() - started) * 1000), request_id=request_id)
            return tools
        except Exception as exc:
            recorder.append(source=source, transport=config.transport, method="tools/list", params={}, response={"error": {"code": -32000, "message": str(exc)}}, elapsed_ms=round((time.perf_counter() - started) * 1000), request_id=request_id)
            raise

    async def call_tool(
        self,
        source: SourceKind,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = self.sources[source]
        clean = sanitize_arguments(arguments, schema) if schema else arguments
        cache_key = hashlib.sha256(json.dumps([source, tool_name, clean], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = self.cache.get(cache_key) if config.external else None
        request_id = hashlib.sha1(f"call:{source}:{time.time_ns()}".encode()).hexdigest()[:12]
        params = {"name": tool_name, "arguments": clean}
        if cached is not None:
            recorder.append(source=source, transport=config.transport, method="tools/call", params=params, response={"result": cached}, elapsed_ms=0, cached=True, request_id=request_id)
            return cached

        started = time.perf_counter()

        async def operation() -> Any:
            async with self._client(source) as client:
                return await client.call_tool(tool_name, clean)

        try:
            result = await self._with_retries(operation, retries=2 if config.external else 1)
            dumped = _model_dump(result)
            if getattr(result, "is_error", False) or getattr(result, "isError", False):
                message = "MCP tool returned an application error"
                content = getattr(result, "content", [])
                if content and hasattr(content[0], "text"):
                    message = content[0].text
                raise RuntimeError(message)
            recorder.append(source=source, transport=config.transport, method="tools/call", params=params, response={"result": dumped}, elapsed_ms=round((time.perf_counter() - started) * 1000), request_id=request_id)
            if config.external:
                self.cache.set(cache_key, dumped)
            return dumped
        except Exception as exc:
            recorder.append(source=source, transport=config.transport, method="tools/call", params=params, response={"error": {"code": -32001, "message": str(exc)}}, elapsed_ms=round((time.perf_counter() - started) * 1000), request_id=request_id)
            raise


def structured_content(result: dict[str, Any]) -> Any:
    """Return MCP structured content, falling back to decoded textual JSON."""

    structured = result.get("structuredContent") or result.get("structured_content")
    if structured is not None:
        return structured
    for item in result.get("content", []):
        text = item.get("text") if isinstance(item, dict) else None
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return result
