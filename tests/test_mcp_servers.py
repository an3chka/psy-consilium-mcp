from mcp import Client

from psy_consilium.servers.http_server import build_server as build_http_server
from psy_consilium.servers.stdio_server import build_server as build_stdio_server


async def test_private_server_tool_discovery_and_call() -> None:
    async with Client(build_stdio_server()) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} >= {"phq9", "gad7", "audit_c", "list_assessments"}
        result = await client.call_tool("phq9", {f"q{i}": 1 for i in range(1, 10)})
        assert not result.is_error
        assert result.structured_content["value"] == 9


async def test_local_server_has_five_specialty_calculators() -> None:
    async with Client(build_http_server()) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names >= {"bmi", "egfr_ckd_epi_2021", "cockcroft_gault", "qtc_fridericia", "child_pugh"}
        result = await client.call_tool("bmi", {"weight_kg": 70, "height_cm": 175})
        assert result.structured_content["value"] == 22.9
