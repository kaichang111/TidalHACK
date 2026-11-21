import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from fch import Case, assess
from fch.models import Action, CausationInput, Party, Scene

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def load(name: str) -> Case:
    return Case.model_validate(json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8")))


def by_id(a, pid):
    return next(p for p in a.parties if p.party_id == pid)


def test_spec_example_red_light_dominates_speeding():
    a = assess(load("red_light_speeding"))
    assert a.status == "DETERMINED"
    A, B = by_id(a, "A"), by_id(a, "B")
    assert A.fault_pct > 60 and 10 < B.fault_pct < 40
    assert abs(A.fault_pct + B.fault_pct - 100) < 0.2
    # speeding made the impact worse: B carries most severity responsibility
    assert B.severity_responsibility_pct > B.fault_pct
    # Texas modified comparative negligence (51% bar)
    assert "Barred" in A.legal_outcome and "May recover" in B.legal_outcome


def test_non_causal_violation_adds_no_fault():
    a = assess(load("rear_end_distracted"))
    reg = next(x for x in a.actions if x.code == "NO_LICENSE_INSURANCE")
    assert reg.causal is False and reg.score == 0
    assert by_id(a, "A").fault_pct == 0


def test_same_mechanism_not_double_counted():
    case = load("rear_end_distracted")
    base = assess(case).parties
    # add a second stopping-capacity action: must not increase party B's raw score
    case.actions.append(Action(id="b3", party_id="B", code="UNSAFE_SPEED_FOR_CONDITIONS",
                               evidence_ids=["e2"], evidence_confidence=0.5))
    after = assess(case)
    assert after.parties[1].raw_score == pytest.approx(base[1].raw_score, abs=1e-9)
    merged = next(x for x in after.actions if x.action_id == "b3")
    assert merged.score > 0 and merged.counted is False


def test_avoidable_right_of_way_holder_shares_fault():
    a = assess(load("left_turn_avoidable"))
    assert a.status == "DETERMINED"
    assert any(x.implicit and x.code == "FAILURE_TO_AVOID" for x in a.actions)
    assert 15 < by_id(a, "B").fault_pct < 40
    # North Carolina contributory negligence bars both
    assert all("barred" in p.legal_outcome.lower() for p in a.parties)


def test_no_failure_to_avoid_without_reasonable_opportunity():
    a = assess(load("red_light_speeding"))
    assert not any(x.implicit for x in a.actions)


def test_conflicting_accounts_insufficient():
    a = assess(load("conflicting_accounts"))
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.conflicts


def test_missing_evidence_not_replaced_by_assumptions():
    case = Case(scene=Scene(collision_type="unknown"),
                parties=[Party(id="A", label="A"), Party(id="B", label="B")],
                actions=[Action(id="a", party_id="A", code="SPEEDING", evidence_confidence=0.9)])
    a = assess(case)
    assert a.status == "INSUFFICIENT_EVIDENCE"
    assert a.actions[0].causal is None
    assert a.missing_information


def test_initiated_chain_sets_causation_floor():
    case = Case(scene=Scene(collision_type="unknown"),
                parties=[Party(id="A", label="A"), Party(id="B", label="B")],
                actions=[Action(id="a", party_id="A", code="IMPROPER_TURN", evidence_ids=[],
                                evidence_confidence=0.9, causation=CausationInput(initiated_chain=True,
                                                                                  mechanism_link=1.0))])
    a = assess(case)
    assert a.actions[0].causation.value >= 0.8
    assert by_id(a, "A").fault_pct == 100


def test_deterministic():
    c = load("red_light_speeding")
    assert assess(c).model_dump() == assess(c).model_dump()


def test_api_assess_and_samples():
    client = TestClient(app)
    samples = client.get("/api/samples").json()
    assert len(samples) >= 4
    r = client.post("/api/assess", json={"case": samples[0]["case"]})
    assert r.status_code == 200
    rep = r.json()["report"]
    for key in ("overview", "parties", "timeline", "evidence", "violations", "analysis", "scores",
                "confidence", "laws", "explanation"):
        assert key in rep
    bad = dict(samples[0]["case"])
    bad["actions"] = [dict(bad["actions"][0], party_id="ZZZ")] if bad["actions"] else []
    if bad["actions"]:
        assert client.post("/api/assess", json={"case": bad}).status_code == 422
