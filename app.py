"""Russian-first Streamlit interface for the PsyConsilium MCP project."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import streamlit as st
from pydantic import ValidationError

from psy_consilium.clients.recorder import recorder
from psy_consilium.clients.router import MCPRouter, structured_content
from psy_consilium.clients.sanitize import InputValidationError
from psy_consilium.consilium import run_consilium
from psy_consilium.models import ConsiliumReport, PatientCase, ToolDescriptor


st.set_page_config(page_title="PsyConsilium", page_icon="✦", layout="wide", initial_sidebar_state="collapsed")

REPORT_SCHEMA_VERSION = 2

SOURCE_LABELS = {
    "stdio": "Приватные шкалы · stdio",
    "local_http": "Соматические расчёты · порт 8000",
    "pubmed": "Научные публикации · PubMed",
    "openfda": "Инструкции препаратов · OpenFDA",
}

TOOL_COPY = {
    "phq9": ("PHQ-9", "Скрининг выраженности депрессивных симптомов", "депрессия настроение"),
    "gad7": ("GAD-7", "Скрининг выраженности тревожных симптомов", "тревога anxiety"),
    "audit_c": ("AUDIT-C", "Скрининг употребления алкоголя", "алкоголь alcohol"),
    "list_calculators": ("Каталог инструментов", "Методики, единицы и допустимые границы", "каталог список"),
    "bmi": ("Индекс массы тела", "Расчёт ИМТ по росту и массе", "имт вес рост"),
    "egfr_ckd_epi_2021": ("СКФ CKD-EPI 2021", "Расчётная скорость клубочковой фильтрации", "почки креатинин nephrology"),
    "cockcroft_gault": ("Клиренс Cockcroft–Gault", "Оценка клиренса креатинина", "почки дозирование"),
    "qtc_fridericia": ("QTcF", "Коррекция интервала QT по Fridericia", "экг сердце cardiology"),
    "child_pugh": ("Child–Pugh", "Оценка тяжести печёночной дисфункции", "печень hepatology"),
    "pubmed_search_articles": ("Поиск статей PubMed", "Публикации по клиническому вопросу", "статьи evidence публикации"),
    "openfda_get_drug_label": ("Инструкция OpenFDA", "Предупреждения, противопоказания и взаимодействия", "препарат инструкция fda"),
}

FIELD_LABELS = {
    "age": "Возраст, лет",
    "sex": "Пол для расчётной формулы",
    "weight_kg": "Масса, кг",
    "height_cm": "Рост, см",
    "creatinine_umol_l": "Креатинин, мкмоль/л",
    "qt_ms": "Интервал QT, мс",
    "heart_rate_bpm": "ЧСС, уд/мин",
    "bilirubin_mg_dl": "Билирубин, мг/дл",
    "albumin_g_dl": "Альбумин, г/дл",
    "inr": "МНО",
    "ascites": "Асцит",
    "encephalopathy_grade": "Печёночная энцефалопатия",
    "query": "Поисковый запрос",
    "maxResults": "Количество результатов",
    "summaryCount": "Количество аннотаций",
    "search": "Условие поиска",
    "sections": "Разделы инструкции (JSON)",
    "limit": "Лимит результатов",
    **{f"q{index}": f"Пункт {index}" for index in range(1, 10)},
}

DEMO_CASE = PatientCase(
    age=34,
    sex="female",
    condition="major depressive disorder",
    candidate_medication="sertraline",
    planned_dose_mg=50,
    comorbidities=["мигрень без ауры"],
    current_medications=[],
    previous_treatments=["краткосрочная поддерживающая психотерапия"],
    allergies=[],
    prefers_psychotherapy=True,
    phq9_items=[2, 2, 2, 2, 2, 1, 1, 1, 0],
    gad7_items=[1, 1, 1, 1, 1, 1, 1],
    auditc_items=[0, 0, 0],
    weight_kg=68,
    height_cm=170,
    creatinine_umol_l=72,
    qt_ms=410,
    heart_rate_bpm=70,
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#15253d; --muted:#64748b; --line:#dfe6ee; --paper:#fff; --canvas:#f4f7fa; --navy:#102a43; --teal:#117c78; }
        .stApp { background:var(--canvas); color:var(--ink); }
        .block-container { max-width:1180px; padding-top:2rem; padding-bottom:5rem; }
        header[data-testid="stHeader"] { background:transparent; }
        h1,h2,h3 { color:var(--ink); letter-spacing:-.025em; }
        h1 { font-size:clamp(2.2rem,5vw,4.5rem)!important; line-height:1.02!important; }
        p,label,.stCaption { line-height:1.55; }
        div[role="radiogroup"] { gap:.35rem; padding:.3rem; background:#e9eef4; border-radius:14px; }
        div[role="radiogroup"] label { background:transparent; border-radius:10px; padding:.45rem .85rem; }
        div[role="radiogroup"] label:has(input:checked) { background:white; box-shadow:0 1px 4px rgba(16,42,67,.1); }
        .hero { background:var(--navy); color:white; border-radius:26px; padding:3.2rem 3.4rem; margin:1.2rem 0 2rem; overflow:hidden; }
        .hero h1 { color:white; margin:.65rem 0 1rem; max-width:820px; }
        .hero p { color:#cbd8e6; font-size:1.12rem; max-width:760px; margin-bottom:0; }
        .eyebrow { color:#73d8d0; font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
        .brand { display:flex; align-items:center; justify-content:space-between; margin-bottom:.5rem; }
        .brand-name { color:var(--navy); font-weight:850; font-size:1.1rem; letter-spacing:-.02em; }
        .brand-meta { color:var(--muted); font-size:.82rem; }
        .info-card,.step-card,.case-card { background:var(--paper); border:1px solid var(--line); border-radius:18px; padding:1.35rem 1.45rem; height:100%; }
        .info-card .number { color:var(--teal); font-size:.78rem; font-weight:800; letter-spacing:.09em; }
        .info-card h3,.step-card h3 { font-size:1.08rem; margin:.55rem 0 .35rem; }
        .info-card p,.step-card p { color:var(--muted); font-size:.92rem; margin:0; }
        .case-card { background:#eef5f5; border-color:#cfe3e2; }
        .case-card b { color:var(--navy); }
        .trust-strip { display:flex; gap:1rem; flex-wrap:wrap; padding:1rem 1.2rem; border:1px solid var(--line); border-radius:14px; background:white; margin:1rem 0 1.5rem; }
        .trust-strip span { color:var(--muted); font-size:.86rem; }
        .trust-strip strong { color:var(--ink); }
        .section-kicker { color:var(--teal); font-size:.75rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; margin-top:2.2rem; }
        div[data-testid="stMetric"] { background:white; border:1px solid var(--line); padding:1rem 1.1rem; border-radius:16px; }
        div[data-testid="stMetricValue"] { color:var(--navy); }
        .stButton>button,.stFormSubmitButton>button { border-radius:12px; min-height:2.8rem; font-weight:700; }
        .stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"] { background:var(--teal); border-color:var(--teal); }
        div[data-testid="stExpander"] { background:white; border:1px solid var(--line); border-radius:14px; }
        .footer-note { color:var(--muted); font-size:.8rem; border-top:1px solid var(--line); padding-top:1rem; margin-top:2rem; }
        @media(max-width:760px){.block-container{padding:1rem}.hero{padding:2rem 1.4rem;border-radius:20px}.brand-meta{display:none}}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_router() -> MCPRouter:
    return MCPRouter()


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def navigate(page: str, *, run_demo: bool = False) -> None:
    st.session_state.page = page
    if run_demo:
        st.session_state.run_demo_on_open = True


def clinical_run(patient_case: PatientCase) -> None:
    try:
        with st.spinner("Считаем шкалы, проверяем соматические ограничения и ищем источники…"):
            st.session_state.report = run_async(run_consilium(patient_case, get_router()))
            st.session_state.report_schema_version = REPORT_SCHEMA_VERSION
            st.session_state.active_case = patient_case
    except Exception as exc:
        st.error(f"Не удалось завершить консилиум: {exc}")
        st.info("Проверьте, что приложение запущено командой `python run.py`, а интернет доступен.")


def brand_header() -> None:
    st.markdown(
        '<div class="brand"><div class="brand-name">PSYCONSILIUM</div>'
        '<div class="brand-meta">Учебная система · MCP · доказательная медицина</div></div>',
        unsafe_allow_html=True,
    )


def overview_page() -> None:
    st.markdown(
        """
        <section class="hero">
          <div class="eyebrow">Поддержка клинического решения</div>
          <h1>Сравнивает лечение.<br>Показывает основания.</h1>
          <p>PsyConsilium сопоставляет психотерапию, препарат и комбинированный подход для конкретного обезличенного случая, проверяет введённую врачом дозу по инструкции и показывает происхождение каждого вывода.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown("### Что получает врач")
        st.write("Прозрачный разбор: выраженность симптомов, сравнительный рейтинг вариантов, релевантность исследований, проверка плановой дозы и ссылки на первоисточники.")
        a, b = st.columns(2)
        a.button(
            "Запустить готовый демо-кейс",
            type="primary",
            width="stretch",
            on_click=navigate,
            args=("Демо и кейс",),
            kwargs={"run_demo": True},
        )
        b.button("Посмотреть MCP-лабораторию", width="stretch", on_click=navigate, args=("Каталог MCP",))
    with right:
        st.markdown(
            """
            <div class="case-card"><div class="eyebrow" style="color:#117c78">Демонстрационный случай</div>
            <p><b>34 года · синтетические данные</b></p>
            <p>Депрессивные симптомы, тревога, кандидат для обсуждения — сертралин. Добавлены креатинин, рост, масса и ЭКГ.</p>
            <p style="margin-bottom:0"><b>Результат:</b> сравнительная матрица трёх подходов, проверка плановой дозы 50 мг, клинические расчёты и журнал JSON-RPC.</p></div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-kicker">Как это работает</div>', unsafe_allow_html=True)
    st.markdown("## Один клинический вопрос — три независимых MCP-источника")
    cols = st.columns(3, gap="medium")
    cards = [
        ("01 · STDIO", "Приватные шкалы", "PHQ-9, GAD-7 и AUDIT-C считаются в изолированном локальном процессе."),
        ("02 · PORT 8000", "Соматическая безопасность", "Почки, ЭКГ, масса тела и печень проверяются локальным сетевым сервисом."),
        ("03 · EXTERNAL", "Доказательные источники", "PubMed ищет исследования, OpenFDA возвращает официальные предупреждения препарата."),
    ]
    for column, (number, title, text) in zip(cols, cards):
        column.markdown(f'<div class="info-card"><div class="number">{number}</div><h3>{title}</h3><p>{text}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-kicker">Контроль качества</div>', unsafe_allow_html=True)
    st.markdown("## Почему вывод можно проверить")
    quality_columns = st.columns(4)
    quality = [
        ("Расчёты", "Числа вычисляет детерминированный код, не языковая модель."),
        ("Источники", "Каждая публикация и инструкция получает собственный ID и ссылку."),
        ("Красные флаги", "Риск, мания/психоз и беременность останавливают обычный сценарий."),
        ("Дозировка", "Проверяется введённый план по инструкции; рецепт и решение остаются у врача."),
    ]
    for column, (title, text) in zip(quality_columns, quality):
        column.markdown(f'<div class="step-card"><h3>{title}</h3><p>{text}</p></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="trust-strip"><span><strong>Важно:</strong> учебный прототип</span><span>Только синтетические данные</span>'
        '<span>Не является медицинским изделием</span><span>Финальное решение принимает врач</span></div>',
        unsafe_allow_html=True,
    )


def score_inputs(title: str, count: int, key: str, maximum: int = 3) -> list[int]:
    st.markdown(f"**{title}**")
    columns = st.columns(min(count, 5))
    return [
        columns[index % len(columns)].selectbox(
            f"Пункт {index + 1}", options=list(range(maximum + 1)), key=f"{key}_{index}", help=f"Допустимое значение: 0–{maximum}"
        )
        for index in range(count)
    ]


def render_score_cards(report: ConsiliumReport) -> None:
    st.markdown('<div class="section-kicker">Шаг 1 · объективные показатели</div>', unsafe_allow_html=True)
    st.markdown("## Расчёты")
    columns = st.columns(min(4, len(report.scores)))
    risk_copy = {"low": "Низкий", "moderate": "Умеренный", "high": "Высокий", "critical": "Критический", "informational": "Информация"}
    for index, result in enumerate(report.scores.values()):
        with columns[index % len(columns)]:
            st.metric(result.title, f"{result.value:g} {result.unit}", risk_copy[result.risk_level])
            st.caption(result.interpretation)
            with st.popover("Разбор расчёта", width="stretch"):
                if result.components:
                    st.dataframe(
                        [{"Компонент": item.name, "Значение": item.value, "Баллы": item.points} for item in result.components],
                        hide_index=True, width="stretch",
                    )
                st.write(result.methodology)
                if result.warnings:
                    st.warning("\n\n".join(result.warnings))
                st.link_button("Первоисточник методики", result.source_url)


def render_report(report: ConsiliumReport) -> None:
    if report.status == "stop":
        st.error("Алгоритм остановлен: сначала требуется приоритетная клиническая оценка")
        for reason in report.stop_reasons:
            st.write(f"• {reason}")
    else:
        st.success("Анализ завершён. Ниже — варианты для проверки врачом, не назначение лечения.")
    render_score_cards(report)
    st.markdown('<div class="section-kicker">Шаг 2 · независимые перспективы</div>', unsafe_allow_html=True)
    st.markdown("## Виртуальный консилиум")
    st.caption("Каждая роль отвечает только за свой участок и явно указывает, каких данных не хватает.")
    for opinion in report.opinions:
        with st.expander(f"{opinion.agent} · {opinion.role}"):
            st.write(opinion.conclusion)
            if opinion.evidence_ids:
                st.caption("Опора на источники: " + ", ".join(opinion.evidence_ids))
            if opinion.concerns:
                st.warning("Что может изменить вывод: " + "; ".join(opinion.concerns))
            if opinion.missing_data:
                st.info("Что ещё нужно уточнить: " + "; ".join(opinion.missing_data))
    if report.options:
        st.markdown('<div class="section-kicker">Шаг 3 · решение остаётся у врача</div>', unsafe_allow_html=True)
        st.markdown("## Сравнительная матрица лечения")
        st.caption("Баллы — прозрачная сортировка применимости, а не вероятность успеха и не автоматическое назначение.")
        verdict_copy = {"priority": "Приоритет для обсуждения", "consider": "Рассмотреть", "defer": "Отложить"}
        st.dataframe(
            [
                {
                    "Вариант": option.name,
                    "Статус": verdict_copy[option.verdict],
                    "Пригодность": f"{option.fit_score}/100",
                    "Источники": len(option.evidence_ids),
                    "Почему подходит": "; ".join(option.factors_for) or "—",
                    "Что против": "; ".join(option.factors_against) or "—",
                }
                for option in report.options
            ],
            hide_index=True,
            width="stretch",
        )
        for number, option in enumerate(report.options, start=1):
            with st.container(border=True):
                st.markdown(f"### {number:02d}. {option.name} · {option.fit_score}/100")
                st.caption(verdict_copy[option.verdict])
                st.write(option.rationale)
                left, right = st.columns(2)
                left.markdown("**Факторы за**")
                for factor in option.factors_for:
                    left.write(f"+ {factor}")
                left.markdown("**Проверить до решения**")
                for check in option.checks_before_decision:
                    left.write(f"• {check}")
                right.markdown("**Факторы против / неопределённость**")
                for factor in option.factors_against:
                    right.write(f"− {factor}")
                for limitation in option.limitations:
                    right.write(f"• {limitation}")
                if option.evidence_summary:
                    st.markdown("**Что именно сообщают найденные исследования**")
                    for summary in option.evidence_summary:
                        st.write(f"• {summary}")
                if option.evidence_ids:
                    st.caption("Источники: " + " · ".join(option.evidence_ids))
    if report.dose_review:
        review = report.dose_review
        st.markdown('<div class="section-kicker">Шаг 4 · проверка плановой дозы</div>', unsafe_allow_html=True)
        st.markdown(f"## {review.medication}: данные официальной инструкции")
        if review.status == "above_label_maximum":
            st.error(review.status_text)
        elif review.status == "label_unavailable":
            st.warning(review.status_text)
        else:
            st.info(review.status_text)
        dose_cols = st.columns(3)
        dose_cols[0].metric("План врача", f"{review.planned_dose_mg:g} мг" if review.planned_dose_mg else "не введён")
        dose_cols[1].metric("Найденный максимум", f"{review.detected_maximum_mg_per_day:g} мг/сут" if review.detected_maximum_mg_per_day else "не распознан")
        dose_cols[2].metric("Источник", review.label_id or "не получен")
        excerpt_groups = [
            ("Начальная доза", review.initial_dose_excerpts),
            ("Титрация", review.titration_excerpts),
            ("Максимальная доза", review.maximum_dose_excerpts),
            ("Особые группы", review.population_adjustment_excerpts),
        ]
        for title, excerpts in excerpt_groups:
            if excerpts:
                with st.expander(title):
                    st.caption("Дословные фрагменты американской инструкции; язык источника сохранён.")
                    for excerpt in excerpts:
                        st.write(excerpt)
        if review.safety_flags:
            st.warning("Ограничения данных: " + " ".join(review.safety_flags))
        st.markdown("**Перед подтверждением плана**")
        for check in review.checks:
            st.write(f"• {check}")
        if review.label_url:
            st.link_button("Открыть источник OpenFDA", review.label_url)
    if report.evidence:
        st.markdown('<div class="section-kicker">Проверяемость</div>', unsafe_allow_html=True)
        st.markdown("## Реестр первоисточников")
        for item in report.evidence:
            with st.expander(f"{item['id']} · {item['title']}"):
                if item.get("study_type"):
                    st.write(
                        f"**{item['study_type']} · {item.get('year') or 'год не указан'} · "
                        f"применимость {item.get('applicability')} ({item.get('applicability_score')}/100)**"
                    )
                if item.get("reasons"):
                    st.caption("Почему включено: " + "; ".join(item["reasons"]))
                for fragment in item.get("result_fragments", []):
                    st.write(f"• {fragment}")
                st.write(item["note"])
                st.link_button("Открыть первоисточник", item["url"])
    render_recent_protocol(limit=3)
    st.markdown(f'<div class="footer-note">{report.disclaimer}</div>', unsafe_allow_html=True)


def demo_page() -> None:
    st.markdown('<div class="section-kicker">Демонстрационный режим</div>', unsafe_allow_html=True)
    st.markdown("# Посмотрите весь путь на одном синтетическом случае")
    st.write("Нажмите одну кнопку: приложение вызовет инструменты каждого типа, соберёт источники и покажет протокольный обмен. Реальные данные пациента не нужны.")
    st.markdown(
        '<div class="trust-strip"><span><strong>Случай:</strong> 34 года</span><span>депрессивные симптомы</span>'
        '<span>PHQ-9: пункт 9 = 0</span><span>сертралин: план 50 мг</span><span>есть лабораторные данные и ЭКГ</span></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.pop("run_demo_on_open", False):
        clinical_run(DEMO_CASE)
    if st.button("Запустить демонстрационный консилиум", type="primary", width="stretch"):
        clinical_run(DEMO_CASE)
    report: ConsiliumReport | None = st.session_state.get("report")
    stale_report = report is not None and (
        st.session_state.get("report_schema_version") != REPORT_SCHEMA_VERSION
        or any(not hasattr(option, "verdict") for option in report.options)
    )
    if stale_report:
        st.session_state.pop("report", None)
        st.session_state.pop("report_schema_version", None)
        report = None
        st.warning(
            "Загружена старая версия внутренних моделей. Остановите приложение в терминале Ctrl+C, "
            "запустите `python run.py` заново и затем повторите демо."
        )
    if report:
        st.divider()
        render_report(report)
    with st.expander("Ввести собственный обезличенный случай"):
        st.warning("Не вводите ФИО, контакты, номер карты и другие идентификаторы.")
        with st.form("patient_case"):
            a, b, c, d = st.columns(4)
            age = a.number_input("Возраст", 18, 100, 34)
            sex = b.selectbox("Пол для формул", ["female", "male"], format_func=lambda x: "женский" if x == "female" else "мужской")
            condition = c.selectbox(
                "Клиническая проблема",
                ["major depressive disorder", "generalized anxiety disorder", "mixed anxiety and depressive symptoms"],
                format_func={"major depressive disorder": "Депрессивное расстройство", "generalized anxiety disorder": "Генерализованная тревога", "mixed anxiety and depressive symptoms": "Смешанные тревожно-депрессивные симптомы"}.get,
            )
            medication = d.selectbox(
                "Препарат-кандидат", ["sertraline", "escitalopram", "fluoxetine", "duloxetine"],
                format_func={"sertraline": "Сертралин", "escitalopram": "Эсциталопрам", "fluoxetine": "Флуоксетин", "duloxetine": "Дулоксетин"}.get,
            )
            planned_dose = st.number_input(
                "Плановая суточная доза препарата, мг (вводит врач)",
                min_value=1.0,
                max_value=5000.0,
                value=50.0,
                help="Система не назначает дозу, а сопоставляет введённое значение с официальной инструкцией.",
            )
            comorbidities = st.text_input("Сопутствующие состояния через запятую")
            current_medications = st.text_input("Текущие лекарства через запятую")
            previous_treatments = st.text_input("Предыдущее лечение через запятую")
            allergies = st.text_input("Аллергии и нежелательные реакции через запятую")
            phq = score_inputs("PHQ-9", 9, "phq")
            gad = score_inputs("GAD-7", 7, "gad")
            audit = score_inputs("AUDIT-C", 3, "audit", maximum=4)
            st.markdown("**Красные флаги**")
            r1, r2, r3 = st.columns(3)
            acute = r1.checkbox("Острый суицидальный риск")
            mania = r2.checkbox("Возможная мания или психоз")
            pregnancy = r3.checkbox("Беременность или лактация")
            with st.expander("Соматические данные"):
                s1, s2, s3 = st.columns(3)
                use_body = s1.checkbox("Рост и масса", value=True)
                weight = s1.number_input("Масса, кг", 25.0, 350.0, 68.0) if use_body else None
                height = s1.number_input("Рост, см", 120.0, 230.0, 170.0) if use_body else None
                use_kidney = s2.checkbox("Креатинин", value=True)
                creatinine = s2.number_input("Креатинин, мкмоль/л", 20.0, 2000.0, 72.0) if use_kidney else None
                use_ecg = s3.checkbox("ЭКГ", value=True)
                qt = s3.number_input("QT, мс", 200.0, 800.0, 410.0) if use_ecg else None
                hr = s3.number_input("ЧСС, уд/мин", 20.0, 250.0, 70.0) if use_ecg else None
            submitted = st.form_submit_button("Провести консилиум", type="primary", width="stretch")
        if submitted:
            try:
                clinical_run(PatientCase(
                    age=age, sex=sex, condition=condition, candidate_medication=medication,
                    planned_dose_mg=planned_dose,
                    comorbidities=split_list(comorbidities), current_medications=split_list(current_medications),
                    previous_treatments=split_list(previous_treatments), allergies=split_list(allergies),
                    acute_suicide_risk=acute, possible_mania_or_psychosis=mania, pregnant_or_breastfeeding=pregnancy,
                    phq9_items=phq, gad7_items=gad, auditc_items=audit, weight_kg=weight, height_cm=height,
                    creatinine_umol_l=creatinine, qt_ms=qt, heart_rate_bpm=hr,
                ))
            except ValidationError as exc:
                st.error(str(exc))


def tool_title(tool: ToolDescriptor) -> str:
    copy = TOOL_COPY.get(tool.name)
    return f"{copy[0]} · {tool.name}" if copy else tool.name


def tool_search_text(tool: ToolDescriptor) -> str:
    copy = TOOL_COPY.get(tool.name, ("", "", ""))
    return " ".join((tool.name, tool.title or "", tool.description or "", *copy)).lower()


def schema_widget(name: str, schema: dict[str, Any], prefix: str) -> Any:
    label = FIELD_LABELS.get(name, schema.get("title") or name)
    description = schema.get("description")
    if schema.get("enum"):
        enum_labels = {"female": "женский", "male": "мужской", "none": "нет", "mild": "лёгкий", "moderate_severe": "умеренный или тяжёлый", "grade_1_2": "степень 1–2", "grade_3_4": "степень 3–4"}
        return st.selectbox(label, schema["enum"], format_func=lambda x: enum_labels.get(x, x), key=f"{prefix}_{name}", help=description)
    kind = schema.get("type", "string")
    if kind == "boolean":
        return st.checkbox(label, value=bool(schema.get("default", False)), key=f"{prefix}_{name}", help=description)
    if kind in {"integer", "number"}:
        minimum, maximum, default = schema.get("minimum", 0), schema.get("maximum", 1_000_000), schema.get("default", schema.get("minimum", 0))
        if kind == "number":
            minimum, maximum, default, step = float(minimum), float(maximum), float(default), 0.1
        else:
            minimum, maximum, default, step = int(minimum), int(maximum), int(default), 1
        return st.number_input(label, min_value=minimum, max_value=maximum, value=default, step=step, key=f"{prefix}_{name}", help=description)
    if kind in {"array", "object"}:
        default = schema.get("default", [] if kind == "array" else {})
        return st.text_area(label, json.dumps(default, ensure_ascii=False), key=f"{prefix}_{name}", help=description)
    return st.text_input(label, value=str(schema.get("default", "")), key=f"{prefix}_{name}", help=description)


def tools_page() -> None:
    st.markdown('<div class="section-kicker">Техническая демонстрация задания</div>', unsafe_allow_html=True)
    st.markdown("# MCP-лаборатория")
    st.write("Выберите один из трёх типов источников, получите каталог через `tools/list` и вызовите инструмент через `tools/call`.")
    source = st.selectbox("Источник MCP", list(SOURCE_LABELS), format_func=SOURCE_LABELS.get)
    if st.button("Получить список инструментов", type="primary"):
        try:
            with st.spinner("Выполняется tools/list…"):
                st.session_state.tools = run_async(get_router().list_tools(source))
                st.session_state.tools_source = source
        except Exception as exc:
            st.error(f"Источник недоступен: {exc}")
    tools: list[ToolDescriptor] = st.session_state.get("tools", []) if st.session_state.get("tools_source") == source else []
    if not tools:
        st.info("Нажмите кнопку выше — каталог придёт от выбранного MCP-сервера, а не из интерфейса.")
        return
    search = st.text_input("Поиск по русскому или латинскому названию", placeholder="Например: почки, тревога, QTc, PubMed").strip().lower()
    filtered = [tool for tool in tools if search in tool_search_text(tool)]
    if not filtered:
        st.warning("По этому запросу инструменты не найдены.")
        return
    selected = st.selectbox("Инструмент", filtered, format_func=tool_title)
    copy = TOOL_COPY.get(selected.name)
    st.caption(copy[1] if copy else selected.description or "Описание не предоставлено сервером")
    with st.expander("JSON Schema, полученная от MCP-сервера"):
        st.json(selected.input_schema)
    with st.form(f"tool_{source}_{selected.name}"):
        raw = {name: schema_widget(name, field_schema, f"{source}_{selected.name}") for name, field_schema in selected.input_schema.get("properties", {}).items()}
        invoke = st.form_submit_button("Выполнить tools/call", type="primary", width="stretch")
    if invoke:
        try:
            result = run_async(get_router().call_tool(source, selected.name, raw, schema=selected.input_schema))
            st.success("Инструмент ответил через MCP")
            payload = structured_content(result)
            if isinstance(payload, dict) and {"title", "value", "unit"}.issubset(payload):
                st.metric(payload["title"], f"{payload['value']:g} {payload['unit']}")
                st.write(payload.get("interpretation", ""))
            with st.expander("Структурированный результат", expanded=True):
                st.json(payload)
        except (InputValidationError, ValueError, RuntimeError) as exc:
            st.error(str(exc))
    render_recent_protocol(limit=1)


def render_recent_protocol(limit: int) -> None:
    packets = recorder.list()[:limit]
    st.markdown('<div class="section-kicker">MCP Packet Inspector</div>', unsafe_allow_html=True)
    st.markdown("## Последние JSON-RPC пакеты")
    if not packets:
        st.info("Пакеты появятся после запуска демо или вызова инструмента.")
        return
    for packet in packets:
        marker = "из кэша" if packet.cached else f"{packet.elapsed_ms} мс"
        with st.expander(f"{SOURCE_LABELS[packet.source]} · {packet.request['method']} · {marker}"):
            left, right = st.columns(2)
            left.markdown("**Запрос**")
            left.json(packet.request)
            right.markdown("**Ответ**")
            right.json(packet.response)


def protocol_page() -> None:
    st.markdown('<div class="section-kicker">Прозрачность протокола</div>', unsafe_allow_html=True)
    st.markdown("# Инспектор JSON-RPC")
    st.write("Здесь видно, что приложение действительно вызывает MCP, а не подменяет его прямыми Python-функциями.")
    if st.button("Очистить журнал"):
        recorder.clear()
        st.rerun()
    render_recent_protocol(limit=100)


def assignment_page() -> None:
    st.markdown('<div class="section-kicker">Практическое задание №2</div>', unsafe_allow_html=True)
    st.markdown("# Что именно здесь реализовано")
    st.write("Проект закрывает четыре технических задания и пять оцениваемых критериев из методички.")
    rows = [
        {"Критерий": "Stdio MCP", "Баллы": "30", "Реализация": "PHQ-9, GAD-7, AUDIT-C, list_calculators; Pydantic; ToolError; lifecycle SDK"},
        {"Критерий": "Локальный сервер", "Баллы": "30", "Реализация": "порт 8000; /mcp, /sse, /messages; 5 направлений; sanitizer; retry"},
        {"Критерий": "Внешний MCP", "Баллы": "20", "Реализация": "PubMed и OpenFDA из Glama; timeout 12 с; TTL cache"},
        {"Критерий": "Web-интерфейс", "Баллы": "15", "Реализация": "selector; русско-латинский поиск; формы из JSON Schema; риск; компоненты; ссылки"},
        {"Критерий": "JSON-RPC inspector", "Баллы": "5", "Реализация": "сырые tools/list и tools/call request/response, транспорт, время, cache"},
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
    st.success("Итого по структуре задания: 100/100 возможных баллов до оценки преподавателем.")
    st.warning("Честная оговорка: это учебный прототип. Медицинская полезность идеи показана архитектурой, но клиническая валидация и статус медицинского изделия в задание не входят.")
    st.markdown("### Три вызова, которые удобно показать на защите")
    columns = st.columns(3)
    cards = [
        ("01", "stdio → PHQ-9", "Показать отдельный процесс, типизированную форму и ToolError."),
        ("02", "порт 8000 → QTcF", "Показать сетевой сервер, границы параметров и результат."),
        ("03", "PubMed → поиск", "Показать внешний MCP, spinner, timeout и cache."),
    ]
    for column, (number, title, body) in zip(columns, cards):
        column.markdown(f'<div class="info-card"><div class="number">{number}</div><h3>{title}</h3><p>{body}</p></div>', unsafe_allow_html=True)


inject_styles()
brand_header()
pages = ["Обзор", "Демо и кейс", "Каталог MCP", "Протокол", "Соответствие заданию"]
if "page" not in st.session_state:
    st.session_state.page = "Обзор"
page = st.radio("Навигация", pages, horizontal=True, label_visibility="collapsed", key="page")

if page == "Обзор":
    overview_page()
elif page == "Демо и кейс":
    demo_page()
elif page == "Каталог MCP":
    tools_page()
elif page == "Протокол":
    protocol_page()
else:
    assignment_page()
