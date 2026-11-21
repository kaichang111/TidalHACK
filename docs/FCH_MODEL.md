# Fault Contribution Hierarchy — Mathematical Model

This document defines how the engine (`fch/engine.py`) turns evidence into fault
percentages. Every number in a report can be traced back to a formula here.

> Guiding principle: **fault follows causal contribution, not violation counts.**
> A violation with no causal link to the collision contributes **zero** fault, however
> serious it is.

## 0. Inputs

A case contains:

* **Parties** `i = 1..n` with optional kinematics: speed `v_i`, posted limit `L_i`,
  distance to the conflict point when the hazard first became perceivable `D_i`,
  right-of-way status, visibility, whether evasive action was taken.
* **Actions** `a` attributed to a party (a traffic-code violation such as `RED_LIGHT`,
  or a non-statutory negligent act such as `FAILURE_TO_KEEP_LOOKOUT`). Each action
  carries the evidence IDs that support it and an *evidence confidence* `E_a ∈ [0,1]`
  (probability the action actually happened, given the evidence).
* **Evidence** items with a reliability score, and explicitly recorded **conflicts**
  between evidence items.
* **Scene**: jurisdiction, road surface, lighting, collision type.

Every factor below is either (a) supplied from evidence, (b) derived by the
reconstruction module from evidence, or (c) **unknown**. Unknown factors are never
silently filled in — see §6.

## 1. Level 1 — Causation `C_a ∈ [0,1]`

```
C_a = B_a × M_a
```

* `B_a` — **but-for probability**: P(no collision | action `a` had not occurred).
  * From the reconstruction module when kinematics are available (e.g. speeding: §4.2).
  * From an explicit investigator/extracted value otherwise.
  * From the violation catalog prior **only** when the scene's collision type is one
    the violation characteristically produces (e.g. `RED_LIGHT` + `angle`); otherwise
    `B_a` is *undetermined*.
* `M_a` — **mechanism link**: how directly the action is connected to the physical
  mechanism of this collision (1 = the action *is* the mechanism; 0.3 = indirect).
* If the action **initiated the chain of events**, `B_a ≥ 0.8`.

**Causal threshold.** If `C_a < τ_c` (default 0.15) the action is classified
*non-causal*: it is listed in the report as a violation but contributes no fault.

## 2. Level 2 — Violation Severity `S_a ∈ [0,1]`

Culpability of the departure from the duty of care:

```
S_a = clamp( s_base(code) × g(magnitude) , 0, 1 )
```

`s_base` comes from the violation catalog (`fch/laws.py`). `g` scales by magnitude
where meaningful, e.g. speeding: `g = 0.6 + 0.4·min(1, over_limit_mph / 25)`.
Severity alone never creates fault — it only modulates an action that already passed
the causal threshold.

## 3. Level 3 — Accident Contribution `K_a` and `K^sev_a`

Two separate quantities, so causing the crash is not confused with worsening it:

**Likelihood contribution** (enters fault):

```
K_a = 1 − Π_j (1 − w_j · k_{a,j})
```

over factors `j ∈ {created_danger, reduced_reaction_time, affected_trajectory,
increased_probability}` with weights `w = (1.0, 0.8, 0.7, 0.9)` (noisy-OR: several
weak factors add up, but `K ≤ 1`).

**Severity contribution** (reported separately as *responsibility for severity*):

`K^sev_a` — share of impact energy attributable to the action. For speeding it is
derived physically: `K^sev = 1 − E_impact(legal speed) / E_impact(actual speed)`.

## 4. Level 4 — Avoidability `A_i ∈ [0,1]`

P(driver `i` had a **reasonable** opportunity to avoid the collision).

### 4.1 Kinematic avoidability

```
PRT_i   = 1.5 s  (+0.5 if the driver had right of way — the hazard is unexpected)
               (+0.5 reduced visibility, +1.0 poor visibility / obstructed sightline)
d_stop  = v·PRT + v² / (2 μ g)              μ: dry .70, wet .50, snow .30, ice .15
margin  = (D − d_stop) / v                  seconds of slack
A_i     = σ( (margin − 0.5) / 0.3 )         logistic
```

A driver is only treated as able to avoid if there is real slack after a realistic
perception-reaction time. "Evasive action was theoretically possible" is not enough:
with zero slack, `A ≈ 0.16`; with one second of slack, `A ≈ 0.84`.

If `v` or `D` is missing, `A_i` is **unknown** and no avoidability fault is assigned.

### 4.2 Speeding counterfactual (feeds `B_a`)

```
stop_gain   = max(0, A_i(at limit L) − A_i(at v))
Δt          = D/L − D/v                         later arrival at the legal speed
clear_time  = (vehicle length + lane width) / v_other   (requires the other speed)
timing_gain = min(1, Δt / clear_time)
B_speeding  = 1 − (1 − stop_gain)(1 − timing_gain)
```

### 4.3 Failure to avoid

For each party with `A_i ≥ 0.5` (more likely than not had a reasonable opportunity)
who did **not** take effective evasive action, the engine adds an implicit action
`FAILURE_TO_AVOID` with `B = A_i`, `M = 0.7` (an omission responding to a hazard
someone else created is a less direct link than creating it), `K = 0.7·A_i`, `S = 0.35`. If it is unknown whether
evasive action was taken, `E = 0.5` and the gap is flagged. It is **not** added for a
party whose own action initiated the hazard (that would double-count the same
contribution).

## 5. Level 5 — Shared Responsibility

**Action score** (weighted geometric form — any zero factor zeroes the score):

```
r_a = E_a × C_a^{1.0} × K_a^{0.8} × S_a^{0.5}
```

The exponents encode the hierarchy's priority: causation > contribution > severity.

**No double counting.** Each action belongs to a *mechanism group* (e.g. speeding and
following-too-closely both act through "stopping capacity"). Within a group only the
strongest action counts:

```
G_{i,m} = max_{a ∈ group m} r_a
R_i     = 1 − Π_m (1 − G_{i,m})           (noisy-OR across independent mechanisms)
```

**Normalization.**

```
fault_i = R_i / Σ_j R_j
```

Three distinct outputs are reported, as the spec requires:

| Output | Formula | Meaning |
|---|---|---|
| Estimated fault (legal-style) | `R_i / ΣR` | causation × contribution × culpability |
| Causal contribution | same, with `S ≡ 1` | pure physical/causal share |
| Severity responsibility | `fault_i·(1 − X) + X_i`, `X_i = Σ_a E_a·K^sev_a`, `X = Σ_i X_i` | baseline impact follows fault; excess energy goes to whoever added it |

**Comparative negligence.** The jurisdiction table maps each state to `pure`,
`modified_50`, `modified_51`, or `contributory`, and the report states what each
party could recover under that rule.

## 6. Uncertainty and insufficient evidence

* Each input carries a spread: `0.05 + 0.25·(1 − reliability)` for evidence-backed
  values, `0.25` for catalog priors, and doubled for inputs touched by a recorded
  evidence conflict.
* 1,000 Monte-Carlo draws (fixed seed) produce an 80% interval for each party.
* The engine returns **INSUFFICIENT_EVIDENCE** instead of percentages when:
  1. no action from any party passes the causal threshold with established causation;
  2. any party's 80% interval is wider than 50 percentage points; or
  3. more than half of the causal factors for the top actions are undetermined.

## 7. Calibration

Weights and exponents live in `fch/params.py`. `calibration/calibrate.py` fits them
against labelled cases (CSV of case JSON + adjudicated fault split) by minimizing
mean absolute error with a coarse grid search. **The shipped defaults are expert
priors, not calibrated values** — see the README for datasets to use.
