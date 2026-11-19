import pytest

from psy_consilium import calculators


def test_phq9_total_severity_and_item_nine_warning() -> None:
    result = calculators.phq9([2, 2, 2, 2, 2, 2, 2, 2, 1])
    assert result.value == 17
    assert result.risk_level == "high"
    assert "пункт 9" in result.warnings[0].lower()


def test_gad7_boundaries() -> None:
    assert calculators.gad7([0] * 7).value == 0
    assert calculators.gad7([2] * 7).risk_level == "moderate"
    with pytest.raises(ValueError):
        calculators.gad7([4] * 7)


def test_audit_c_uses_documented_threshold() -> None:
    assert calculators.audit_c([1, 1, 1], "female").risk_level == "moderate"
    assert calculators.audit_c([1, 1, 1], "male").risk_level == "low"


def test_bmi_and_qtc_known_examples() -> None:
    assert calculators.bmi(70, 175).value == 22.9
    assert calculators.qtc_fridericia(400, 60).value == 400


def test_ckd_epi_plausible_and_no_race_input() -> None:
    result = calculators.egfr_ckd_epi_2021(age=40, sex="female", creatinine_umol_l=70)
    assert 85 < result.value < 110
    assert "Расовая-независимая" in result.methodology


def test_child_pugh_components_are_auditable() -> None:
    result = calculators.child_pugh(1.0, 4.0, 1.1, "none", "none")
    assert result.value == 5
    assert result.interpretation.endswith("A")
    assert sum(component.points or 0 for component in result.components) == 5

