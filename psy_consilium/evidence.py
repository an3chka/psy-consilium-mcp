"""PICO-oriented evidence retrieval and applicability checks over PubMed MCP."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from psy_consilium.clients.router import MCPRouter, structured_content
from psy_consilium.models import PatientCase


@dataclass(frozen=True)
class CandidateSpec:
    key: str
    title: str
    category: str
    query_terms: str
    required_terms: tuple[str, ...]


CONDITION_TERMS = {
    "major depressive disorder": ("major depressive disorder", "major depression", "depression"),
    "generalized anxiety disorder": ("generalized anxiety disorder", "generalised anxiety disorder", "anxiety"),
    "mixed anxiety and depressive symptoms": ("depression", "anxiety", "mixed anxiety"),
}


def candidate_specs(case: PatientCase, medication_title: str) -> list[CandidateSpec]:
    medication = case.candidate_medication.lower()
    return [
        CandidateSpec(
            key="psychotherapy",
            title="Когнитивно-поведенческая терапия",
            category="psychotherapy",
            query_terms='("cognitive behavioral therapy" OR "behavioural activation" OR "behavioral activation")',
            required_terms=("cognitive", "behavioral", "behavioural", "psychotherapy"),
        ),
        CandidateSpec(
            key="medication",
            title=medication_title,
            category="medication",
            query_terms=f'("{medication}")',
            required_terms=(medication,),
        ),
        CandidateSpec(
            key="combined",
            title=f"Комбинация: психотерапия + {medication_title}",
            category="combined",
            query_terms=(
                '(("cognitive behavioral therapy" OR psychotherapy) AND '
                '(antidepressant OR pharmacotherapy) AND (combined OR combination))'
            ),
            required_terms=("combined", "combination", "psychotherapy", "antidepressant"),
        ),
    ]


def _search_payload(case: PatientCase, spec: CandidateSpec) -> dict[str, Any]:
    population = '"aged"[MeSH Terms]' if case.age >= 65 else '"adult"[MeSH Terms]'
    query = f'("{case.condition}") AND {spec.query_terms} AND ({population})'
    return {
        "query": query,
        "publicationTypes": ["Meta-Analysis", "Systematic Review", "Randomized Controlled Trial"],
        "species": "humans",
        "hasAbstract": True,
        "maxResults": 4,
        "summaryCount": 4,
        "sort": "relevance",
    }


def _pmids(raw: dict[str, Any]) -> list[str]:
    payload = structured_content(raw)
    if isinstance(payload, dict):
        return [str(value) for value in payload.get("pmids", []) if str(value).isdigit()]
    return []


def _article_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    payload = structured_content(raw)
    if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
        return [row for row in payload["articles"] if isinstance(row, dict)]
    return []


def _mesh_text(article: dict[str, Any]) -> str:
    names = []
    for term in article.get("meshTerms", []):
        if isinstance(term, dict) and term.get("descriptorName"):
            names.append(str(term["descriptorName"]))
    return " ".join(names)


def _study_type(article: dict[str, Any]) -> str:
    kinds = [str(value) for value in article.get("publicationTypes", [])]
    joined = " ".join(kinds).lower()
    if "meta-analysis" in joined:
        return "Метаанализ"
    if "systematic review" in joined:
        return "Систематический обзор"
    if "randomized controlled trial" in joined:
        return "Рандомизированное исследование"
    return kinds[0] if kinds else "Тип не указан"


def _result_fragments(abstract: str) -> list[str]:
    """Select short verbatim result sentences; never invent or recompute an effect."""

    normalized = re.sub(r"\s+", " ", abstract).strip()
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    signals = ("95%", "confidence interval", "effect size", "hedges", "number needed", "significant", "outperformed", "comparable", "participants", "n =")
    selected = [sentence.strip() for sentence in sentences if any(signal in sentence.lower() for signal in signals)]
    if not selected:
        selected = [sentence.strip() for sentence in sentences if sentence.lower().startswith(("results:", "conclusions:", "conclusion:"))]
    return [fragment[:420] + ("…" if len(fragment) > 420 else "") for fragment in selected[:2]]


def assess_article(article: dict[str, Any], case: PatientCase, spec: CandidateSpec) -> dict[str, Any] | None:
    title = str(article.get("title", ""))
    abstract = str(article.get("abstractText", ""))
    mesh = _mesh_text(article)
    haystack = f"{title} {abstract} {mesh}".lower()
    condition_terms = CONDITION_TERMS.get(case.condition, (case.condition.lower(),))
    condition_match = any(term in haystack for term in condition_terms)
    intervention_hits = sum(1 for term in spec.required_terms if term in haystack)
    intervention_match = intervention_hits >= (2 if spec.key == "combined" else 1)
    adult_match = "adult" in haystack or "middle aged" in haystack or "humans" in haystack
    study_type = _study_type(article)
    design_points = 15 if study_type in {"Метаанализ", "Систематический обзор"} else 12 if study_type == "Рандомизированное исследование" else 4
    score = (30 if condition_match else 0) + (30 if intervention_match else 0) + (15 if adult_match else 0) + design_points + (10 if abstract else 0)
    if not condition_match or not intervention_match or score < 55:
        return None
    reasons = ["совпадает клиническая проблема", "совпадает вмешательство"]
    if adult_match:
        reasons.append("взрослая популяция")
    reasons.append(study_type.lower())
    pmid = str(article.get("pmid", ""))
    year = str(article.get("journalInfo", {}).get("publicationDate", {}).get("year", ""))
    return {
        "id": f"PMID:{pmid}",
        "type": "publication",
        "option_key": spec.key,
        "title": title or f"PubMed record {pmid}",
        "url": article.get("pubmedUrl") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "study_type": study_type,
        "year": year,
        "applicability_score": min(score, 100),
        "applicability": "высокая" if score >= 80 else "умеренная",
        "reasons": reasons,
        "result_fragments": _result_fragments(abstract),
        "note": "Автоматическая PICO-проверка по названию, аннотации, MeSH, популяции и типу исследования; полный текст должен проверить врач.",
    }


async def fetch_candidate_evidence(
    router: MCPRouter,
    case: PatientCase,
    spec: CandidateSpec,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        search = await router.call_tool("pubmed", "pubmed_search_articles", _search_payload(case, spec))
        ids = _pmids(search)[:4]
        if not ids:
            return [], None
        fetched = await router.call_tool(
            "pubmed",
            "pubmed_fetch_articles",
            {"pmids": ids, "includeMesh": True, "maxResponseCharacters": 60000},
        )
        accepted = [item for article in _article_rows(fetched) if (item := assess_article(article, case, spec)) is not None]
        accepted.sort(key=lambda item: item["applicability_score"], reverse=True)
        return accepted[:3], None
    except Exception as exc:
        return [], f"PubMed MCP для варианта «{spec.title}» недоступен: {exc}"


async def fetch_comparative_evidence(
    router: MCPRouter,
    case: PatientCase,
    medication_title: str,
) -> tuple[list[CandidateSpec], list[dict[str, Any]], list[str]]:
    specs = candidate_specs(case, medication_title)
    results = await asyncio.gather(*(fetch_candidate_evidence(router, case, spec) for spec in specs))
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    for items, warning in results:
        evidence.extend(items)
        if warning:
            warnings.append(warning)
    return specs, evidence, warnings

