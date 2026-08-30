"""MCP JSON-RPC 客户端（对齐 car_robot/fc_monitor.js）。"""
from __future__ import annotations

import json
import re
import time

import httpx

from app.config import settings


class McpClient:
    def __init__(self) -> None:
        self._verify_ssl = settings.alarm_mcp_verify_ssl
        self._timeout = httpx.Timeout(settings.alarm_mcp_timeout_sec)
        self.url = f"https://{settings.alarm_mcp_host}{settings.alarm_mcp_path}"
        self._session_id: str | None = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with httpx.AsyncClient(
            timeout=self._timeout, verify=self._verify_ssl
        ) as client:
            resp = await client.post(
                self.url,
                headers=self._headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "AICustomeRobort", "version": "1.0"},
                    },
                },
            )
            resp.raise_for_status()
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
            res = self._parse_response(resp)
            if res.get("error"):
                raise RuntimeError(str(res["error"]))

            notify = await client.post(
                self.url,
                headers=self._headers,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
            )
            notify.raise_for_status()
            self._initialized = True

    async def call_tool(self, name: str, arguments: dict) -> dict:
        await self.initialize()
        async with httpx.AsyncClient(
            timeout=self._timeout, verify=self._verify_ssl
        ) as client:
            resp = await client.post(
                self.url,
                headers=self._headers,
                json={
                    "jsonrpc": "2.0",
                    "id": int(time.time() * 1000),
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            resp.raise_for_status()
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
            data = self._parse_response(resp)
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            return data.get("result") or {}

    @property
    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {settings.alarm_mcp_token}",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _parse_response(self, resp: httpx.Response) -> dict:
        text = resp.text.strip()
        if text.startswith("data:") or "\ndata:" in text:
            return self._parse_sse(text)
        return json.loads(text)

    def _parse_sse(self, text: str) -> dict:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(f"无法解析 SSE: {text[:200]}")
