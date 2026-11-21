"""Traffic Law Engine: violation catalog + jurisdiction rules.

Statute references are provided for orientation only and must be verified
against current law before any real-world use. This is not legal advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Violation:
    code: str
    title: str
    base_severity: float
    mechanism_group: str
    initiates_hazard: bool  # typically creates the hazard (vs. reduces ability to respond)
    typical_collisions: tuple[str, ...]
    prior: dict  # catalog priors used only when collision type matches
    statutes: dict = field(default_factory=dict)  # jurisdiction -> citation


CATALOG: dict[str, Violation] = {v.code: v for v in [
    Violation(
        "RED_LIGHT", "Running a red light", 0.90, "right_of_way", True,
        ("angle", "left_turn", "pedestrian"),
        {"but_for": 0.95, "mechanism_link": 1.0, "created_danger": 1.0,
         "increased_probability": 0.9, "affected_trajectory": 0.6},
        {"TX": "Tex. Transp. Code §544.007", "CA": "Cal. Veh. Code §21453"}),
    Violation(
        "STOP_SIGN", "Failing to stop at a stop sign", 0.80, "right_of_way", True,
        ("angle", "left_turn", "pedestrian"),
        {"but_for": 0.9, "mechanism_link": 1.0, "created_danger": 1.0,
         "increased_probability": 0.85, "affected_trajectory": 0.5},
        {"TX": "Tex. Transp. Code §544.010", "CA": "Cal. Veh. Code §22450"}),
    Violation(
        "FAILURE_TO_YIELD", "Failure to yield right of way", 0.75, "right_of_way", True,
        ("angle", "left_turn", "sideswipe", "pedestrian"),
        {"but_for": 0.9, "mechanism_link": 1.0, "created_danger": 0.95,
         "increased_probability": 0.85, "affected_trajectory": 0.6},
        {"TX": "Tex. Transp. Code §545.153", "CA": "Cal. Veh. Code §21800"}),
    Violation(
        "IMPROPER_LEFT_TURN", "Unsafe left turn across traffic", 0.75, "right_of_way", True,
        ("left_turn", "angle"),
        {"but_for": 0.9, "mechanism_link": 1.0, "created_danger": 0.95,
         "increased_probability": 0.85, "affected_trajectory": 0.8},
        {"TX": "Tex. Transp. Code §545.152", "CA": "Cal. Veh. Code §21801"}),
    Violation(
        "IMPROPER_TURN", "Improper turn", 0.55, "trajectory", True,
        ("angle", "sideswipe", "left_turn"),
        {"but_for": 0.7, "mechanism_link": 0.8, "created_danger": 0.7,
         "increased_probability": 0.6, "affected_trajectory": 0.9},
        {"TX": "Tex. Transp. Code §545.101", "CA": "Cal. Veh. Code §22100"}),
    Violation(
        "UNSAFE_LANE_CHANGE", "Unsafe lane change", 0.65, "trajectory", True,
        ("sideswipe", "rear_end", "angle"),
        {"but_for": 0.9, "mechanism_link": 1.0, "created_danger": 0.9,
         "increased_probability": 0.8, "affected_trajectory": 0.9},
        {"TX": "Tex. Transp. Code §545.060", "CA": "Cal. Veh. Code §21658"}),
    Violation(
        "WRONG_WAY", "Driving against traffic / wrong side", 0.95, "trajectory", True,
        ("head_on", "sideswipe"),
        {"but_for": 0.95, "mechanism_link": 1.0, "created_danger": 1.0,
         "increased_probability": 0.95, "affected_trajectory": 1.0},
        {"TX": "Tex. Transp. Code §545.051", "CA": "Cal. Veh. Code §21650"}),
    Violation(
        "SPEEDING", "Speeding", 0.55, "stopping_capacity", False,
        ("rear_end", "single_vehicle"),
        {"but_for": 0.5, "mechanism_link": 0.7, "reduced_reaction_time": 0.6,
         "increased_probability": 0.4},
        {"TX": "Tex. Transp. Code §545.351", "CA": "Cal. Veh. Code §22350"}),
    Violation(
        "FOLLOWING_TOO_CLOSELY", "Following too closely", 0.60, "stopping_capacity", False,
        ("rear_end",),
        {"but_for": 0.85, "mechanism_link": 1.0, "reduced_reaction_time": 0.9,
         "increased_probability": 0.8},
        {"TX": "Tex. Transp. Code §545.062", "CA": "Cal. Veh. Code §21703"}),
    Violation(
        "DISTRACTED", "Distracted driving / device use", 0.70, "attention", False,
        ("rear_end", "angle", "single_vehicle", "pedestrian", "sideswipe", "left_turn"),
        {"but_for": 0.6, "mechanism_link": 0.8, "reduced_reaction_time": 0.9,
         "increased_probability": 0.6},
        {"TX": "Tex. Transp. Code §545.4251", "CA": "Cal. Veh. Code §23123.5"}),
    Violation(
        "FAILURE_TO_KEEP_LOOKOUT", "Failure to keep a proper lookout", 0.40, "attention", False,
        ("rear_end", "angle", "pedestrian", "left_turn"),
        {"but_for": 0.5, "mechanism_link": 0.7, "reduced_reaction_time": 0.7,
         "increased_probability": 0.5},
        {}),
    Violation(
        "UNSAFE_SPEED_FOR_CONDITIONS", "Speed unsafe for conditions", 0.55, "stopping_capacity", False,
        ("rear_end", "single_vehicle", "angle"),
        {"but_for": 0.5, "mechanism_link": 0.7, "reduced_reaction_time": 0.6,
         "increased_probability": 0.5},
        {"TX": "Tex. Transp. Code §545.351(b)", "CA": "Cal. Veh. Code §22350"}),
    Violation(
        "IMPAIRED", "Driving while impaired", 0.95, "attention", False,
        ("rear_end", "angle", "head_on", "single_vehicle", "sideswipe", "pedestrian", "left_turn"),
        {"but_for": 0.6, "mechanism_link": 0.7, "reduced_reaction_time": 0.9,
         "increased_probability": 0.7},
        {"TX": "Tex. Penal Code §49.04", "CA": "Cal. Veh. Code §23152"}),
    Violation(
        "EQUIPMENT", "Defective equipment (e.g. lights, brakes)", 0.35, "vehicle_condition", False,
        (),
        {"but_for": 0.4, "mechanism_link": 0.5, "increased_probability": 0.4},
        {}),
    Violation(
        "NO_LICENSE_INSURANCE", "Unlicensed / uninsured", 0.30, "status", False,
        (),  # status offenses are almost never causal
        {"but_for": 0.0, "mechanism_link": 0.0},
        {}),
    Violation(
        "FAILURE_TO_AVOID", "Failure to take reasonable evasive action", 0.35, "avoidance", False,
        (), {}, {}),
]}


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    rule: str  # pure | modified_50 | modified_51 | contributory
    authority: str


JURISDICTIONS: dict[str, Jurisdiction] = {j.code: j for j in [
    Jurisdiction("TX", "Texas", "modified_51", "Tex. Civ. Prac. & Rem. Code ch. 33 (proportionate responsibility)"),
    Jurisdiction("CA", "California", "pure", "Li v. Yellow Cab Co., 13 Cal.3d 804 (1975)"),
    Jurisdiction("NY", "New York", "pure", "N.Y. CPLR §1411"),
    Jurisdiction("WA", "Washington", "pure", "RCW 4.22.005"),
    Jurisdiction("FL", "Florida", "modified_51", "Fla. Stat. §768.81 (as amended 2023)"),
    Jurisdiction("IL", "Illinois", "modified_51", "735 ILCS 5/2-1116"),
    Jurisdiction("GA", "Georgia", "modified_50", "O.C.G.A. §51-12-33"),
    Jurisdiction("NC", "North Carolina", "contributory", "Common-law contributory negligence"),
    Jurisdiction("VA", "Virginia", "contributory", "Common-law contributory negligence"),
    Jurisdiction("MD", "Maryland", "contributory", "Common-law contributory negligence"),
    Jurisdiction("AL", "Alabama", "contributory", "Common-law contributory negligence"),
    Jurisdiction("DC", "District of Columbia", "contributory", "Common-law contributory negligence"),
    Jurisdiction("GENERIC", "Generic (modified comparative, 51% bar)", "modified_51",
                 "Illustrative default; select a specific jurisdiction"),
]}

RULE_TEXT = {
    "pure": "Pure comparative negligence: each party's recovery is reduced by its own share of fault, at any level.",
    "modified_50": "Modified comparative negligence (50% bar): a party 50% or more at fault recovers nothing; otherwise recovery is reduced by its share.",
    "modified_51": "Modified comparative negligence (51% bar): a party more than 50% at fault recovers nothing; otherwise recovery is reduced by its share.",
    "contributory": "Contributory negligence: a party found even slightly at fault is generally barred from recovery (subject to doctrines such as last clear chance).",
}


def get_violation(code: str) -> Violation:
    return CATALOG.get(code.upper()) or Violation(
        code.upper(), code.replace("_", " ").title(), 0.5, f"custom_{code.lower()}", False, (), {}, {})


def get_jurisdiction(code: str) -> Jurisdiction:
    return JURISDICTIONS.get((code or "").upper(), JURISDICTIONS["GENERIC"])


def statute_for(v: Violation, jurisdiction: str) -> str:
    if jurisdiction in v.statutes:
        return v.statutes[jurisdiction]
    if v.statutes:
        return "Uniform Vehicle Code equivalent — verify local statute"
    return "Common-law duty of reasonable care"


def legal_outcome(rule: str, fault_pct: float) -> str:
    f = round(fault_pct, 1)
    if rule == "pure":
        return f"May recover {100 - f:.1f}% of own damages from others."
    if rule == "modified_50":
        return "Barred from recovery (≥50% at fault)." if f >= 50 else f"May recover {100 - f:.1f}% of own damages."
    if rule == "modified_51":
        return "Barred from recovery (>50% at fault)." if f > 50 else f"May recover {100 - f:.1f}% of own damages."
    if rule == "contributory":
        return "Likely barred from recovery (any contributory fault)." if f >= 1 else "Not barred — no contributory fault found."
    return ""
