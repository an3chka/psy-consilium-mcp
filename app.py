"""Streamlit front end for the PsyConsilium MCP coursework project."""

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


st.set_page_config(page_title="PsyConsilium MCP", page_icon="🩺", layout="wide")


@st.cache_resource
def get_router() -> MCPRouter:
    return MCPRouter()


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def score_inputs(title: str, count: int, key: str, maximum: int = 3) -> list[int]:
    st.markdown(f"**{title}**")
    columns = st.columns(min(count, 5))
    return [
        columns[index % len(columns)].selectbox(
            f"Пункт {index + 1}",
            options=list(range(maximum + 1)),
            key=f"{key}_{index}",
            help="0 — совсем нет; 3 — почти каждый день",
        )
        for index in range(count)
    ]


def render_report(report: ConsiliumReport) -> None:
    if report.status == "stop":
        st.error("Обычный алгоритм остановлен: требуется приоритетная очная оценка")
        for reason in report.stop_reasons:
            st.write(f"• {reason}")
    else:
        st.success("Консилиум сформировал варианты для проверки врачом — это не назначение")

    st.subheader("Проверяемые расчёты")
    columns = st.columns(min(4, len(report.scores)))
    risk_icons = {"low": "🟢", "moderate": "🟡", "high": "🟠", "critical": "🔴", "informational": "🔵"}
    for index, result in enumerate(report.scores.values()):
        with columns[index % len(columns)]:
            st.metric(result.title, f"{result.value:g} {result.unit}")
            st.caption(f"{risk_icons[result.risk_level]} {result.interpretation}")
            with st.popover("Методика и источник"):
                st.write(result.methodology)
                st.link_button("Открыть источник", result.source_url)
                if result.warnings:
                    st.warning("\n\n".join(result.warnings))

    st.subheader("Мнения участников консилиума")
    for opinion in report.opinions:
        with st.expander(f"{opinion.agent} — {opinion.role}"):
            st.write(opinion.conclusion)
            if opinion.evidence_ids:
                st.caption("Источники: " + ", ".join(opinion.evidence_ids))
            if opinion.concerns:
                st.warning("Ограничения: " + "; ".join(opinion.concerns))
            if opinion.missing_data:
                st.info("Не хватает: " + "; ".join(opinion.missing_data))

    if report.options:
        st.subheader("Варианты для врачебного обсуждения")
        for option in report.options:
            with st.container(border=True):
                st.markdown(f"#### {option.name}")
                st.write(option.rationale)
                st.caption("Проверить до решения: " + "; ".join(option.checks_before_decision))
                st.caption("Ограничения: " + "; ".join(option.limitations))
                if option.evidence_ids:
                    st.code(" · ".join(option.evidence_ids), language=None)

    if report.evidence:
        st.subheader("Реестр источников")
        for item in report.evidence:
            with st.expander(f"{item['id']} — {item['title']}"):
                st.write(item["note"])
                st.link_button("Открыть первоисточник", item["url"])
    st.caption(report.disclaimer)


def case_tab() -> None:
    st.header("Обезличенный клинический случай")
    st.info("Используйте только синтетические или полностью обезличенные данные. Полей ФИО и номера карты в модели нет.")
    with st.form("patient_case"):
        a, b, c, d = st.columns(4)
        age = a.number_input("Возраст", 18, 100, 34)
        sex = b.selectbox("Пол для формул", ["female", "male"], format_func=lambda x: "женский" if x == "female" else "мужской")
        condition = c.selectbox(
            "Рабочая проблема",
            ["major depressive disorder", "generalized anxiety disorder", "mixed anxiety and depressive symptoms"],
        )
        medication = d.selectbox("Препарат-кандидат", ["sertraline", "escitalopram", "fluoxetine", "duloxetine"])
        comorbidities = st.text_input("Сопутствующие состояния, через запятую", "")
        current_medications = st.text_input("Текущие лекарства, через запятую", "")
        previous_treatments = st.text_input("Предыдущее лечение, через запятую", "")
        allergies = st.text_input("Аллергии/нежелательные реакции, через запятую", "")

        phq = score_inputs("PHQ-9", 9, "phq")
        gad = score_inputs("GAD-7", 7, "gad")
        audit = score_inputs("AUDIT-C", 3, "audit", maximum=4)

        st.markdown("**Красные флаги**")
        r1, r2, r3 = st.columns(3)
        acute = r1.checkbox("Острый суицидальный риск")
        mania = r2.checkbox("Возможная мания или психоз")
        pregnancy = r3.checkbox("Беременность или лактация")

        with st.expander("Дополнительные соматические данные"):
            s1, s2, s3 = st.columns(3)
            use_body = s1.checkbox("Добавить рост и массу", value=True)
            weight = s1.number_input("Масса, кг", 25.0, 350.0, 68.0) if use_body else None
            height = s1.number_input("Рост, см", 120.0, 230.0, 170.0) if use_body else None
            use_kidney = s2.checkbox("Добавить креатинин", value=True)
            creatinine = s2.number_input("Креатинин, мкмоль/л", 20.0, 2000.0, 72.0) if use_kidney else None
            use_ecg = s3.checkbox("Добавить ЭКГ", value=True)
            qt = s3.number_input("QT, мс", 200.0, 800.0, 410.0) if use_ecg else None
            hr = s3.number_input("ЧСС, уд/мин", 20.0, 250.0, 70.0) if use_ecg else None

        submitted = st.form_submit_button("Созвать консилиум", type="primary", use_container_width=True)

    if submitted:
        try:
            patient_case = PatientCase(
                age=age,
                sex=sex,
                condition=condition,
                candidate_medication=medication,
                comorbidities=split_list(comorbidities),
                current_medications=split_list(current_medications),
                previous_treatments=split_list(previous_treatments),
                allergies=split_list(allergies),
                acute_suicide_risk=acute,
                possible_mania_or_psychosis=mania,
                pregnant_or_breastfeeding=pregnancy,
                phq9_items=phq,
                gad7_items=gad,
                auditc_items=audit,
                weight_kg=weight,
                height_cm=height,
                creatinine_umol_l=creatinine,
                qt_ms=qt,
                heart_rate_bpm=hr,
            )
            with st.spinner("MCP-инструменты считают показатели и проверяют источники…"):
                st.session_state.report = run_async(run_consilium(patient_case, get_router()))
        except (ValidationError, ValueError, RuntimeError) as exc:
            st.error(str(exc))

    report = st.session_state.get("report")
    if report:
        st.divider()
        render_report(report)


def schema_widget(name: str, schema: dict[str, Any], prefix: str) -> Any:
    label = schema.get("title") or name
    description = schema.get("description")
    if schema.get("enum"):
        return st.selectbox(label, schema["enum"], key=f"{prefix}_{name}", help=description)
    kind = schema.get("type", "string")
    if kind == "boolean":
        return st.checkbox(label, value=bool(schema.get("default", False)), key=f"{prefix}_{name}", help=description)
    if kind in {"integer", "number"}:
        minimum = schema.get("minimum", 0)
        maximum = schema.get("maximum", 1_000_000)
        default = schema.get("default", minimum)
        if kind == "number":
            minimum, maximum, default = float(minimum), float(maximum), float(default)
            step = 0.1
        else:
            minimum, maximum, default, step = int(minimum), int(maximum), int(default), 1
        return st.number_input(label, min_value=minimum, max_value=maximum, value=default, step=step, key=f"{prefix}_{name}", help=description)
    if kind in {"array", "object"}:
        default = schema.get("default", [] if kind == "array" else {})
        return st.text_area(label + " (JSON)", json.dumps(default, ensure_ascii=False), key=f"{prefix}_{name}", help=description)
    return st.text_input(label, value=str(schema.get("default", "")), key=f"{prefix}_{name}", help=description)


def tools_tab() -> None:
    st.header("MCP Tool Explorer")
    labels = {"stdio": "Private stdio", "local_http": "Local HTTP", "pubmed": "PubMed external", "openfda": "OpenFDA external"}
    source = st.selectbox("Источник", list(labels), format_func=labels.get)
    if st.button("Получить tools/list", type="primary"):
        try:
            with st.spinner("MCP discovery…"):
                st.session_state.tools = run_async(get_router().list_tools(source))
                st.session_state.tools_source = source
        except Exception as exc:
            st.error(f"Источник недоступен: {exc}")
    tools: list[ToolDescriptor] = st.session_state.get("tools", []) if st.session_state.get("tools_source") == source else []
    if not tools:
        return
    search = st.text_input("Поиск по инструментам").lower()
    filtered = [tool for tool in tools if search in (tool.name + " " + (tool.description or "")).lower()]
    if not filtered:
        st.warning("Ничего не найдено")
        return
    selected = st.selectbox("Инструмент", filtered, format_func=lambda tool: tool.name)
    st.caption(selected.description or "Описание не предоставлено сервером")
    with st.form(f"tool_{source}_{selected.name}"):
        raw = {
            name: schema_widget(name, field_schema, f"{source}_{selected.name}")
            for name, field_schema in selected.input_schema.get("properties", {}).items()
        }
        invoke = st.form_submit_button("Вызвать tools/call", type="primary")
    if invoke:
        try:
            result = run_async(get_router().call_tool(source, selected.name, raw, schema=selected.input_schema))
            st.success("Ответ получен через MCP")
            st.json(structured_content(result))
        except (InputValidationError, Exception) as exc:
            st.error(str(exc))


def protocol_tab() -> None:
    st.header("Инспектор JSON-RPC")
    st.caption("Пакеты записываются вокруг реальных вызовов SDK; секреты и персональные идентификаторы не журналируются.")
    if st.button("Очистить журнал"):
        recorder.clear()
        st.rerun()
    packets = recorder.list()
    if not packets:
        st.info("Сначала запустите консилиум или Tool Explorer.")
    for packet in packets:
        marker = "cache" if packet.cached else f"{packet.elapsed_ms} ms"
        with st.expander(f"{packet.source} · {packet.request['method']} · {marker}"):
            left, right = st.columns(2)
            left.markdown("**Request**")
            left.json(packet.request)
            right.markdown("**Response**")
            right.json(packet.response)


def architecture_tab() -> None:
    st.header("Почему это не «лечение с потолка»")
    st.markdown(
        """
1. **Числа считает код**, а не языковая модель: PHQ-9, GAD-7, AUDIT-C, BMI, CKD-EPI, Cockcroft–Gault, QTcF и Child-Pugh.
2. **Каждый источник вызывается через MCP**: приватный `stdio`, локальный `/mcp`, внешний PubMed и OpenFDA.
3. **Поиск не равен рекомендации**: публикации помечаются кандидатами на проверку полного текста.
4. **Медикаментозный вариант появляется только при двойной опоре** — публикации плюс официальная маркировка.
5. **Красные флаги останавливают алгоритм**, дозировки не генерируются, финальное решение остаётся у врача.
        """
    )
    st.code(
        "Case → private stdio scales → local somatic HTTP tools\n"
        "     → de-identified query → PubMed MCP + OpenFDA MCP\n"
        "     → 5 clinical perspectives → citation validator → physician review",
        language=None,
    )
    st.warning("Для учебной демонстрации используйте только синтетический случай. Это не медицинское изделие.")


st.title("PsyConsilium MCP")
st.caption("Проверяемая система поддержки врачебного обсуждения — не автопилот назначения")
tab_case, tab_tools, tab_protocol, tab_arch = st.tabs(["Консилиум", "MCP-инструменты", "JSON-RPC", "Архитектура"])
with tab_case:
    case_tab()
with tab_tools:
    tools_tab()
with tab_protocol:
    protocol_tab()
with tab_arch:
    architecture_tab()
