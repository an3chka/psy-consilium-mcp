"""Evidence-grounded, rule-based virtual consilium orchestration.

The agents are explicit clinical perspectives, not independent prescribing bots.
Every calculation and external lookup travels through MCP.
"""

from __future__ import annotations

import re
from typing import Any

from psy_consilium.clients.router import MCPRouter, structured_content
from psy_consilium.models import AgentOpinion, ClinicalResult, ConsiliumReport, PatientCase, TreatmentOption

MEDICATION_RU = {
    "sertraline": "Сертралин",
    "escitalopram": "Эсциталопрам",
    "fluoxetine": "Флуоксетин",
    "duloxetine": "Дулоксетин",
}


def _score_args(values: list[int]) -> dict[str, int]:
    return {f"q{index}": value for index, value in enumerate(values, start=1)}


def _clinical_result(raw: dict[str, Any]) -> ClinicalResult:
    payload = structured_content(raw)
    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], dict):
        payload = payload["result"]
    return ClinicalResult.model_validate(payload)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _pubmed_evidence(raw: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _walk(structured_content(raw)):
        pmid = item.get("pmid") or item.get("uid") or item.get("PMID")
        title = item.get("title") or item.get("Title")
        if not pmid or str(pmid) in seen:
            continue
        seen.add(str(pmid))
        found.append(
            {
                "id": f"PMID:{pmid}",
                "type": "publication",
                "title": str(title or f"PubMed record {pmid}"),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "note": "Найдена через внешний PubMed MCP; релевантность требует проверки полного текста.",
            }
        )
    return found[:5]


def _openfda_evidence(raw: dict[str, Any], medication: str) -> list[dict[str, Any]]:
    payload = structured_content(raw)
    texts: list[str] = []
    set_id = "unknown"
    for item in _walk(payload):
        if item.get("set_id"):
            set_id = str(item["set_id"])
        for key in ("boxed_warning", "contraindications", "warnings_and_cautions", "drug_interactions"):
            value = item.get(key)
            if isinstance(value, list):
                texts.extend(str(part) for part in value)
            elif isinstance(value, str):
                texts.append(value)
    compact = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return [
        {
            "id": f"OPENFDA:{set_id}",
            "type": "drug_label",
            "title": f"Инструкция FDA США: {MEDICATION_RU.get(medication.lower(), medication)}",
            "url": "https://open.fda.gov/apis/drug/label/",
            "note": (compact[:700] + "…") if len(compact) > 700 else (compact or "Label response received; inspect raw MCP packet."),
        }
    ]


def _citation_ids(evidence: list[dict[str, Any]], kind: str) -> list[str]:
    return [str(item["id"]) for item in evidence if item.get("type") == kind]


def _validate_citations(report: ConsiliumReport) -> None:
    known = {str(item["id"]) for item in report.evidence}
    referenced: set[str] = set()
    for opinion in report.opinions:
        referenced.update(opinion.evidence_ids)
    for option in report.options:
        referenced.update(option.evidence_ids)
    unknown = referenced - known
    if unknown:
        raise ValueError(f"Consilium produced unknown evidence IDs: {sorted(unknown)}")


async def run_consilium(case: PatientCase, router: MCPRouter) -> ConsiliumReport:
    """Run assessments, safety checks, literature search, and structured deliberation."""

    scores: dict[str, ClinicalResult] = {}
    phq_raw = await router.call_tool("stdio", "phq9", _score_args(case.phq9_items))
    gad_raw = await router.call_tool("stdio", "gad7", _score_args(case.gad7_items))
    audit_args: dict[str, Any] = {"sex": case.sex, **_score_args(case.auditc_items)}
    audit_raw = await router.call_tool("stdio", "audit_c", audit_args)
    scores["phq9"] = _clinical_result(phq_raw)
    scores["gad7"] = _clinical_result(gad_raw)
    scores["audit_c"] = _clinical_result(audit_raw)

    if case.weight_kg is not None and case.height_cm is not None:
        scores["bmi"] = _clinical_result(
            await router.call_tool("local_http", "bmi", {"weight_kg": case.weight_kg, "height_cm": case.height_cm})
        )
    if case.creatinine_umol_l is not None:
        scores["egfr"] = _clinical_result(
            await router.call_tool(
                "local_http",
                "egfr_ckd_epi_2021",
                {"age": case.age, "sex": case.sex, "creatinine_umol_l": case.creatinine_umol_l},
            )
        )
        if case.weight_kg is not None:
            scores["creatinine_clearance"] = _clinical_result(
                await router.call_tool(
                    "local_http",
                    "cockcroft_gault",
                    {"age": case.age, "sex": case.sex, "weight_kg": case.weight_kg, "creatinine_umol_l": case.creatinine_umol_l},
                )
            )
    if case.qt_ms is not None and case.heart_rate_bpm is not None:
        scores["qtc"] = _clinical_result(
            await router.call_tool(
                "local_http",
                "qtc_fridericia",
                {"qt_ms": case.qt_ms, "heart_rate_bpm": case.heart_rate_bpm},
            )
        )

    stop_reasons: list[str] = []
    if case.acute_suicide_risk:
        stop_reasons.append("Отмечен острый суицидальный риск: требуется немедленная очная оценка по локальному протоколу.")
    if case.phq9_items[8] > 0:
        stop_reasons.append("Пункт 9 PHQ-9 положительный: нужна отдельная структурированная оценка суицидального риска.")
    if case.possible_mania_or_psychosis:
        stop_reasons.append("Есть признаки возможной мании или психоза: обычный алгоритм депрессии неприменим до очной оценки.")
    if case.pregnant_or_breastfeeding:
        stop_reasons.append("Беременность/лактация требует специализированной оценки пользы и риска.")

    opinions: list[AgentOpinion] = [
        AgentOpinion(
            agent="Клинический координатор",
            role="Психиатрическая формулировка случая",
            conclusion=f"PHQ-9: {scores['phq9'].value:g}; GAD-7: {scores['gad7'].value:g}; AUDIT-C: {scores['audit_c'].value:g}.",
            concerns=scores["phq9"].warnings + stop_reasons,
            missing_data=["длительность и динамика симптомов", "функциональное нарушение", "дифференциальный диагноз"],
        )
    ]

    if stop_reasons:
        report = ConsiliumReport(
            status="stop",
            case_summary=f"Обезличенный взрослый случай: {case.condition}.",
            scores=scores,
            opinions=opinions,
            options=[],
            stop_reasons=stop_reasons,
            evidence=[],
        )
        _validate_citations(report)
        return report

    evidence: list[dict[str, Any]] = []
    external_warnings: list[str] = []
    safe_terms = case.safe_research_terms()
    population = '"aged"[MeSH Terms]' if safe_terms["age_group"] == "older adult" else '"adult"[MeSH Terms]'
    query = (
        f"({safe_terms['condition']}) AND ({safe_terms['candidate_medication']}) AND ({population}) AND "
        "(systematic review[Publication Type] OR meta-analysis[Publication Type] OR randomized controlled trial[Publication Type])"
    )
    try:
        pubmed = await router.call_tool(
            "pubmed",
            "pubmed_search_articles",
            {"query": query, "maxResults": 5, "summaryCount": 5},
        )
        evidence.extend(_pubmed_evidence(pubmed))
    except Exception as exc:
        external_warnings.append(f"PubMed MCP недоступен: {exc}")

    try:
        openfda = await router.call_tool(
            "openfda",
            "openfda_get_drug_label",
            {
                "search": f'openfda.generic_name:"{safe_terms["candidate_medication"]}"',
                "sections": ["boxed_warning", "contraindications", "warnings_and_cautions", "drug_interactions"],
                "limit": 1,
            },
        )
        evidence.extend(_openfda_evidence(openfda, case.candidate_medication))
    except Exception as exc:
        external_warnings.append(f"OpenFDA MCP недоступен: {exc}")

    publications = _citation_ids(evidence, "publication")
    labels = _citation_ids(evidence, "drug_label")
    medication_display = MEDICATION_RU.get(case.candidate_medication.lower(), case.candidate_medication)
    opinions.extend(
        [
            AgentOpinion(
                agent="Специалист по доказательной медицине",
                role="Поиск и оценка литературы",
                conclusion=(
                    f"Через PubMed MCP найдено {len(publications)} записей; это кандидаты для проверки, а не автоматически доказанные рекомендации."
                    if publications
                    else "Проверяемые публикации не получены; медикаментозные выводы ограничены."
                ),
                evidence_ids=publications,
                concerns=external_warnings,
                missing_data=["полные тексты", "качество и применимость исследований"],
            ),
            AgentOpinion(
                agent="Специалист по психофармакологии",
                role="Инструкции, противопоказания и взаимодействия",
                conclusion=(
                    f"Получена американская маркировка для препарата «{medication_display}»; перед решением врач должен проверить актуальную локальную инструкцию."
                    if labels
                    else "Маркировка препарата не получена — медикаментозный вариант нельзя считать проверенным."
                ),
                evidence_ids=labels,
                concerns=["OpenFDA содержит американские инструкции и не заменяет локальную нормативную информацию."],
                missing_data=["полный список лекарств и взаимодействий", "анамнез нежелательных реакций"],
            ),
            AgentOpinion(
                agent="Специалист по соматической безопасности",
                role="Соматические ограничения",
                conclusion="Доступные локальные показатели рассчитаны детерминированными MCP-инструментами.",
                concerns=[result.interpretation for key, result in scores.items() if key not in {"phq9", "gad7", "audit_c"} and result.risk_level in {"high", "critical"}],
                missing_data=["АД и пульс", "электролиты", "печёночные показатели"] if len(scores) <= 3 else [],
            ),
        ]
    )

    options: list[TreatmentOption] = [
        TreatmentOption(
            name="Структурированная психотерапия для обсуждения",
            rationale="Соответствует предпочтению пациента и не требует автоматического лекарственного назначения.",
            evidence_ids=publications,
            limitations=["Конкретный метод зависит от диагноза, доступности и предпочтений."],
            checks_before_decision=["подтвердить диагноз", "оценить тяжесть и функционирование", "согласовать цели лечения"],
        )
    ]
    if publications and labels:
        options.append(
            TreatmentOption(
                name=f"{medication_display}: медикаментозный вариант для врачебного рассмотрения",
                rationale="Есть найденные публикации и официальная американская маркировка; система не выбирает дозу и не выписывает препарат.",
                evidence_ids=[*publications, *labels],
                limitations=["Не доказана применимость каждой найденной статьи к этому случаю.", "Нужна актуальная локальная инструкция."],
                checks_before_decision=["исключить биполярность", "проверить взаимодействия и противопоказания", "сформировать план мониторинга"],
            )
        )

    opinions.append(
        AgentOpinion(
            agent="Методолог — адвокат дьявола",
            role="Критика качества решения",
            conclusion="Варианты допустимы только как повестка врачебного обсуждения; причинно-следующий вывод из поисковой выдачи запрещён.",
            evidence_ids=publications,
            concerns=["publication bias", "неполные данные пациента", "ошибка переноса результатов исследования"],
            missing_data=["предпочтения по рискам", "предыдущий ответ на лечение", "план наблюдения"],
        )
    )
    report = ConsiliumReport(
        status="review",
        case_summary=f"Обезличенный взрослый случай: {case.condition}; кандидат для обсуждения — {medication_display}.",
        scores=scores,
        opinions=opinions,
        options=options,
        stop_reasons=[],
        evidence=evidence,
    )
    _validate_citations(report)
    return report
