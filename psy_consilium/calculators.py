"""Deterministic clinical calculations used by MCP servers.

No language model participates in arithmetic or risk classification.
"""

from __future__ import annotations

import math
from typing import Literal, Sequence

from .models import ClinicalResult, Component

PHQ9_SOURCE = "https://pubmed.ncbi.nlm.nih.gov/11556941/"
GAD7_SOURCE = "https://pubmed.ncbi.nlm.nih.gov/16717171/"
AUDITC_SOURCE = "https://pubmed.ncbi.nlm.nih.gov/10483995/"
CKDEPI_SOURCE = "https://www.kidney.org/ckd-epi-creatinine-equation-2021"
COCKCROFT_SOURCE = "https://www.kidney.org/professionals/kdoqi/cockcroft-gault-equation-estimating-creatinine-clearance"
BMI_SOURCE = "https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight"
QTC_SOURCE = "https://doi.org/10.1111/j.1476-5381.1920.tb00326.x"
CHILD_PUGH_SOURCE = "https://www.ncbi.nlm.nih.gov/books/NBK542308/"


def _bounded_items(items: Sequence[int], expected: int, name: str) -> list[int]:
    if len(items) != expected:
        raise ValueError(f"{name}: ожидается {expected} ответов, получено {len(items)}")
    values = [int(value) for value in items]
    if any(value < 0 or value > 3 for value in values):
        raise ValueError(f"{name}: каждый ответ должен быть от 0 до 3")
    return values


def phq9(items: Sequence[int]) -> ClinicalResult:
    values = _bounded_items(items, 9, "PHQ-9")
    total = sum(values)
    if total <= 4:
        level, interpretation = "low", "Минимальная выраженность депрессивных симптомов"
    elif total <= 9:
        level, interpretation = "low", "Лёгкая выраженность депрессивных симптомов"
    elif total <= 14:
        level, interpretation = "moderate", "Умеренная выраженность депрессивных симптомов"
    elif total <= 19:
        level, interpretation = "high", "Умеренно тяжёлая выраженность депрессивных симптомов"
    else:
        level, interpretation = "critical", "Тяжёлая выраженность депрессивных симптомов"
    warnings: list[str] = []
    if values[8] > 0:
        warnings.append(
            "Ответ на пункт 9 требует отдельной клинической оценки суицидального риска; суммарный балл её не заменяет."
        )
    return ClinicalResult(
        tool="phq9",
        title="PHQ-9",
        value=float(total),
        unit="баллов",
        risk_level=level,
        interpretation=interpretation,
        components=[Component(name=f"Пункт {i + 1}", value=str(v), points=v) for i, v in enumerate(values)],
        warnings=warnings,
        methodology="Сумма 9 пунктов, каждый оценивается от 0 до 3. Шкала является скрининговой, а не диагнозом.",
        source_url=PHQ9_SOURCE,
    )


def gad7(items: Sequence[int]) -> ClinicalResult:
    values = _bounded_items(items, 7, "GAD-7")
    total = sum(values)
    if total <= 4:
        level, interpretation = "low", "Минимальная выраженность тревожных симптомов"
    elif total <= 9:
        level, interpretation = "low", "Лёгкая выраженность тревожных симптомов"
    elif total <= 14:
        level, interpretation = "moderate", "Умеренная выраженность тревожных симптомов"
    else:
        level, interpretation = "high", "Тяжёлая выраженность тревожных симптомов"
    return ClinicalResult(
        tool="gad7",
        title="GAD-7",
        value=float(total),
        unit="баллов",
        risk_level=level,
        interpretation=interpretation,
        components=[Component(name=f"Пункт {i + 1}", value=str(v), points=v) for i, v in enumerate(values)],
        methodology="Сумма 7 пунктов, каждый оценивается от 0 до 3. Результат требует клинической интерпретации.",
        source_url=GAD7_SOURCE,
    )


def audit_c(items: Sequence[int], sex: Literal["female", "male"]) -> ClinicalResult:
    if len(items) != 3:
        raise ValueError("AUDIT-C: ожидается 3 ответа")
    values = [int(value) for value in items]
    if any(value < 0 or value > 4 for value in values):
        raise ValueError("AUDIT-C: каждый ответ должен быть от 0 до 4")
    total = sum(values)
    threshold = 3 if sex == "female" else 4
    positive = total >= threshold
    return ClinicalResult(
        tool="audit_c",
        title="AUDIT-C",
        value=float(total),
        unit="баллов",
        risk_level="moderate" if positive else "low",
        interpretation=(
            "Положительный скрининг: требуется уточняющая оценка употребления алкоголя"
            if positive
            else "Скрининговый порог не достигнут"
        ),
        components=[Component(name=f"Пункт {i + 1}", value=str(v), points=v) for i, v in enumerate(values)],
        warnings=["Порог скрининга не является диагнозом расстройства, связанного с употреблением алкоголя."],
        methodology=f"Сумма 3 пунктов по 0-4; используемый порог: {threshold}.",
        source_url=AUDITC_SOURCE,
    )


def bmi(weight_kg: float, height_cm: float) -> ClinicalResult:
    if not 25 <= weight_kg <= 350:
        raise ValueError("Масса тела должна быть в диапазоне 25-350 кг")
    if not 120 <= height_cm <= 230:
        raise ValueError("Рост должен быть в диапазоне 120-230 см")
    value = weight_kg / ((height_cm / 100) ** 2)
    if value < 18.5:
        level, interpretation = "moderate", "Недостаточная масса тела"
    elif value < 25:
        level, interpretation = "low", "Диапазон нормальной массы тела"
    elif value < 30:
        level, interpretation = "moderate", "Избыточная масса тела"
    else:
        level, interpretation = "high", "Ожирение по классификации ИМТ"
    return ClinicalResult(
        tool="bmi",
        title="Индекс массы тела",
        value=round(value, 1),
        unit="кг/м²",
        risk_level=level,
        interpretation=interpretation,
        components=[
            Component(name="Масса", value=f"{weight_kg:g} кг"),
            Component(name="Рост", value=f"{height_cm:g} см"),
        ],
        warnings=["ИМТ не различает жировую и мышечную массу и требует контекстной интерпретации."],
        methodology="Масса тела (кг) / рост² (м²).",
        source_url=BMI_SOURCE,
    )


def egfr_ckd_epi_2021(
    age: int,
    sex: Literal["female", "male"],
    creatinine_umol_l: float,
) -> ClinicalResult:
    if not 18 <= age <= 100:
        raise ValueError("CKD-EPI 2021 предназначена для взрослых 18-100 лет")
    if not 20 <= creatinine_umol_l <= 2000:
        raise ValueError("Креатинин должен быть в физиологически проверяемом диапазоне 20-2000 мкмоль/л")
    creatinine_mg_dl = creatinine_umol_l / 88.4
    kappa = 0.7 if sex == "female" else 0.9
    alpha = -0.241 if sex == "female" else -0.302
    ratio = creatinine_mg_dl / kappa
    value = 142 * min(ratio, 1) ** alpha * max(ratio, 1) ** -1.2 * 0.9938**age
    if sex == "female":
        value *= 1.012
    if value >= 90:
        level, interpretation = "low", "G1: сохранённая или высокая расчётная СКФ"
    elif value >= 60:
        level, interpretation = "moderate", "G2: незначительно сниженная расчётная СКФ"
    elif value >= 45:
        level, interpretation = "moderate", "G3a: умеренно сниженная расчётная СКФ"
    elif value >= 30:
        level, interpretation = "high", "G3b: существенно сниженная расчётная СКФ"
    elif value >= 15:
        level, interpretation = "high", "G4: резко сниженная расчётная СКФ"
    else:
        level, interpretation = "critical", "G5: почечная недостаточность по категории СКФ"
    return ClinicalResult(
        tool="egfr_ckd_epi_2021",
        title="CKD-EPI 2021",
        value=round(value, 1),
        unit="мл/мин/1,73 м²",
        risk_level=level,
        interpretation=interpretation,
        components=[
            Component(name="Возраст", value=f"{age} лет"),
            Component(name="Пол", value=sex),
            Component(name="Креатинин", value=f"{creatinine_umol_l:g} мкмоль/л"),
        ],
        warnings=[
            "Одна оценка СКФ не устанавливает хроническую болезнь почек; важны длительность и альбуминурия.",
            "Формула менее надёжна при нестабильном креатинине и нетипичной мышечной массе.",
        ],
        methodology="Расовая-независимая формула CKD-EPI 2021 по креатинину, возрасту и полу.",
        source_url=CKDEPI_SOURCE,
    )


def cockcroft_gault(
    age: int,
    sex: Literal["female", "male"],
    weight_kg: float,
    creatinine_umol_l: float,
) -> ClinicalResult:
    if not 18 <= age <= 100:
        raise ValueError("Возраст должен быть 18-100 лет")
    if not 25 <= weight_kg <= 350:
        raise ValueError("Масса тела должна быть 25-350 кг")
    if not 20 <= creatinine_umol_l <= 2000:
        raise ValueError("Креатинин должен быть 20-2000 мкмоль/л")
    creatinine_mg_dl = creatinine_umol_l / 88.4
    value = ((140 - age) * weight_kg) / (72 * creatinine_mg_dl)
    if sex == "female":
        value *= 0.85
    if value >= 90:
        level = "low"
    elif value >= 50:
        level = "moderate"
    elif value >= 30:
        level = "high"
    else:
        level = "critical"
    return ClinicalResult(
        tool="cockcroft_gault",
        title="Клиренс креатинина Cockcroft-Gault",
        value=round(value, 1),
        unit="мл/мин",
        risk_level=level,
        interpretation="Расчётная оценка клиренса креатинина для контекстной проверки дозирования",
        components=[
            Component(name="Возраст", value=f"{age} лет"),
            Component(name="Масса", value=f"{weight_kg:g} кг"),
            Component(name="Креатинин", value=f"{creatinine_umol_l:g} мкмоль/л"),
        ],
        warnings=[
            "Выбор фактической, идеальной или скорректированной массы зависит от клинического контекста.",
            "Не заменяет инструкцию конкретного препарата и решение врача.",
        ],
        methodology="(140 - возраст) × масса / (72 × креатинин мг/дл), коэффициент 0,85 для женщин.",
        source_url=COCKCROFT_SOURCE,
    )


def qtc_fridericia(qt_ms: float, heart_rate_bpm: float) -> ClinicalResult:
    if not 200 <= qt_ms <= 800:
        raise ValueError("QT должен быть в диапазоне 200-800 мс")
    if not 20 <= heart_rate_bpm <= 250:
        raise ValueError("ЧСС должна быть в диапазоне 20-250 уд/мин")
    rr_seconds = 60 / heart_rate_bpm
    value = qt_ms / math.pow(rr_seconds, 1 / 3)
    if value < 450:
        level, interpretation = "low", "QTcF ниже 450 мс"
    elif value < 480:
        level, interpretation = "moderate", "Пограничное удлинение QTcF"
    elif value < 500:
        level, interpretation = "high", "Выраженное удлинение QTcF"
    else:
        level, interpretation = "critical", "QTcF 500 мс или более: высокий риск требует клинической оценки"
    return ClinicalResult(
        tool="qtc_fridericia",
        title="QTc по Fridericia",
        value=round(value, 0),
        unit="мс",
        risk_level=level,
        interpretation=interpretation,
        components=[
            Component(name="QT", value=f"{qt_ms:g} мс"),
            Component(name="ЧСС", value=f"{heart_rate_bpm:g} уд/мин"),
            Component(name="RR", value=f"{rr_seconds:.3f} с"),
        ],
        warnings=["Автоматическое измерение QT и пороги требуют проверки ЭКГ врачом."],
        methodology="QTcF = QT / RR^(1/3).",
        source_url=QTC_SOURCE,
    )


def child_pugh(
    bilirubin_mg_dl: float,
    albumin_g_dl: float,
    inr: float,
    ascites: Literal["none", "mild", "moderate_severe"],
    encephalopathy_grade: Literal["none", "grade_1_2", "grade_3_4"],
) -> ClinicalResult:
    if not 0.1 <= bilirubin_mg_dl <= 50:
        raise ValueError("Билирубин должен быть 0,1-50 мг/дл")
    if not 0.5 <= albumin_g_dl <= 6:
        raise ValueError("Альбумин должен быть 0,5-6 г/дл")
    if not 0.5 <= inr <= 15:
        raise ValueError("INR должен быть 0,5-15")
    bilirubin_points = 1 if bilirubin_mg_dl < 2 else 2 if bilirubin_mg_dl <= 3 else 3
    albumin_points = 1 if albumin_g_dl > 3.5 else 2 if albumin_g_dl >= 2.8 else 3
    inr_points = 1 if inr < 1.7 else 2 if inr <= 2.3 else 3
    ascites_points = {"none": 1, "mild": 2, "moderate_severe": 3}[ascites]
    encephalopathy_points = {"none": 1, "grade_1_2": 2, "grade_3_4": 3}[encephalopathy_grade]
    total = bilirubin_points + albumin_points + inr_points + ascites_points + encephalopathy_points
    if total <= 6:
        level, interpretation = "moderate", "Класс Child-Pugh A"
    elif total <= 9:
        level, interpretation = "high", "Класс Child-Pugh B"
    else:
        level, interpretation = "critical", "Класс Child-Pugh C"
    return ClinicalResult(
        tool="child_pugh",
        title="Child-Pugh",
        value=float(total),
        unit="баллов",
        risk_level=level,
        interpretation=interpretation,
        components=[
            Component(name="Билирубин", value=f"{bilirubin_mg_dl:g} мг/дл", points=bilirubin_points),
            Component(name="Альбумин", value=f"{albumin_g_dl:g} г/дл", points=albumin_points),
            Component(name="INR", value=f"{inr:g}", points=inr_points),
            Component(name="Асцит", value=ascites, points=ascites_points),
            Component(name="Энцефалопатия", value=encephalopathy_grade, points=encephalopathy_points),
        ],
        warnings=[
            "Для холестатических заболеваний применяются иные пороги билирубина.",
            "Шкала не заменяет оценку причины и динамики печёночной дисфункции.",
        ],
        methodology="Сумма пяти компонентов по 1-3 балла.",
        source_url=CHILD_PUGH_SOURCE,
    )

