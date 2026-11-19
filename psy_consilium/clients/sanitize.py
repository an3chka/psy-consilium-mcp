"""Conservative conversion of UI values according to an MCP JSON Schema."""

from __future__ import annotations

import json
from typing import Any


class InputValidationError(ValueError):
    pass


SMART_DEFAULTS: dict[str, Any] = {
    "age": 42,
    "weight_kg": 70.0,
    "height_cm": 170.0,
    "creatinine_umol_l": 80.0,
    "qt_ms": 400.0,
    "heart_rate_bpm": 70.0,
    "bilirubin_mg_dl": 1.0,
    "albumin_g_dl": 4.0,
    "inr": 1.0,
}


def _convert(value: Any, schema: dict[str, Any], field_name: str) -> Any:
    if value is None or value == "":
        return value
    if "enum" in schema and value not in schema["enum"]:
        raise InputValidationError(f"{field_name}: выберите одно из допустимых значений")
    kind = schema.get("type")
    try:
        if kind == "integer":
            converted: Any = int(value)
        elif kind == "number":
            converted = float(value)
        elif kind == "boolean":
            if isinstance(value, bool):
                converted = value
            elif str(value).lower() in {"true", "1", "yes"}:
                converted = True
            elif str(value).lower() in {"false", "0", "no"}:
                converted = False
            else:
                raise ValueError
        elif kind == "array":
            raw_items = json.loads(value) if isinstance(value, str) else value
            if not isinstance(raw_items, list):
                raise ValueError
            converted = [_convert(item, schema.get("items", {}), field_name) for item in raw_items]
        elif kind == "object":
            converted = json.loads(value) if isinstance(value, str) else value
            if not isinstance(converted, dict):
                raise ValueError
        else:
            converted = str(value) if kind == "string" else value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"{field_name}: значение не соответствует типу {kind}") from exc

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and converted < minimum:
        raise InputValidationError(f"{field_name}: минимум {minimum}")
    if maximum is not None and converted > maximum:
        raise InputValidationError(f"{field_name}: максимум {maximum}")
    return converted


def sanitize_arguments(raw: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    unknown = set(raw) - set(properties)
    if unknown and properties:
        raise InputValidationError(f"Неизвестные параметры: {', '.join(sorted(unknown))}")

    clean: dict[str, Any] = {}
    for name, field_schema in properties.items():
        value = raw.get(name)
        if value in (None, ""):
            if "default" in field_schema:
                clean[name] = field_schema["default"]
            elif name in required and name in SMART_DEFAULTS:
                clean[name] = _convert(SMART_DEFAULTS[name], field_schema, name)
            elif name in required:
                raise InputValidationError(f"{name}: обязательное поле")
            continue
        clean[name] = _convert(value, field_schema, name)
    return clean
