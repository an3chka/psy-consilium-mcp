from typing import Any

from psy_consilium import calculators
from psy_consilium.consilium import run_consilium
from psy_consilium.models import PatientCase


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def call_tool(self, source: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((source, tool_name))
        if tool_name == "phq9":
            result = calculators.phq9(list(arguments.values()))
        elif tool_name == "gad7":
            result = calculators.gad7(list(arguments.values()))
        elif tool_name == "audit_c":
            result = calculators.audit_c([arguments["q1"], arguments["q2"], arguments["q3"]], arguments["sex"])
        else:
            raise AssertionError(f"Unexpected tool call after a stop flag: {source}/{tool_name}")
        return {"structuredContent": result.model_dump(mode="json")}


async def test_red_flag_stops_before_external_research() -> None:
    router = FakeRouter()
    case = PatientCase(
        age=30,
        sex="female",
        condition="depressive symptoms",
        phq9_items=[1, 1, 1, 1, 1, 1, 1, 1, 1],
        gad7_items=[0] * 7,
        auditc_items=[0] * 3,
        acute_suicide_risk=True,
    )
    report = await run_consilium(case, router)  # type: ignore[arg-type]
    assert report.status == "stop"
    assert report.options == []
    assert all(source == "stdio" for source, _ in router.calls)
    assert {tool for _, tool in router.calls} == {"phq9", "gad7", "audit_c"}

