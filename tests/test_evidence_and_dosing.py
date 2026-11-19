from psy_consilium.dosing import parse_dose_review
from psy_consilium.evidence import assess_article, candidate_specs
from psy_consilium.models import PatientCase


def _case(**overrides):
    values = {
        "age": 34,
        "sex": "female",
        "condition": "major depressive disorder",
        "candidate_medication": "sertraline",
        "phq9_items": [1] * 9,
        "gad7_items": [1] * 7,
        "auditc_items": [0] * 3,
    }
    values.update(overrides)
    return PatientCase(**values)


def test_article_is_rejected_when_intervention_does_not_match() -> None:
    case = _case()
    medication = candidate_specs(case, "Сертралин")[1]
    unrelated = {
        "pmid": "123",
        "title": "Exercise for major depressive disorder in adults",
        "abstractText": "A randomized trial of exercise in adults with depression.",
        "publicationTypes": ["Randomized Controlled Trial"],
        "meshTerms": [{"descriptorName": "Humans"}, {"descriptorName": "Adult"}],
    }
    assert assess_article(unrelated, case, medication) is None


def test_article_result_fragment_is_copied_from_abstract() -> None:
    case = _case()
    medication = candidate_specs(case, "Сертралин")[1]
    sentence = "Sertraline significantly improved symptoms in adult participants."
    article = {
        "pmid": "456",
        "title": "Sertraline for major depressive disorder",
        "abstractText": f"Background text. {sentence} Conclusions: further study is required.",
        "publicationTypes": ["Randomized Controlled Trial"],
        "meshTerms": [{"descriptorName": "Humans"}, {"descriptorName": "Adult"}],
        "journalInfo": {"publicationDate": {"year": 2024}},
    }
    accepted = assess_article(article, case, medication)
    assert accepted is not None
    assert accepted["result_fragments"] == [sentence]


def test_dose_above_detected_label_maximum_is_flagged() -> None:
    case = _case(planned_dose_mg=250, creatinine_umol_l=70, qt_ms=400, heart_rate_bpm=70)
    raw = {
        "structuredContent": {
            "results": [
                {
                    "set_id": "label-1",
                    "dosage_and_administration": [
                        "The recommended initial dosage is 50 mg per day. The maximum dosage is 200 mg per day. "
                        "Increase at weekly intervals."
                    ],
                }
            ]
        }
    }
    review = parse_dose_review(raw, case, "Сертралин")
    assert review.detected_maximum_mg_per_day == 200
    assert review.status == "above_label_maximum"
    assert review.label_id == "OPENFDA:label-1"
