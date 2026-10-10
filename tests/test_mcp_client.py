import sys
import json

import pytest

from app.config.settings import MCPServerSettings
from app.mcp.client import _validate_value, connect_mcp_servers
from app.permissions.policy import Risk
from app.agent.executor import Executor
from app.providers.base import ToolCall
from app.tools.registry import ToolRegistry


def test_mcp_schema_validation_checks_nested_required_types_and_ranges():
    schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "minLength": 2},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "additionalProperties": False,
    }
    _validate_value({"query": "hello", "limit": 3}, schema)
    with pytest.raises(ValueError):
        _validate_value({"query": "x", "limit": 3}, schema)
    with pytest.raises(ValueError):
        _validate_value({"query": "valid", "limit": 6}, schema)
    with pytest.raises(ValueError):
        _validate_value({"query": "valid", "other": True}, schema)


@pytest.mark.asyncio
async def test_stdio_mcp_handshake_tools_and_call():
    server_script = r'''
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "test", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo input", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}}]}
    elif method == "tools/call":
        result = {"structuredContent": {"echo": message["params"]["arguments"]["text"]}}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''
    settings = MCPServerSettings(name="demo", command=sys.executable, args=["-u", "-c", server_script])
    registry = ToolRegistry()
    connections = await connect_mcp_servers([settings], registry)
    try:
        assert len(connections) == 1
        tool = registry.get("mcp_demo__echo")
        assert tool.risk == Risk.CONFIRM
        assert tool.schema()["function"]["parameters"]["required"] == ["text"]
        denied = await Executor(registry, confirm=lambda *_: _approved(False)).execute(
            ToolCall(id="1", name=tool.name, arguments=json.dumps({"text": "hello"}))
        )
        assert denied["error"] == "confirmation_denied"
        approved = await Executor(registry, confirm=lambda *_: _approved(True)).execute(
            ToolCall(id="2", name=tool.name, arguments=json.dumps({"text": "hello"}))
        )
        assert approved == {"ok": True, "result": {"ok": True, "result": {"echo": "hello"}}}
    finally:
        for connection in connections:
            await connection.close()


async def _approved(value: bool) -> bool:
    return value
