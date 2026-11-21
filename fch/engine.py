"""Fault Contribution Engine — applies the five-level hierarchy (docs/FCH_MODEL.md)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from .laws import RULE_TEXT, get_jurisdiction, get_violation, legal_outcome, statute_for
from .models import (Action, ActionAssessment, Assessment, Case, FactorTrace, Party,
                     PartyAssessment)
from .params import DEFAULT_PARAMS, FCHParams
from .reconstruction import avoidability, speeding_counterfactual

K_FACTORS = ("created_danger", "reduced_reaction_time", "affected_trajectory", "increased_probability")


@dataclass
class Factor:
    value: Optional[float]
    source: str = "undetermined"
    spread: float = 0.0
    note: str = ""

    def draw(self, rng: Optional[random.Random]) -> Optional[float]:
        if self.value is None:
            return None
        if rng is None or self.spread <= 0:
            return self.value
        return min(1.0, max(0.0, rng.gauss(self.value, self.spread)))

    def trace(self) -> FactorTrace:
        return FactorTrace(value=None if self.value is None else round(self.value, 3),
                           source=self.source if self.source in
                           ("evidence", "reconstruction", "catalog_prior", "derived") else "undetermined",
                           note=self.note)


@dataclass
class Resolved:
    action: Action
    title: str
    statute: str
    group: str
    initiates_hazard: bool
    implicit: bool
    E: Factor
    B: Factor
    M: Factor
    S: Factor
    K: dict[str, Factor]
    Ksev: Factor
    notes: list[str] = field(default_factory=list)


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


class Engine:
    def __init__(self, case: Case, params: FCHParams = DEFAULT_PARAMS):
        self.case = case
        self.p = params
        self.ev = {e.id: e for e in case.evidence}
        self.conflicted = {eid for c in case.conflicts for eid in c.evidence_ids}
        self.conflicted_parties = {pid for c in case.conflicts for pid in c.party_ids}
        self.parties = {p.id: p for p in case.parties}
        self.missing: list[str] = []
        self.uncertain: list[str] = []
        self.avoid: dict[str, Optional[dict]] = {}
        self.resolved: list[Resolved] = []

    # ------------------------------------------------------------ resolution
    def _evidence_spread(self, a: Action) -> tuple[float, float, bool]:
        rels = [self.ev[e].reliability for e in a.evidence_ids if e in self.ev]
        rel = mean(rels) if rels else 0.5
        conflicted = any(e in self.conflicted for e in a.evidence_ids) or a.party_id in self.conflicted_parties
        spread = 0.05 + 0.25 * (1 - rel)
        return rel, spread * (2 if conflicted else 1), conflicted

    def _resolve_action(self, a: Action) -> Resolved:
        v = get_violation(a.code)
        scene = self.case.scene
        party = self.parties.get(a.party_id)
        others = [p for p in self.case.parties if p.id != a.party_id]
        rel, spread, conflicted = self._evidence_spread(a)
        notes: list[str] = []
        if not a.evidence_ids:
            notes.append("No evidence item is cited for this action.")
            self.missing.append(f"{a.code} by {self._label(a.party_id)}: no supporting evidence cited.")
        if conflicted:
            notes.append("Supporting evidence is subject to a recorded conflict — uncertainty doubled.")

        E = Factor(a.evidence_confidence, "evidence", spread,
                   f"mean evidence reliability {rel:.2f}")
        match = scene.collision_type in v.typical_collisions
        # status offenses (no typical collision mechanism, zero but-for prior) are non-causal by nature
        status_offense = not v.typical_collisions and v.prior.get("but_for") == 0.0
        prior = v.prior if (match or status_offense) else {}

        def pick(name: str, provided: Optional[float]) -> Factor:
            if provided is not None:
                return Factor(provided, "evidence", spread, "from evidence / investigator input")
            if name in prior:
                return Factor(prior[name], "catalog_prior", self.p.prior_spread,
                              f"catalog prior: {v.title.lower()} is a characteristic cause of "
                              f"{scene.collision_type.replace('_', ' ')} collisions")
            return Factor(None)

        B = pick("but_for", a.causation.but_for)
        M = pick("mechanism_link", a.causation.mechanism_link)
        K = {k: pick(k, getattr(a.contribution, k)) for k in K_FACTORS}
        Ksev = Factor(a.contribution.increased_severity, "evidence", spread) \
            if a.contribution.increased_severity is not None else Factor(None)

        magnitude = a.magnitude
        if v.code in ("SPEEDING", "UNSAFE_SPEED_FOR_CONDITIONS") and party:
            if magnitude is None and party.speed_mph and party.speed_limit_mph:
                magnitude = max(0.0, party.speed_mph - party.speed_limit_mph)
            if v.code == "SPEEDING" and a.causation.but_for is None and party:
                cf = speeding_counterfactual(party, others, scene.road_surface, self.p)
                if cf:
                    B = Factor(cf["but_for"], "reconstruction", 0.12,
                               f"stopping gain {cf['stop_gain']:.2f}; timing gain {cf['timing_gain']:.2f} "
                               f"({cf['timing_note']})")
                    if a.causation.mechanism_link is None:
                        M = Factor(1.0, "derived", 0.05, "speed directly governs the vehicle's arrival and stopping")
                    if a.contribution.increased_probability is None:
                        K["increased_probability"] = Factor(cf["but_for"], "reconstruction", 0.12)
                    if a.contribution.reduced_reaction_time is None:
                        prt = avoidability(party, scene.road_surface, self.p)["prt"]
                        K["reduced_reaction_time"] = Factor(_clamp(cf["dt"] / prt), "reconstruction", 0.1,
                                                            f"{cf['dt']:.2f}s of {prt:.1f}s reaction time lost")
                    if Ksev.value is None and cf["severity_share"] is not None:
                        Ksev = Factor(cf["severity_share"], "reconstruction", 0.1,
                                      "share of impact energy due to excess speed")
                else:
                    self.missing.append(
                        f"Speeding by {party.label}: speed, limit or distance-to-conflict missing — "
                        "speed-based reconstruction not possible.")

        if a.causation.initiated_chain:
            if B.value is None or B.value < self.p.initiated_chain_floor:
                B = Factor(self.p.initiated_chain_floor if B.value is None else max(B.value, self.p.initiated_chain_floor),
                           "evidence", spread, "action initiated the chain of events")

        # increased probability of collision is, by definition, bounded by the but-for probability
        if all(f.value is None for f in K.values()) and B.value is not None:
            K["increased_probability"] = Factor(B.value, "derived", B.spread or self.p.prior_spread,
                                                "set equal to the but-for probability")

        g = 1.0
        if v.code in ("SPEEDING", "UNSAFE_SPEED_FOR_CONDITIONS") and magnitude is not None:
            g = 0.6 + 0.4 * min(1.0, magnitude / 25.0)
        elif magnitude is not None and v.code == "DISTRACTED":
            g = 0.7 + 0.3 * min(1.0, magnitude / 4.0)  # seconds eyes-off-road
        S = Factor(_clamp(v.base_severity * g), "derived", 0.05,
                   f"base severity {v.base_severity:.2f} × magnitude factor {g:.2f}")

        if B.value is None:
            self.uncertain.append(f"Causation of '{v.title}' by {self._label(a.party_id)} is undetermined "
                                  "on the available evidence.")
        return Resolved(a, v.title, statute_for(v, get_jurisdiction(scene.jurisdiction).code),
                        v.mechanism_group, v.initiates_hazard, False, E, B, M, S, K, Ksev, notes)

    def _label(self, pid: str) -> str:
        p = self.parties.get(pid)
        return p.label if p else pid

    def _resolve(self) -> None:
        self.resolved = [self._resolve_action(a) for a in self.case.actions]
        scene = self.case.scene
        for party in self.case.parties:
            av = avoidability(party, scene.road_surface, self.p)
            self.avoid[party.id] = av
            if av is None:
                self.missing.append(f"{party.label}: speed or distance-to-conflict unknown — "
                                    "avoidability (Level 4) not evaluated.")
                continue
            initiator = any(r.action.party_id == party.id and r.initiates_hazard and
                            (r.B.value or 0) * (r.M.value or 0) >= 0.5 for r in self.resolved)
            if initiator or party.evasive_action_taken or av["A"] < 0.5:
                continue
            E_val, note = (1.0, "no evasive action recorded") if party.evasive_action_taken is False \
                else (0.5, "whether evasive action was taken is unknown")
            if party.evasive_action_taken is None:
                self.uncertain.append(f"{party.label}: unknown whether evasive action was taken.")
            act = Action(id=f"implicit-avoid-{party.id}", party_id=party.id, code="FAILURE_TO_AVOID",
                         description=f"Had {av['margin']:.1f}s of slack after a {av['prt']:.1f}s "
                                     "perception-reaction time but did not avoid the collision.",
                         evidence_confidence=E_val)
            A = Factor(av["A"], "reconstruction", 0.1, f"avoidability {av['A']:.2f}")
            link = self.p.failure_to_avoid_link
            self.resolved.append(Resolved(
                act, "Failure to take reasonable evasive action", "Common-law duty of reasonable care",
                "avoidance", False, True, Factor(E_val, "evidence", 0.1, note), A,
                Factor(link, "derived", 0.05, "omission responding to a hazard created by another party"),
                Factor(self.p.failure_to_avoid_severity, "derived", 0.05, "duty of lookout / evasive action"),
                {"increased_probability": Factor(av["A"] * link, "reconstruction", 0.1)}, Factor(None), []))

    # ------------------------------------------------------------ computation
    def _noisy_or_k(self, K: dict[str, Factor], rng) -> Optional[float]:
        vals = [(k, f.draw(rng)) for k, f in K.items()]
        vals = [(k, x) for k, x in vals if x is not None]
        if not vals:
            return None
        prod = 1.0
        for k, x in vals:
            prod *= 1 - self.p.contribution_weights.get(k, 0.8) * x
        return 1 - prod

    def _compute(self, rng: Optional[random.Random] = None) -> dict:
        p = self.p
        rows = []
        for r in self.resolved:
            E, B, M, S = r.E.draw(rng), r.B.draw(rng), r.M.draw(rng), r.S.draw(rng)
            C = None if B is None or M is None else B * M
            K = self._noisy_or_k(r.K, rng)
            causal = None if C is None else C >= p.causal_threshold
            if causal and K is not None:
                score = E * C ** p.exp_causation * K ** p.exp_contribution * S ** p.exp_severity
                cscore = E * C ** p.exp_causation * K ** p.exp_contribution
            else:
                score = cscore = 0.0
            ksev = r.Ksev.draw(rng)
            rows.append({"r": r, "E": E, "C": C, "K": K, "S": S, "causal": causal,
                         "score": score, "cscore": cscore, "sev": (E or 0) * (ksev or 0)})

        def aggregate(key: str) -> tuple[dict, dict]:
            R, counted = {}, {}
            for party in self.case.parties:
                groups: dict[str, dict] = {}
                for row in rows:
                    if row["r"].action.party_id != party.id or row[key] <= 0:
                        continue
                    g = row["r"].group
                    if g not in groups or row[key] > groups[g][key]:
                        groups[g] = row
                prod = 1.0
                for row in groups.values():
                    prod *= 1 - row[key]
                    counted[row["r"].action.id] = True
                R[party.id] = 1 - prod
            return R, counted

        R, counted = aggregate("score")
        CR, _ = aggregate("cscore")

        def norm(d: dict) -> Optional[dict]:
            tot = sum(d.values())
            return {k: 100 * v / tot for k, v in d.items()} if tot > 0 else None

        fault = norm(R)
        # Severity responsibility: baseline impact energy follows causal fault; excess energy
        # (e.g. from excess speed) goes to the party whose action added it.
        severity = None
        if fault:
            excess = {pt.id: min(1.0, sum(row["sev"] for row in rows if row["r"].action.party_id == pt.id))
                      for pt in self.case.parties}
            tot_ex = sum(excess.values())
            if tot_ex > 1:
                excess = {k: v / tot_ex for k, v in excess.items()}
                tot_ex = 1.0
            severity = {k: fault[k] * (1 - tot_ex) + 100 * excess[k] for k in fault}

        return {"rows": rows, "R": R, "counted": counted, "fault": fault,
                "causal": norm(CR), "severity": severity}

    # ------------------------------------------------------------ public
    def run(self) -> Assessment:
        self._resolve()
        point = self._compute()
        rng = random.Random(self.p.mc_seed)
        samples: dict[str, list[float]] = {pt.id: [] for pt in self.case.parties}
        for _ in range(self.p.mc_draws):
            res = self._compute(rng)
            if res["fault"]:
                for pid, v in res["fault"].items():
                    samples[pid].append(v)

        def interval(pid: str) -> tuple[float, float]:
            s = sorted(samples[pid])
            if not s:
                return (0.0, 0.0)
            return (round(s[int(0.1 * (len(s) - 1))], 1), round(s[int(0.9 * (len(s) - 1))], 1))

        jur = get_jurisdiction(self.case.scene.jurisdiction)
        status, reasons = "DETERMINED", []
        if point["fault"] is None:
            status = "INSUFFICIENT_EVIDENCE"
            reasons.append("No action by any party has established causation of the collision.")
        widths = {pid: interval(pid)[1] - interval(pid)[0] for pid in samples}
        if point["fault"] and max(widths.values()) > self.p.max_interval_width_pts:
            status = "INSUFFICIENT_EVIDENCE"
            reasons.append(f"Uncertainty too large: an 80% interval spans "
                           f"{max(widths.values()):.0f} percentage points.")
        explicit = [row for row in point["rows"] if not row["r"].implicit and row["E"] >= 0.5]
        if explicit:
            undetermined = sum(1 for row in explicit if row["C"] is None) / len(explicit)
            if undetermined > self.p.max_undetermined_share:
                status = "INSUFFICIENT_EVIDENCE"
                reasons.append(f"Causation is undetermined for {undetermined:.0%} of the reported actions.")

        max_w = max(widths.values()) if widths else 100
        uses_prior = any(row["r"].B.source == "catalog_prior" and point["counted"].get(row["r"].action.id)
                         for row in point["rows"])
        if max_w <= 15 and not self.case.conflicts and not uses_prior:
            confidence = "high"
        elif max_w <= 30:
            confidence = "moderate"
        else:
            confidence = "low"

        parties_out = []
        for pt in self.case.parties:
            f = point["fault"][pt.id] if point["fault"] else 0.0
            av = self.avoid.get(pt.id)
            parties_out.append(PartyAssessment(
                party_id=pt.id, label=pt.label, raw_score=round(point["R"][pt.id], 4),
                fault_pct=round(f, 1), fault_interval=interval(pt.id),
                causal_contribution_pct=round(point["causal"][pt.id], 1) if point["causal"] else 0.0,
                severity_responsibility_pct=round(point["severity"][pt.id], 1) if point["severity"] else 0.0,
                avoidability=FactorTrace(
                    value=round(av["A"], 3) if av else None,
                    source="reconstruction" if av else "undetermined",
                    note=(f"stopping distance {av['d_stop']:.0f} ft vs {pt.distance_to_conflict_ft:.0f} ft "
                          f"available; slack {av['margin']:.2f}s (PRT {av['prt']:.1f}s, μ={av['mu']:.2f})")
                    if av else "speed or distance unknown"),
                legal_outcome=legal_outcome(jur.rule, f) if status == "DETERMINED" else ""))

        actions_out = [self._action_out(row, point["counted"]) for row in point["rows"]]
        return Assessment(
            case_id=self.case.id, status=status, status_reasons=reasons, confidence=confidence,
            parties=parties_out, actions=actions_out,
            shared_responsibility=self._shared_text(point),
            uncertainties=list(dict.fromkeys(self.uncertain)),
            missing_information=list(dict.fromkeys(self.missing)),
            conflicts=[c.description for c in self.case.conflicts],
            jurisdiction={"code": jur.code, "name": jur.name, "rule": jur.rule,
                          "rule_text": RULE_TEXT[jur.rule], "authority": jur.authority},
            calculation_steps=self._steps(point))

    # ------------------------------------------------------------ explanation
    def _action_out(self, row: dict, counted: dict) -> ActionAssessment:
        r: Resolved = row["r"]
        a = r.action
        expl = list(r.notes)
        if row["C"] is None:
            expl.append("Level 1: causation could not be established from the evidence — excluded from fault.")
        else:
            expl.append(f"Level 1: but-for {r.B.value:.2f} × mechanism link {r.M.value:.2f} = "
                        f"causation {row['C']:.2f} ({r.B.source.replace('_', ' ')}).")
            if not row["causal"]:
                expl.append(f"Below the causal threshold ({self.p.causal_threshold}) — recorded as a violation "
                            "that did not contribute; adds no fault.")
        expl.append(f"Level 2: severity {row['S']:.2f} ({r.S.note}).")
        if row["K"] is not None:
            parts = ", ".join(f"{k.replace('_', ' ')} {f.value:.2f}" for k, f in r.K.items() if f.value is not None)
            expl.append(f"Level 3: likelihood contribution {row['K']:.2f} from {parts}.")
        if r.Ksev.value is not None:
            expl.append(f"Level 3: severity contribution {r.Ksev.value:.2f} (affects consequences, not causation).")
        if row["score"] > 0:
            expl.append(f"Score = E {row['E']:.2f} × C^{self.p.exp_causation} × K^{self.p.exp_contribution} × "
                        f"S^{self.p.exp_severity} = {row['score']:.3f}.")
            if not counted.get(a.id):
                expl.append(f"Level 5: shares the '{r.group}' mechanism with a stronger action by the same "
                            "party — not counted twice.")
        Ktrace = Factor(row["K"], "derived" if row["K"] is not None else "undetermined", 0,
                        "noisy-OR of contribution factors")
        return ActionAssessment(
            action_id=a.id, party_id=a.party_id, code=a.code, title=r.title, statute=r.statute,
            implicit=r.implicit, evidence_ids=a.evidence_ids, evidence_confidence=round(row["E"], 3),
            causation=Factor(row["C"], r.B.source, 0, r.B.note).trace(),
            severity=r.S.trace(), contribution=Ktrace.trace(), severity_contribution=r.Ksev.trace(),
            mechanism_group=r.group, causal=row["causal"], score=round(row["score"], 4),
            counted=bool(counted.get(a.id)), explanation=expl + ([a.description] if a.description else []))

    def _shared_text(self, point: dict) -> list[str]:
        out = []
        contributors = [pt for pt in self.case.parties if point["R"][pt.id] > 0]
        if len(contributors) >= 2:
            out.append("Concurrent negligence: " + ", ".join(pt.label for pt in contributors) +
                       " each independently contributed to the collision.")
        elif len(contributors) == 1:
            out.append(f"Sole established contributor: {contributors[0].label}.")
        for pt in self.case.parties:
            rows = [r for r in point["rows"] if r["r"].action.party_id == pt.id and r["score"] > 0]
            groups: dict[str, list] = {}
            for r in rows:
                groups.setdefault(r["r"].group, []).append(r)
            for g, rs in groups.items():
                if len(rs) > 1:
                    out.append(f"{pt.label}: {', '.join(x['r'].title for x in rs)} act through the same "
                               f"'{g}' mechanism and are counted once.")
            for r in point["rows"]:
                if r["r"].action.party_id == pt.id and r["causal"] is False:
                    out.append(f"{pt.label}: '{r['r'].title}' occurred but did not contribute causally — no fault.")
        initiators = {r["r"].action.party_id for r in point["rows"] if r["r"].initiates_hazard and r["score"] > 0}
        responders = {r["r"].action.party_id for r in point["rows"]
                      if not r["r"].initiates_hazard and r["score"] > 0} - initiators
        if initiators and responders:
            out.append("Interaction: " + ", ".join(self._label(i) for i in initiators) +
                       " created the hazard; " + ", ".join(self._label(i) for i in responders) +
                       " reduced the ability to respond to it.")
        return out

    def _steps(self, point: dict) -> list[str]:
        steps = ["Each action scored as r = E × C^1.0 × K^0.8 × S^0.5 (zero causation ⇒ zero fault)."]
        for pt in self.case.parties:
            steps.append(f"{pt.label}: R = 1 − Π(1 − strongest r per mechanism) = {point['R'][pt.id]:.3f}.")
        tot = sum(point["R"].values())
        if tot > 0:
            steps.append("Normalized: " + "; ".join(
                f"{pt.label} {point['R'][pt.id]:.3f}/{tot:.3f} = {100 * point['R'][pt.id] / tot:.1f}%"
                for pt in self.case.parties))
        steps.append(f"80% intervals from {self.p.mc_draws} Monte-Carlo draws over input uncertainty.")
        return steps


def assess(case: Case, params: FCHParams = DEFAULT_PARAMS) -> Assessment:
    return Engine(case, params).run()
