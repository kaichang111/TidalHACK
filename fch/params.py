"""Tunable parameters of the Fault Contribution Hierarchy model.

These are expert priors, NOT calibrated values. Use calibration/calibrate.py
against labelled cases to fit them. See docs/FCH_MODEL.md for the formulas.
"""
from dataclasses import dataclass, field


@dataclass
class FCHParams:
    # Level 1
    causal_threshold: float = 0.15
    initiated_chain_floor: float = 0.8

    # Level 3 noisy-OR weights for likelihood contribution factors
    contribution_weights: dict = field(default_factory=lambda: {
        "created_danger": 1.0,
        "reduced_reaction_time": 0.8,
        "affected_trajectory": 0.7,
        "increased_probability": 0.9,
    })

    # Level 5 exponents: causation > contribution > severity
    exp_causation: float = 1.0
    exp_contribution: float = 0.8
    exp_severity: float = 0.5

    # Level 4 kinematics
    base_prt_s: float = 1.5
    prt_unexpected_s: float = 0.5
    prt_reduced_visibility_s: float = 0.5
    prt_poor_visibility_s: float = 1.0
    avoid_margin_offset_s: float = 0.5
    avoid_margin_scale_s: float = 0.3
    failure_to_avoid_severity: float = 0.35
    failure_to_avoid_link: float = 0.7  # mechanism link of an omission vs. creating the hazard
    vehicle_length_ft: float = 16.0
    lane_width_ft: float = 12.0

    # Uncertainty
    mc_draws: int = 1000
    mc_seed: int = 7
    prior_spread: float = 0.25
    max_interval_width_pts: float = 50.0
    max_undetermined_share: float = 0.5


FRICTION = {"dry": 0.70, "wet": 0.50, "snow": 0.30, "ice": 0.15, "unknown": 0.60}
G_FTPS2 = 32.2
MPH_TO_FPS = 1.46667

DEFAULT_PARAMS = FCHParams()
