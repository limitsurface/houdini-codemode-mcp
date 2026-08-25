from __future__ import annotations

import asyncio

from mcp import Client

import houdini_codemode.mcp_server as mcp_module


class FakeController:
    calls = []

    def run(self, source, args=None, instance=None, policy=None):
        self.calls.append((source, args, instance, policy))
        return {
            "ok": True,
            "data": {"value": {"source": source, "args": args}},
            "meta": {"completion": "complete"},
        }


def test_mcp_2026_exposes_exactly_one_tool_and_delegates(monkeypatch) -> None:
    FakeController.calls = []
    monkeypatch.setattr(mcp_module, "Controller", FakeController)

    async def exercise():
        async with Client(mcp_module.mcp) as client:
            listed = await client.list_tools()
            assert client.protocol_version == "2026-07-28"
            assert client.server_info.version == "0.3.1"
            assert [tool.name for tool in listed.tools] == ["houdini_code_run"]
            assert "ctx.capabilities()" in listed.tools[0].description
            assert "ctx.help('ctx.service.method')" in listed.tools[0].description
            return await client.call_tool(
                "houdini_code_run",
                {"source": "result.emit(args)", "args": {"value": 9}},
            )

    result = asyncio.run(exercise())

    assert result.is_error is False
    assert result.structured_content["data"]["value"] == {
        "source": "result.emit(args)",
        "args": {"value": 9},
    }
    assert FakeController.calls == [
        ("result.emit(args)", {"value": 9}, None, None)
    ]
