"""Somatic safety calculators served over modern HTTP and legacy MCP SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import uvicorn
from mcp.server.mcpserver import MCPServer
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from psy_consilium import calculators
from psy_consilium.models import CalculatorInfo, ClinicalResult


def build_server(name: str = "PsyConsilium Somatic Safety") -> MCPServer:
    server = MCPServer(
        name,
        instructions=(
            "Deterministic adult somatic-safety calculations. Input units are explicit. "
            "Outputs require interpretation by a qualified clinician."
        ),
    )

    @server.tool()
    async def bmi(
        weight_kg: Annotated[float, Field(ge=25, le=350)],
        height_cm: Annotated[float, Field(ge=120, le=230)],
    ) -> ClinicalResult:
        """Calculate adult body mass index from kilograms and centimetres."""

        return calculators.bmi(weight_kg, height_cm)

    @server.tool()
    async def egfr_ckd_epi_2021(
        age: Annotated[int, Field(ge=18, le=100)],
        sex: Literal["female", "male"],
        creatinine_umol_l: Annotated[float, Field(ge=20, le=2000)],
    ) -> ClinicalResult:
        """Estimate adult eGFR with the race-free 2021 CKD-EPI creatinine equation."""

        return calculators.egfr_ckd_epi_2021(age, sex, creatinine_umol_l)

    @server.tool()
    async def cockcroft_gault(
        age: Annotated[int, Field(ge=18, le=100)],
        sex: Literal["female", "male"],
        weight_kg: Annotated[float, Field(ge=25, le=350)],
        creatinine_umol_l: Annotated[float, Field(ge=20, le=2000)],
    ) -> ClinicalResult:
        """Estimate creatinine clearance for contextual medication review."""

        return calculators.cockcroft_gault(age, sex, weight_kg, creatinine_umol_l)

    @server.tool()
    async def qtc_fridericia(
        qt_ms: Annotated[float, Field(ge=200, le=800)],
        heart_rate_bpm: Annotated[float, Field(ge=20, le=250)],
    ) -> ClinicalResult:
        """Correct QT interval with the Fridericia formula."""

        return calculators.qtc_fridericia(qt_ms, heart_rate_bpm)

    @server.tool()
    async def child_pugh(
        bilirubin_mg_dl: Annotated[float, Field(ge=0.1, le=50)],
        albumin_g_dl: Annotated[float, Field(ge=1, le=6)],
        inr: Annotated[float, Field(ge=0.5, le=10)],
        ascites: Literal["none", "mild", "moderate_severe"],
        encephalopathy_grade: Literal["none", "grade_1_2", "grade_3_4"],
    ) -> ClinicalResult:
        """Calculate Child-Pugh class from explicit laboratory and clinical inputs."""

        return calculators.child_pugh(
            bilirubin_mg_dl,
            albumin_g_dl,
            inr,
            ascites,
            encephalopathy_grade,
        )

    @server.tool()
    async def list_calculators() -> list[CalculatorInfo]:
        """List all local somatic tools with specialties, units, limits, and sources."""

        return [
            CalculatorInfo(name="bmi", title="BMI", specialty="general medicine", description="Adult BMI.", units={"weight_kg": "kg", "height_cm": "cm"}, limits={"weight_kg": "25..350", "height_cm": "120..230"}, source_url=calculators.BMI_SOURCE),
            CalculatorInfo(name="egfr_ckd_epi_2021", title="CKD-EPI 2021", specialty="nephrology", description="Race-free eGFR.", units={"creatinine_umol_l": "µmol/L"}, limits={"age": "18..100", "creatinine_umol_l": "20..2000"}, source_url=calculators.CKDEPI_SOURCE),
            CalculatorInfo(name="cockcroft_gault", title="Cockcroft-Gault", specialty="clinical pharmacology", description="Creatinine clearance estimate.", units={"weight_kg": "kg", "creatinine_umol_l": "µmol/L"}, limits={"age": "18..100"}, source_url=calculators.COCKCROFT_SOURCE),
            CalculatorInfo(name="qtc_fridericia", title="QTcF", specialty="cardiology", description="QT correction by Fridericia.", units={"qt_ms": "ms", "heart_rate_bpm": "beats/min"}, limits={"qt_ms": "200..800", "heart_rate_bpm": "20..250"}, source_url=calculators.QTC_SOURCE),
            CalculatorInfo(name="child_pugh", title="Child-Pugh", specialty="hepatology", description="Liver disease severity class.", units={"bilirubin_mg_dl": "mg/dL", "albumin_g_dl": "g/dL", "inr": "ratio"}, limits={"encephalopathy_grade": "none | grade_1_2 | grade_3_4"}, source_url=calculators.CHILD_PUGH_SOURCE),
        ]

    return server


modern_mcp = build_server()
legacy_mcp = build_server("PsyConsilium Somatic Safety (legacy SSE)")
modern_app = modern_mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)
legacy_app = legacy_mcp.sse_app(sse_path="/sse", message_path="/messages")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "modern": "/mcp", "legacy_sse": "/sse", "legacy_messages": "/messages"})


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    async with modern_mcp.session_manager.run():
        yield


app = Starlette(
    routes=[Route("/health", health), *modern_app.routes, *legacy_app.routes],
    lifespan=lifespan,
)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
