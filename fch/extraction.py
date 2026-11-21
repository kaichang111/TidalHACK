"""Automated evidence extraction (NLP over reports/statements + vision over photos/video).

The model only *extracts facts* into the case schema, citing evidence IDs. It never
assigns fault: the deterministic FCH engine does that, so every percentage stays
explainable. Missing facts stay null rather than being guessed.
"""
from __future__ import annotations

import base64
import os
import tempfile
from typing import Literal, Optional

from pydantic import BaseModel

from .laws import CATALOG, JURISDICTIONS
from .models import (Action, CausationInput, Case, Conflict, ContributionInput, Evidence, Party,
                     Scene)

def _model() -> str:
    """Model ID comes from the FCH_MODEL setting in .env."""
    model = os.environ.get("FCH_MODEL", "").strip()
    if not model:
        raise MissingCredentials("No model configured. Add FCH_MODEL=<model id> to the .env file "
                                 "and restart the server.")
    return model
MAX_VIDEO_FRAMES = 6


# ------------------------------------------------------------------ schema for the model
class XParty(BaseModel):
    id: str
    label: str
    vehicle: str
    speed_mph: Optional[float]
    speed_limit_mph: Optional[float]
    distance_to_conflict_ft: Optional[float]
    had_right_of_way: Optional[bool]
    visibility: Literal["good", "reduced", "poor", "unknown"]
    evasive_action_taken: Optional[bool]
    notes: str


class XAction(BaseModel):
    party_id: str
    code: str
    description: str
    evidence_ids: list[str]
    evidence_confidence: float
    magnitude: Optional[float]
    initiated_chain: Optional[bool]


class XEvidence(BaseModel):
    id: str
    kind: Literal["photo", "video", "dashcam", "police_report", "witness",
                  "driver_statement", "telemetry", "diagram", "other"]
    summary: str
    reliability: float


class XConflict(BaseModel):
    description: str
    evidence_ids: list[str]
    party_ids: list[str]


class Extraction(BaseModel):
    title: str
    description: str
    jurisdiction: str
    location: str
    date: str
    road_surface: Literal["dry", "wet", "snow", "ice", "unknown"]
    lighting: Literal["daylight", "dusk", "dark_lit", "dark_unlit", "unknown"]
    collision_type: Literal["angle", "rear_end", "head_on", "sideswipe",
                            "left_turn", "single_vehicle", "pedestrian", "unknown"]
    traffic_control: str
    parties: list[XParty]
    actions: list[XAction]
    evidence: list[XEvidence]
    conflicts: list[XConflict]
    timeline: list[str]


SYSTEM = f"""You are the evidence-extraction stage of an accident fault analysis system.
Your job is to turn submitted evidence into structured facts. You do NOT decide fault.

Rules:
- Only record facts the evidence supports. If a value (speed, distance, right of way,
  whether evasive action was taken, road surface...) is not supported, use null / "unknown".
  Never fill gaps with typical or assumed values.
- Every action must cite the evidence IDs that support it. Set evidence_confidence (0-1)
  to how strongly the cited evidence shows the action actually happened: independent
  objective evidence (video, telemetry) is high; a single interested party's claim is ~0.5.
- Use these action codes: {", ".join(f"{c} ({v.title})" for c, v in CATALOG.items() if c != "FAILURE_TO_AVOID")}.
  Record every potential violation, including ones that may not have contributed (e.g. an
  expired registration) — the downstream engine decides causation.
- magnitude: for SPEEDING the mph over the limit; for DISTRACTED the seconds of inattention; else null.
- initiated_chain: true only if the evidence shows this action started the sequence of events.
- distance_to_conflict_ft: the party's distance to the collision point when the hazard first
  became perceivable to them — only if measurable from the evidence.
- Assess each evidence item's reliability (0-1): objective recordings high, police
  observations moderately high, interested-party statements low.
- Record every conflict between accounts explicitly, naming the evidence and parties.
- jurisdiction: a two-letter US state code if determinable, else one of {", ".join(JURISDICTIONS)}.
- Give each party a short id (A, B, C...). Produce a concise timeline of the events.
"""


class MissingCredentials(RuntimeError):
    pass


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    import anthropic
    if not has_credentials():
        raise MissingCredentials(
            "No Anthropic API key configured. Add ANTHROPIC_API_KEY=... to the .env file "
            "in the project folder and restart the server.")
    return anthropic.Anthropic()


def video_frames(data: bytes, suffix: str = ".mp4", n: int = MAX_VIDEO_FRAMES) -> list[tuple[float, bytes]]:
    """Sample n evenly spaced JPEG frames from a video. Returns [] if OpenCV is unavailable."""
    try:
        import cv2
    except ImportError:
        return []
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    frames = []
    try:
        cap = cv2.VideoCapture(path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        for i in range(n):
            idx = int(total * (i + 0.5) / n) if total else i * int(fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                frames.append((idx / fps, buf.tobytes()))
        cap.release()
    finally:
        os.unlink(path)
    return frames


def build_content(texts: list[dict], media: list[dict]) -> list[dict]:
    """texts: [{id, kind, source, text}]; media: [{id, kind, source, media_type, data(bytes)}]."""
    content: list[dict] = []
    for m in media:
        if m["media_type"].startswith("video/"):
            frames = video_frames(m["data"], "." + m["media_type"].split("/")[-1])
            if not frames:
                content.append({"type": "text", "text": f"[{m['id']}] video '{m['source']}' could not be decoded."})
            for t, jpg in frames:
                content.append({"type": "text", "text": f"[{m['id']}] {m['kind']} '{m['source']}', frame at t={t:.1f}s:"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.standard_b64encode(jpg).decode()}})
        else:
            content.append({"type": "text", "text": f"[{m['id']}] {m['kind']} '{m['source']}':"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": m["media_type"],
                                                        "data": base64.standard_b64encode(m["data"]).decode()}})
    for t in texts:
        content.append({"type": "text", "text": f"[{t['id']}] {t['kind']} — {t['source']}\n\"\"\"\n{t['text']}\n\"\"\""})
    content.append({"type": "text", "text":
                    "Extract the structured case from the evidence above. Use the bracketed IDs as evidence IDs."})
    return content


def extract_case(texts: list[dict], media: list[dict], jurisdiction_hint: str = "") -> tuple[Case, list[str]]:
    import anthropic

    content = build_content(texts, media)
    if jurisdiction_hint:
        content.append({"type": "text", "text": f"The user indicated jurisdiction: {jurisdiction_hint}."})
    kwargs = dict(model=_model(), max_tokens=16000, system=SYSTEM,
                  output_config={"effort": "high"},
                  messages=[{"role": "user", "content": content}], output_format=Extraction)
    client = _client()
    try:
        # Server-side fallback: if the request is declined by a safety classifier,
        # the API retries it on a fallback model within the same call.
        resp = client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"],
                                          fallbacks="default", **kwargs)
    except anthropic.BadRequestError as e:
        if "fallback" not in str(e).lower():
            raise
        resp = client.messages.parse(**kwargs)  # account without the fallback beta
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to process this evidence.")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError("Extraction was incomplete; try submitting less material at once.")
    return to_case(resp.parsed_output, texts, media)


def to_case(x: Extraction, texts: list[dict], media: list[dict]) -> tuple[Case, list[str]]:
    src = {d["id"]: d for d in texts + media}
    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    evidence = [Evidence(id=e.id, kind=e.kind, source=src.get(e.id, {}).get("source", e.id),
                         summary=e.summary, reliability=clamp(e.reliability)) for e in x.evidence]
    seen = {e.id for e in evidence}
    for d in texts + media:  # ensure every submission appears as evidence
        if d["id"] not in seen:
            evidence.append(Evidence(id=d["id"], kind=d.get("kind", "other"), source=d["source"],
                                     summary="(no facts extracted)", reliability=0.5))
    actions = [Action(id=f"x{i + 1}", party_id=a.party_id, code=a.code.upper(), description=a.description,
                      evidence_ids=a.evidence_ids, evidence_confidence=clamp(a.evidence_confidence),
                      magnitude=a.magnitude, causation=CausationInput(initiated_chain=a.initiated_chain),
                      contribution=ContributionInput())
               for i, a in enumerate(x.actions)]
    case = Case(
        id="extracted", title=x.title, description=x.description,
        scene=Scene(jurisdiction=x.jurisdiction.upper() if x.jurisdiction.upper() in JURISDICTIONS else "GENERIC",
                    location=x.location, date=x.date, road_surface=x.road_surface, lighting=x.lighting,
                    collision_type=x.collision_type, traffic_control=x.traffic_control),
        parties=[Party(**p.model_dump()) for p in x.parties],
        actions=actions, evidence=evidence,
        conflicts=[Conflict(**c.model_dump()) for c in x.conflicts])
    return case, x.timeline
