import pytest

from psy_consilium.clients.sanitize import InputValidationError, sanitize_arguments


SCHEMA = {
    "type": "object",
    "properties": {
        "age": {"type": "integer", "minimum": 18, "maximum": 100},
        "sex": {"type": "string", "enum": ["female", "male"]},
        "limit": {"type": "integer", "default": 5},
    },
    "required": ["age", "sex"],
}


def test_sanitizer_converts_and_uses_only_explicit_defaults() -> None:
    assert sanitize_arguments({"age": "42", "sex": "female"}, SCHEMA) == {
        "age": 42,
        "sex": "female",
        "limit": 5,
    }


def test_sanitizer_rejects_out_of_range_and_unknown_fields() -> None:
    with pytest.raises(InputValidationError):
        sanitize_arguments({"age": 15, "sex": "female"}, SCHEMA)
    with pytest.raises(InputValidationError):
        sanitize_arguments({"age": 42, "sex": "female", "name": "patient"}, SCHEMA)


def test_sanitizer_uses_documented_smart_default_for_known_physiology() -> None:
    schema = {
        "type": "object",
        "properties": {"weight_kg": {"type": "number", "minimum": 25, "maximum": 350}},
        "required": ["weight_kg"],
    }
    assert sanitize_arguments({}, schema) == {"weight_kg": 70.0}
