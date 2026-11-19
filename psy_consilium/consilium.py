"""Evidence-grounded, rule-based virtual consilium orchestration.

The agents are explicit clinical perspectives, not independent prescribing bots.
Every calculation and external lookup travels through MCP.
"""

from __future__ import annotations

import re
from typing import Any

from psy_consilium.clients.router import MCPRouter, structured_content
from psy_consilium.dosing import parse_dose_review
from psy_consilium.evidence import fetch_comparative_evidence
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


def _option_evidence(evidence: list[dict[str, Any]], option_key: str) -> list[dict[str, Any]]:
    return [item for item in evidence if item.get("type") == "publication" and item.get("option_key") == option_key]


def _evidence_summary(items: list[dict[str, Any]]) -> list[str]:
    summaries: list[str] = []
    for item in items[:2]:
        fragments = item.get("result_fragments") or []
        if fragments:
            summaries.append(f"{item['id']} · {fragments[0]}")
        else:
            summaries.append(
                f"{item['id']} · {item.get('study_type', 'исследование')}, применимость "
                f"{item.get('applicability', 'не оценена')}."
            )
    return summaries


def _fit_score(case: PatientCase, option_key: str, items: list[dict[str, Any]], has_label: bool) -> int:
    applicability = sum(int(item.get("applicability_score", 0)) for item in items) / len(items) if items else 0
    score = 35 + min(25, round(applicability / 4))
    if option_key == "psychotherapy" and case.prefers_psychotherapy:
        score += 15
    if option_key == "medication" and has_label:
        score += 10
    phq = sum(case.phq9_items)
    if option_key == "combined" and phq >= 15:
        score += 15
    if not items:
        score -= 15
    return max(0, min(100, score))


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
    medication_display = MEDICATION_RU.get(case.candidate_medication.lower(), case.candidate_medication)
    specs, comparative_evidence, research_warnings = await fetch_comparative_evidence(
        router, case, medication_display
    )
    evidence.extend(comparative_evidence)
    external_warnings.extend(research_warnings)

    openfda_raw: dict[str, Any] | None = None
    try:
        openfda_raw = await router.call_tool(
            "openfda",
            "openfda_get_drug_label",
            {
                "search": f'openfda.generic_name:"{safe_terms["candidate_medication"]}"',
                "sections": [
                    "dosage_and_administration",
                    "boxed_warning",
                    "contraindications",
                    "warnings_and_cautions",
                    "drug_interactions",
                    "use_in_specific_populations",
                ],
                "limit": 1,
            },
        )
        evidence.extend(_openfda_evidence(openfda_raw, case.candidate_medication))
    except Exception as exc:
        external_warnings.append(f"OpenFDA MCP недоступен: {exc}")

    publications = _citation_ids(evidence, "publication")
    labels = _citation_ids(evidence, "drug_label")
    dose_review = (
        parse_dose_review(openfda_raw, case, medication_display)
        if openfda_raw is not None
        else None
    )
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

    options: list[TreatmentOption] = []
    for spec in specs:
        items = _option_evidence(evidence, spec.key)
        ids = [str(item["id"]) for item in items]
        if spec.key in {"medication", "combined"}:
            ids.extend(labels)
        score = _fit_score(case, spec.key, items, bool(labels))
        factors_for = [
            f"{len(items)} публикац. прошли автоматическую проверку применимости",
        ]
        factors_against: list[str] = []
        if case.prefers_psychotherapy and spec.key in {"psychotherapy", "combined"}:
            factors_for.append("соответствует предпочтению психотерапии")
        if spec.key == "medication" and labels:
            factors_for.append("получена официальная маркировка OpenFDA")
        if spec.key == "combined" and sum(case.phq9_items) >= 15:
            factors_for.append("выраженность симптомов делает комбинированный подход предметом обсуждения")
        if not items:
            factors_against.append("релевантные публикации автоматически не подтверждены")
        if spec.key in {"medication", "combined"} and not labels:
            factors_against.append("официальная маркировка препарата не получена")
        options.append(
            TreatmentOption(
                key=spec.key,
                name=spec.title,
                category=spec.category,  # type: ignore[arg-type]
                fit_score=score,
                rationale=(
                    "Оценка пригодности складывается из совпадения клинической проблемы, вмешательства, "
                    "взрослой популяции, дизайна исследований и данных конкретного случая."
                ),
                evidence_ids=ids,
                evidence_summary=_evidence_summary(items),
                factors_for=factors_for,
                factors_against=factors_against,
                limitations=[
                    "Автоматическая PICO-проверка не заменяет чтение полного текста.",
                    "Доступность, противопоказания и предпочтения могут изменить порядок вариантов.",
                ],
                checks_before_decision=(
                    ["подтвердить диагноз", "оценить функционирование", "согласовать цели лечения"]
                    if spec.key == "psychotherapy"
                    else ["исключить биполярность", "проверить взаимодействия", "согласовать дозу и мониторинг по инструкции"]
                ),
            )
        )
    options.sort(key=lambda option: option.fit_score, reverse=True)
    for index, option in enumerate(options):
        option.verdict = "priority" if index == 0 and option.fit_score >= 55 else "consider" if option.fit_score >= 45 else "defer"

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
        dose_review=dose_review,
    )
    _validate_citations(report)
    return report
