"""Accident Assessment Report — assembles the 15 required sections from case + assessment."""
from __future__ import annotations

from .models import Assessment, Case

LEVEL_KEYS = {
    "causation": "Level 1 — Causation",
    "severity": "Level 2 — Violation severity",
    "contribution": "Level 3 — Accident contribution",
    "avoidability": "Level 4 — Avoidability",
    "shared": "Level 5 — Shared responsibility",
}

DISCLAIMER = ("This is an automated, evidence-based estimate produced for analysis and review. "
              "It is not a legal determination or legal advice; a qualified human reviewer must "
              "confirm findings before any reliance.")


def _label(case: Case, pid: str) -> str:
    return next((p.label for p in case.parties if p.id == pid), pid)


def build_report(case: Case, a: Assessment, timeline: list[str] | None = None) -> dict:
    by_party = {p.party_id: p for p in a.parties}
    explicit = [x for x in a.actions if not x.implicit]

    violations = [{
        "party": _label(case, x.party_id), "code": x.code, "title": x.title, "statute": x.statute,
        "evidence_ids": x.evidence_ids, "evidence_confidence": x.evidence_confidence,
        "causal": x.causal,
    } for x in explicit]

    def level_rows(field: str) -> list[dict]:
        return [{"party": _label(case, x.party_id), "action": x.title, "implicit": x.implicit,
                 "value": getattr(x, field).value, "source": getattr(x, field).source,
                 "note": getattr(x, field).note} for x in a.actions]

    avoid = [{"party": p.label, "value": p.avoidability.value, "source": p.avoidability.source,
              "note": p.avoidability.note} for p in a.parties]

    if a.status == "DETERMINED":
        ranked = sorted(a.parties, key=lambda p: -p.fault_pct)
        lead = ranked[0]
        top_actions = [x for x in a.actions if x.party_id == lead.party_id and x.counted]
        why = ", ".join(x.title.lower() for x in top_actions) or "its actions"
        summary = (f"{lead.label} bears the largest share of estimated fault ({lead.fault_pct:.0f}%, 80% interval "
                   f"{lead.fault_interval[0]:.0f}–{lead.fault_interval[1]:.0f}%) because {why} had the strongest "
                   f"established causal connection to the collision. " +
                   " ".join(f"{p.label}: {p.fault_pct:.0f}%." for p in ranked[1:]) +
                   f" Confidence: {a.confidence}.")
        non_causal = [x for x in explicit if x.causal is False]
        if non_causal:
            summary += (" Violations found but not counted as fault because they did not contribute: " +
                        "; ".join(f"{x.title} ({_label(case, x.party_id)})" for x in non_causal) + ".")
    else:
        summary = ("Insufficient evidence to assign fault percentages. " + " ".join(a.status_reasons) +
                   " Resolve the missing information and conflicts listed below, then re-run the assessment.")

    if not timeline:
        timeline = [s.strip() + "." for s in case.description.split(".") if s.strip()]

    return {
        "title": case.title,
        "disclaimer": DISCLAIMER,
        "overview": {
            "description": case.description, "location": case.scene.location, "date": case.scene.date,
            "collision_type": case.scene.collision_type, "road_surface": case.scene.road_surface,
            "lighting": case.scene.lighting, "traffic_control": case.scene.traffic_control,
            "jurisdiction": a.jurisdiction,
        },
        "parties": [p.model_dump() for p in case.parties],
        "timeline": timeline,
        "evidence": [e.model_dump() for e in case.evidence],
        "violations": violations,
        "analysis": {
            "causation": level_rows("causation"),
            "severity": level_rows("severity"),
            "contribution": level_rows("contribution"),
            "severity_contribution": level_rows("severity_contribution"),
            "avoidability": avoid,
            "shared": a.shared_responsibility,
        },
        "actions": [x.model_dump() for x in a.actions],
        "scores": [{"party": p.label, "party_id": p.party_id, "raw_score": p.raw_score,
                    "fault_pct": p.fault_pct, "interval": p.fault_interval,
                    "causal_pct": p.causal_contribution_pct, "severity_pct": p.severity_responsibility_pct,
                    "legal_outcome": p.legal_outcome} for p in a.parties],
        "status": a.status,
        "status_reasons": a.status_reasons,
        "confidence": a.confidence,
        "uncertainties": a.uncertainties,
        "missing_information": a.missing_information,
        "conflicts": a.conflicts,
        "laws": {
            "jurisdiction": a.jurisdiction,
            "statutes": sorted({(x.title, x.statute) for x in explicit}),
        },
        "explanation": {"summary": summary, "steps": a.calculation_steps},
        "levels": LEVEL_KEYS,
        "_party_index": list(by_party),
    }
