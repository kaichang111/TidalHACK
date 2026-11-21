# FCH: Accident Fault Determination

Estimates each driver's share of responsibility for a vehicle accident using a
five-level **Fault Contribution Hierarchy** (causation, violation severity, accident
contribution, avoidability, shared responsibility).

> **Core principle:** fault follows *causal contribution*, not violation counts. A
> violation that didn't cause the crash adds zero fault. Missing evidence is never
> filled in with assumptions. When the evidence can't support a split, the system
> returns *insufficient evidence* instead of a percentage.

## How it works

```
 photos / dashcam / reports ──► Fact extraction   ──► Case facts ──► Human review ──► FCH engine ──► Report
                                (NLP + vision;        (structured,    (edit/confirm     (deterministic,
                                 facts only, cites     evidence-cited)  every fact)       explainable math)
                                 evidence IDs)
```

| Component | Where | What it does |
|---|---|---|
| Computer vision + NLP | `fch/extraction.py` | The extraction service reads police reports, witness/driver statements, photos and sampled dashcam frames, then returns structured facts with evidence citations and flags conflicts. It never assigns fault. |
| Accident reconstruction | `fch/reconstruction.py` | Stopping distance, perception-reaction time, avoidability margins, speeding counterfactuals, impact-energy share. |
| Traffic law engine | `fch/laws.py` | Violation catalog (severity, causal mechanism, statutes for TX/CA) and comparative-negligence rules for 12 jurisdictions. |
| Fault Contribution Engine | `fch/engine.py` | Applies the five levels, de-duplicates shared mechanisms, normalizes to percentages, and runs Monte-Carlo uncertainty. |
| Explainable report | `fch/report.py`, `web/` | A 15-section report with a fault-distribution chart, per-action reasoning traces, and lists of uncertainty, missing information and conflicts. |

The full math is in [docs/FCH_MODEL.md](docs/FCH_MODEL.md).

Each report gives three distinct outputs, as the spec requires:

- **Estimated fault**: causation × contribution × culpability.
- **Causal contribution**: pure physical cause, ignoring culpability.
- **Severity responsibility**: who made the outcome worse.

## Run it

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

Automatic fact extraction from raw evidence also needs a `.env` file in the project folder (it is git-ignored):

```
ANTHROPIC_API_KEY=<your API key>
FCH_MODEL=<model id>
```

Open http://localhost:8000. The four sample cases and manual entry work without an API key.

```powershell
python -m pytest -q
```

## Sample cases (`samples/`)

| Case | Result | Shows |
|---|---|---|
| Red light vs. speeding (TX) | A 70% / B 30% | The spec's example. B's speeding is causal because at the legal speed B would have arrived 0.7 s later. B carries most of the *severity* responsibility. |
| Rear-end, tailgating + phone (CA) | B 100% | A's expired registration is recorded but non-causal (0 fault). Tailgating and distraction are scored separately (different mechanisms). |
| Left turn, inattentive oncoming driver (NC) | A 71% / B 29% | Level 4: B had 1.9 s of slack and never braked. Under contributory negligence, both are barred from recovery. |
| Disputed signal, no objective evidence (FL) | Insufficient evidence | Conflicting statements give an 80% interval wider than 50 points, so no split is forced. |

## Status and honest limitations

- **Phases 1–4 (foundation, intelligence, integration, application):** implemented as a working MVP.
- **Calibration:** the weights in `fch/params.py` are expert priors, not fitted values.
  `calibration/calibrate.py` fits them against labelled cases (case JSON with an
  `adjudicated_fault` field). Candidate data sources:
  - NHTSA CRSS, FARS and CISS (crash circumstances and violations)
  - Dashcam crash datasets (CCD, DoTA) to validate the vision stage
  - Court verdicts or insurer arbitration outcomes for the fault labels
- **Phase 5 (validation):** the test harness exists, but no real-world accuracy has been measured yet.
- **Statutes:** citations exist for TX and CA only; other states fall back to a generic note. All citations must be verified against current law.
- **Video:** dashcam video is sampled at 6 frames. Speeds are not yet measured from video (that needs camera calibration), so speed and distance must come from telemetry, reports or reviewer input.
- **Not legal advice:** output is decision support for a qualified human reviewer.
