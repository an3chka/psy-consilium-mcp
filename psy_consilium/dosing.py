"""Conservative extraction of dosing evidence from an official OpenFDA label."""

from __future__ import annotations

import re
from typing import Any

from psy_consilium.clients.router import structured_content
from psy_consilium.models import DoseReview, PatientCase


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _parts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _sentences(texts: list[str]) -> list[str]:
    text = re.sub(r"\s+", " ", " ".join(texts)).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+", text) if part.strip()]


def _select(sentences: list[str], signals: tuple[str, ...], limit: int = 3) -> list[str]:
    found: list[str] = []
    for sentence in sentences:
        if any(signal in sentence.lower() for signal in signals):
            compact = sentence[:500] + ("…" if len(sentence) > 500 else "")
            if compact not in found:
                found.append(compact)
        if len(found) >= limit:
            break
    return found


def _maximum_mg_per_day(excerpts: list[str]) -> float | None:
    values: list[float] = []
    for excerpt in excerpts:
        lower = excerpt.lower()
        if "maximum" not in lower and "maximal" not in lower:
            continue
        for raw in re.findall(r"(\d+(?:\.\d+)?)\s*mg(?:\s*/\s*day|\s+per\s+day|\s+daily)?", lower):
            value = float(raw)
            if 0 < value <= 5000:
                values.append(value)
    return max(values) if values else None


def parse_dose_review(raw: dict[str, Any], case: PatientCase, medication_title: str) -> DoseReview:
    payload = structured_content(raw)
    set_id: str | None = None
    dosage: list[str] = []
    populations: list[str] = []
    warnings: list[str] = []
    for item in _walk(payload):
        if set_id is None and item.get("set_id"):
            set_id = str(item["set_id"])
        dosage.extend(_parts(item.get("dosage_and_administration")))
        populations.extend(_parts(item.get("use_in_specific_populations")))
        warnings.extend(_parts(item.get("warnings_and_cautions")))

    dose_sentences = _sentences(dosage)
    initial = _select(
        dose_sentences,
        (
            "initial dose",
            "initial dosage",
            "initial treatment dosage",
            "initial therapeutic dose",
            "starting dose",
            "starting dosage",
            "recommended dose",
            "initiated with a dose",
        ),
    )
    titration = _select(dose_sentences, ("titrate", "titration", "increase", "decrease", "weekly", "interval"))
    maximum = _select(dose_sentences, ("maximum", "maximal"))
    adjustments = _select(
        _sentences([*dosage, *populations]),
        ("hepatic impairment", "renal impairment", "older", "elderly", "pregnan", "lactation"),
        limit=4,
    )
    detected_max = _maximum_mg_per_day(maximum)

    flags: list[str] = []
    if case.creatinine_umol_l is None:
        flags.append("Нет показателя функции почек для проверки поправок дозы.")
    if case.age >= 65:
        flags.append("Возраст 65+ требует отдельной проверки раздела для пожилых пациентов.")
    if case.qt_ms is None or case.heart_rate_bpm is None:
        flags.append("Нет QTc для проверки риска удлинения интервала QT.")
    if case.current_medications:
        flags.append("Нужно вручную сверить взаимодействия со всеми текущими препаратами.")
    if not dosage:
        return DoseReview(
            medication=medication_title,
            planned_dose_mg=case.planned_dose_mg,
            status="label_unavailable",
            status_text="Раздел дозирования не получен; проверка дозы невозможна.",
            label_id=f"OPENFDA:{set_id}" if set_id else None,
            label_url="https://open.fda.gov/apis/drug/label/",
            safety_flags=flags,
            checks=["Открыть актуальную локальную инструкцию препарата."],
        )

    if case.planned_dose_mg is None:
        status = "not_entered"
        status_text = "Плановая доза не введена: показаны выдержки из официальной инструкции."
    elif detected_max is not None and case.planned_dose_mg > detected_max:
        status = "above_label_maximum"
        status_text = f"Введённая доза выше обнаруженного в инструкции максимума {detected_max:g} мг/сут."
    else:
        status = "review_required"
        status_text = "Доза не превышает автоматически обнаруженный максимум, но всё равно требует проверки показания, титрации и пациента врачом."

    return DoseReview(
        medication=medication_title,
        planned_dose_mg=case.planned_dose_mg,
        status=status,
        status_text=status_text,
        label_id=f"OPENFDA:{set_id}" if set_id else None,
        label_url="https://open.fda.gov/apis/drug/label/",
        initial_dose_excerpts=initial,
        titration_excerpts=titration,
        maximum_dose_excerpts=maximum,
        population_adjustment_excerpts=adjustments,
        detected_maximum_mg_per_day=detected_max,
        safety_flags=flags,
        checks=[
            "Сопоставить выдержку с точным показанием и формой выпуска.",
            "Проверить противопоказания, взаимодействия и предыдущие нежелательные реакции.",
            "Зафиксировать срок оценки эффекта, переносимости и критерии изменения плана.",
            "Сверить с актуальной локальной инструкцией: OpenFDA — маркировка США.",
        ],
    )
