"""Data model for cases (input) and assessments (output)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Unit = Optional[float]  # value in [0,1], or None = unknown / not established


class Evidence(BaseModel):
    id: str
    kind: Literal["photo", "video", "dashcam", "police_report", "witness",
                  "driver_statement", "telemetry", "diagram", "other"] = "other"
    source: str = ""
    summary: str = ""
    reliability: float = Field(0.7, ge=0, le=1)


class Conflict(BaseModel):
    description: str
    evidence_ids: list[str] = []
    party_ids: list[str] = []


class Party(BaseModel):
    id: str
    label: str
    vehicle: str = ""
    speed_mph: Optional[float] = None
    speed_limit_mph: Optional[float] = None
    distance_to_conflict_ft: Optional[float] = Field(
        None, description="Distance to the conflict point when the hazard first became perceivable")
    had_right_of_way: Optional[bool] = None
    visibility: Literal["good", "reduced", "poor", "unknown"] = "unknown"
    evasive_action_taken: Optional[bool] = None
    notes: str = ""


class CausationInput(BaseModel):
    initiated_chain: Optional[bool] = None
    but_for: Unit = None
    mechanism_link: Unit = None


class ContributionInput(BaseModel):
    created_danger: Unit = None
    reduced_reaction_time: Unit = None
    affected_trajectory: Unit = None
    increased_probability: Unit = None
    increased_severity: Unit = None


class Action(BaseModel):
    id: str
    party_id: str
    code: str = Field(..., description="Violation/negligence code from the catalog, e.g. RED_LIGHT")
    description: str = ""
    evidence_ids: list[str] = []
    evidence_confidence: float = Field(0.8, ge=0, le=1,
                                       description="P(action actually occurred | evidence)")
    magnitude: Optional[float] = Field(None, description="e.g. mph over limit, seconds distracted")
    causation: CausationInput = CausationInput()
    contribution: ContributionInput = ContributionInput()


class Scene(BaseModel):
    jurisdiction: str = "TX"
    location: str = ""
    date: str = ""
    road_surface: Literal["dry", "wet", "snow", "ice", "unknown"] = "unknown"
    lighting: Literal["daylight", "dusk", "dark_lit", "dark_unlit", "unknown"] = "unknown"
    collision_type: Literal["angle", "rear_end", "head_on", "sideswipe",
                            "left_turn", "single_vehicle", "pedestrian", "unknown"] = "unknown"
    traffic_control: str = ""


class Case(BaseModel):
    id: str = "case"
    title: str = "Untitled accident"
    description: str = ""
    scene: Scene = Scene()
    parties: list[Party]
    actions: list[Action] = []
    evidence: list[Evidence] = []
    conflicts: list[Conflict] = []


# ---------------------------------------------------------------- outputs

class FactorTrace(BaseModel):
    value: Optional[float]
    source: Literal["evidence", "reconstruction", "catalog_prior", "derived", "undetermined"]
    note: str = ""


class ActionAssessment(BaseModel):
    action_id: str
    party_id: str
    code: str
    title: str
    statute: str = ""
    implicit: bool = False
    evidence_ids: list[str] = []
    evidence_confidence: float
    causation: FactorTrace
    severity: FactorTrace
    contribution: FactorTrace
    severity_contribution: FactorTrace
    mechanism_group: str
    causal: Optional[bool]
    score: float
    counted: bool
    explanation: list[str] = []


class PartyAssessment(BaseModel):
    party_id: str
    label: str
    raw_score: float
    fault_pct: float
    fault_interval: tuple[float, float]
    causal_contribution_pct: float
    severity_responsibility_pct: float
    avoidability: FactorTrace
    legal_outcome: str = ""


class Assessment(BaseModel):
    case_id: str
    status: Literal["DETERMINED", "INSUFFICIENT_EVIDENCE"]
    status_reasons: list[str] = []
    confidence: Literal["high", "moderate", "low"]
    parties: list[PartyAssessment]
    actions: list[ActionAssessment]
    shared_responsibility: list[str] = []
    uncertainties: list[str] = []
    missing_information: list[str] = []
    conflicts: list[str] = []
    jurisdiction: dict = {}
    calculation_steps: list[str] = []
