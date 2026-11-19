"""Shared typed contracts for calculators, evidence, and the consilium."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "moderate", "high", "critical", "informational"]
SourceKind = Literal["stdio", "local_http", "pubmed", "openfda"]


class Component(BaseModel):
    """One transparent contribution to a clinical score."""

    name: str
    value: str
    points: float | None = None


class ClinicalResult(BaseModel):
    """Uniform result returned by every deterministic clinical MCP tool."""

    tool: str
    title: str
    value: float
    unit: str
    risk_level: RiskLevel
    interpretation: str
    components: list[Component] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    methodology: str
    source_url: str


class CalculatorInfo(BaseModel):
    name: str
    title: str
    specialty: str
    description: str
    units: dict[str, str]
    limits: dict[str, str]
    source_url: str


class MCPPacket(BaseModel):
    """JSON-RPC envelope recorded around a real MCP client operation."""

    packet_id: str
    source: SourceKind
    transport: str
    elapsed_ms: int
    cached: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request: dict[str, Any]
    response: dict[str, Any]


class ToolDescriptor(BaseModel):
    source: SourceKind
    name: str
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any]


class PatientCase(BaseModel):
    """De-identified case data. Names, contacts, and record identifiers are intentionally absent."""

    age: int = Field(ge=18, le=100)
    sex: Literal["female", "male"]
    condition: str = Field(min_length=3, max_length=200)
    candidate_medication: str = Field(default="sertraline", min_length=2, max_length=100)
    comorbidities: list[str] = Field(default_factory=list)
    current_medications: list[str] = Field(default_factory=list)
    previous_treatments: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    prefers_psychotherapy: bool = True
    pregnant_or_breastfeeding: bool = False
    possible_mania_or_psychosis: bool = False
    acute_suicide_risk: bool = False
    phq9_items: list[int] = Field(min_length=9, max_length=9)
    gad7_items: list[int] = Field(min_length=7, max_length=7)
    auditc_items: list[int] = Field(min_length=3, max_length=3)
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    height_cm: float | None = Field(default=None, ge=120, le=230)
    creatinine_umol_l: float | None = Field(default=None, ge=20, le=2000)
    qt_ms: float | None = Field(default=None, ge=200, le=800)
    heart_rate_bpm: float | None = Field(default=None, ge=20, le=250)

    def safe_research_terms(self) -> dict[str, Any]:
        """Only coarse, non-identifying attributes may leave the local application."""

        return {
            "condition": self.condition.strip(),
            "age_group": "older adult" if self.age >= 65 else "adult",
            "candidate_medication": self.candidate_medication.strip(),
        }


class AgentOpinion(BaseModel):
    agent: str
    role: str
    conclusion: str
    evidence_ids: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class TreatmentOption(BaseModel):
    name: str
    rationale: str
    evidence_ids: list[str]
    limitations: list[str]
    checks_before_decision: list[str]


class ConsiliumReport(BaseModel):
    status: Literal["review", "stop"]
    case_summary: str
    scores: dict[str, ClinicalResult]
    opinions: list[AgentOpinion]
    options: list[TreatmentOption]
    stop_reasons: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    disclaimer: str = (
        "Учебная система поддержки решений. Не ставит диагноз, не назначает лечение и требует проверки врачом."
    )

