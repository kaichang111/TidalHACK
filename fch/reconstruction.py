"""Accident Reconstruction: kinematics used by Levels 1, 3 and 4.

All functions return None when the inputs needed are missing, so the engine
never invents values that the evidence does not support.
"""
from __future__ import annotations

import math
from typing import Optional

from .models import Party
from .params import FRICTION, G_FTPS2, MPH_TO_FPS, FCHParams


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def perception_reaction_time(p: Party, params: FCHParams) -> float:
    prt = params.base_prt_s
    if p.had_right_of_way:
        prt += params.prt_unexpected_s  # a right-of-way holder does not expect the violation
    if p.visibility == "reduced":
        prt += params.prt_reduced_visibility_s
    elif p.visibility == "poor":
        prt += params.prt_poor_visibility_s
    return prt


def stopping_distance_ft(speed_mph: float, mu: float, prt_s: float) -> float:
    v = speed_mph * MPH_TO_FPS
    return v * prt_s + v * v / (2 * mu * G_FTPS2)


def avoidability(p: Party, surface: str, params: FCHParams,
                 speed_override: Optional[float] = None) -> Optional[dict]:
    speed = speed_override if speed_override is not None else p.speed_mph
    if not speed or p.distance_to_conflict_ft is None:
        return None
    mu = FRICTION.get(surface, FRICTION["unknown"])
    prt = perception_reaction_time(p, params)
    v = speed * MPH_TO_FPS
    d_stop = stopping_distance_ft(speed, mu, prt)
    margin = (p.distance_to_conflict_ft - d_stop) / v
    a = sigmoid((margin - params.avoid_margin_offset_s) / params.avoid_margin_scale_s)
    return {"A": a, "prt": prt, "mu": mu, "d_stop": d_stop, "margin": margin,
            "time_available": p.distance_to_conflict_ft / v}


def impact_energy_ratio(p: Party, surface: str, params: FCHParams, legal_speed: float) -> Optional[float]:
    """Share of impact kinetic energy attributable to excess speed."""
    if not p.speed_mph or p.distance_to_conflict_ft is None:
        return None
    mu = FRICTION.get(surface, FRICTION["unknown"])
    prt = perception_reaction_time(p, params)

    def impact_v2(speed_mph: float) -> float:
        v = speed_mph * MPH_TO_FPS
        braking = max(0.0, p.distance_to_conflict_ft - v * prt)
        return max(0.0, v * v - 2 * mu * G_FTPS2 * braking)

    e_actual = impact_v2(p.speed_mph)
    if e_actual <= 0:
        return 0.0
    return max(0.0, 1 - impact_v2(legal_speed) / e_actual)


def speeding_counterfactual(p: Party, others: list[Party], surface: str,
                            params: FCHParams) -> Optional[dict]:
    """But-for probability of collision attributable to speeding (docs §4.2)."""
    if not p.speed_mph or not p.speed_limit_mph or p.speed_mph <= p.speed_limit_mph:
        return None
    actual = avoidability(p, surface, params)
    legal = avoidability(p, surface, params, speed_override=p.speed_limit_mph)
    if actual is None or legal is None:
        return None
    stop_gain = max(0.0, legal["A"] - actual["A"])

    timing_gain, timing_note = 0.0, "other vehicle speed unknown — timing effect not evaluated"
    D = p.distance_to_conflict_ft
    dt = D / (p.speed_limit_mph * MPH_TO_FPS) - D / (p.speed_mph * MPH_TO_FPS)
    other_speeds = [o.speed_mph for o in others if o.speed_mph]
    if other_speeds:
        clear_time = (params.vehicle_length_ft + params.lane_width_ft) / (max(other_speeds) * MPH_TO_FPS)
        timing_gain = min(1.0, dt / clear_time)
        timing_note = (f"at the limit, arrival {dt:.2f}s later vs. {clear_time:.2f}s for the other "
                       f"vehicle to clear the lane")
    but_for = 1 - (1 - stop_gain) * (1 - timing_gain)
    return {"but_for": but_for, "stop_gain": stop_gain, "timing_gain": timing_gain,
            "dt": dt, "timing_note": timing_note,
            "severity_share": impact_energy_ratio(p, surface, params, p.speed_limit_mph),
            "A_actual": actual["A"], "A_legal": legal["A"]}
