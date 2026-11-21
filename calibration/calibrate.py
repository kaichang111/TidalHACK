"""Calibrate FCH parameters against labelled cases (Phase 5 validation).

Input: a directory of case JSON files, each with an extra top-level key
  "adjudicated_fault": {"<party_id>": <percent>, ...}
taken from an independent determination (court verdict, insurer arbitration, etc.).

Run:  python -m calibration.calibrate path/to/labelled_cases
It reports MAE / max error / interval coverage for the current defaults, then
grid-searches the three Level-5 exponents and the causal threshold.
"""
from __future__ import annotations

import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

from fch.engine import assess
from fch.models import Case
from fch.params import DEFAULT_PARAMS, FCHParams


def load(directory: Path) -> list[tuple[Case, dict]]:
    out = []
    for f in sorted(directory.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        label = data.pop("adjudicated_fault", None)
        if label:
            out.append((Case.model_validate(data), label))
    return out


def evaluate(cases, params: FCHParams) -> dict:
    errs, covered, n, insufficient = [], 0, 0, 0
    for case, label in cases:
        a = assess(case, params)
        if a.status != "DETERMINED":
            insufficient += 1
            continue
        for p in a.parties:
            if p.party_id in label:
                truth = label[p.party_id]
                errs.append(abs(p.fault_pct - truth))
                covered += p.fault_interval[0] <= truth <= p.fault_interval[1]
                n += 1
    return {"mae": sum(errs) / len(errs) if errs else float("nan"), "max_err": max(errs, default=float("nan")),
            "coverage_80": covered / n if n else float("nan"), "insufficient": insufficient, "n_parties": n}


def main(path: str) -> None:
    cases = load(Path(path))
    if not cases:
        sys.exit("No labelled cases found (need 'adjudicated_fault' in each JSON).")
    fast = replace(DEFAULT_PARAMS, mc_draws=200)
    print("defaults:", evaluate(cases, DEFAULT_PARAMS))
    best = None
    for ec, ek, es, tau in itertools.product([0.8, 1.0, 1.2], [0.6, 0.8, 1.0], [0.3, 0.5, 0.8], [0.1, 0.15, 0.2]):
        p = replace(fast, exp_causation=ec, exp_contribution=ek, exp_severity=es, causal_threshold=tau)
        m = evaluate(cases, p)
        if best is None or m["mae"] < best[1]["mae"]:
            best = (p, m)
    p, m = best
    print(f"best: exp_causation={p.exp_causation} exp_contribution={p.exp_contribution} "
          f"exp_severity={p.exp_severity} causal_threshold={p.causal_threshold} -> {m}")
    print("Hold out a test split before adopting these values; check fairness across jurisdictions.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "calibration/labelled")
