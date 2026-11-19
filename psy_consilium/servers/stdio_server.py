"""Private psychiatric screening tools exposed over MCP stdio."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from psy_consilium import calculators
from psy_consilium.models import CalculatorInfo, ClinicalResult


def _clinical_call(function: Callable[..., ClinicalResult], *args: Any) -> ClinicalResult:
    """Expose expected calculator validation failures as MCP ToolError."""

    try:
        return function(*args)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def build_server() -> MCPServer:
    server = MCPServer(
        "PsyConsilium Private Assessments",
        instructions=(
            "Deterministic screening instruments for de-identified adult cases. "
            "Results are screening aids, not diagnoses."
        ),
    )

    @server.tool()
    async def phq9(
        q1: Annotated[int, Field(ge=0, le=3)],
        q2: Annotated[int, Field(ge=0, le=3)],
        q3: Annotated[int, Field(ge=0, le=3)],
        q4: Annotated[int, Field(ge=0, le=3)],
        q5: Annotated[int, Field(ge=0, le=3)],
        q6: Annotated[int, Field(ge=0, le=3)],
        q7: Annotated[int, Field(ge=0, le=3)],
        q8: Annotated[int, Field(ge=0, le=3)],
        q9: Annotated[int, Field(ge=0, le=3)],
    ) -> ClinicalResult:
        """Calculate PHQ-9 depression symptom severity from nine 0-3 responses."""

        return _clinical_call(calculators.phq9, [q1, q2, q3, q4, q5, q6, q7, q8, q9])

    @server.tool()
    async def gad7(
        q1: Annotated[int, Field(ge=0, le=3)],
        q2: Annotated[int, Field(ge=0, le=3)],
        q3: Annotated[int, Field(ge=0, le=3)],
        q4: Annotated[int, Field(ge=0, le=3)],
        q5: Annotated[int, Field(ge=0, le=3)],
        q6: Annotated[int, Field(ge=0, le=3)],
        q7: Annotated[int, Field(ge=0, le=3)],
    ) -> ClinicalResult:
        """Calculate GAD-7 anxiety symptom severity from seven 0-3 responses."""

        return _clinical_call(calculators.gad7, [q1, q2, q3, q4, q5, q6, q7])

    @server.tool()
    async def audit_c(
        sex: Literal["female", "male"],
        q1: Annotated[int, Field(ge=0, le=4)],
        q2: Annotated[int, Field(ge=0, le=4)],
        q3: Annotated[int, Field(ge=0, le=4)],
    ) -> ClinicalResult:
        """Screen alcohol use with AUDIT-C using the documented sex-specific threshold."""

        return _clinical_call(calculators.audit_c, [q1, q2, q3], sex)

    @server.tool()
    async def list_calculators() -> list[CalculatorInfo]:
        """List available private screening tools, input units, limits, and sources."""

        return [
            CalculatorInfo(
                name="phq9",
                title="PHQ-9",
                specialty="psychiatry",
                description="Depressive symptom screening; item 9 is always surfaced separately.",
                units={f"q{i}": "integer score" for i in range(1, 10)},
                limits={f"q{i}": "0..3" for i in range(1, 10)},
                source_url=calculators.PHQ9_SOURCE,
            ),
            CalculatorInfo(
                name="gad7",
                title="GAD-7",
                specialty="psychiatry",
                description="Generalized anxiety symptom screening.",
                units={f"q{i}": "integer score" for i in range(1, 8)},
                limits={f"q{i}": "0..3" for i in range(1, 8)},
                source_url=calculators.GAD7_SOURCE,
            ),
            CalculatorInfo(
                name="audit_c",
                title="AUDIT-C",
                specialty="addiction medicine",
                description="Alcohol use screening with a documented threshold.",
                units={"q1": "score", "q2": "score", "q3": "score"},
                limits={"q1": "0..4", "q2": "0..4", "q3": "0..4"},
                source_url=calculators.AUDITC_SOURCE,
            ),
        ]

    return server


mcp = build_server()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
