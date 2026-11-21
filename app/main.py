"""FastAPI backend: evidence extraction, FCH assessment, catalog and samples."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fch.engine import assess
from fch.laws import CATALOG, JURISDICTIONS, RULE_TEXT
from fch.models import Case
from fch.report import build_report

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
WEB = ROOT / "web"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=value lines) so the API key needn't be set in the shell."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # tolerate shell-style lines: `export KEY=...` and PowerShell `$env:KEY = "..."`
        for prefix in ("export ", "$env:"):
            if key.lower().startswith(prefix.lower()):
                key = key[len(prefix):].strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

app = FastAPI(title="FCH Accident Fault Determination", version="0.1.0")


class AssessRequest(BaseModel):
    case: Case
    timeline: Optional[list[str]] = None


@app.get("/api/health")
def health():
    from fch.extraction import has_credentials
    return {"ok": True,
            "extraction_available": has_credentials() and bool(os.environ.get("FCH_MODEL", "").strip())}


@app.get("/api/catalog")
def catalog():
    return {
        "violations": [{"code": v.code, "title": v.title, "base_severity": v.base_severity,
                        "mechanism_group": v.mechanism_group} for v in CATALOG.values()
                       if v.code != "FAILURE_TO_AVOID"],
        "jurisdictions": [{"code": j.code, "name": j.name, "rule": j.rule, "rule_text": RULE_TEXT[j.rule],
                           "authority": j.authority} for j in JURISDICTIONS.values()],
    }


@app.get("/api/samples")
def samples():
    out = []
    for f in sorted(SAMPLES.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out.append({"id": f.stem, "title": data.get("title", f.stem), "case": data})
    return out


@app.post("/api/assess")
def run_assessment(req: AssessRequest):
    known = {p.id for p in req.case.parties}
    bad = [a.id for a in req.case.actions if a.party_id not in known]
    if bad:
        raise HTTPException(422, f"Actions reference unknown parties: {', '.join(bad)}")
    a = assess(req.case)
    return {"assessment": a.model_dump(), "report": build_report(req.case, a, req.timeline)}


TEXT_KINDS = {"police_report", "witness", "driver_statement", "other"}


@app.post("/api/extract")
async def extract(
    jurisdiction: str = Form(""),
    police_report: str = Form(""),
    witness_statements: str = Form(""),
    driver_statements: str = Form(""),
    description: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    from fch.extraction import MissingCredentials, extract_case, has_credentials

    if not has_credentials():
        raise HTTPException(401, "No Anthropic API key configured. Add ANTHROPIC_API_KEY=... to the "
                                 ".env file in the project folder and restart the server.")

    texts = []
    for kind, label, body in [("police_report", "Police report", police_report),
                              ("witness", "Witness statements", witness_statements),
                              ("driver_statement", "Driver statements", driver_statements),
                              ("other", "Accident description", description)]:
        if body.strip():
            texts.append({"id": f"t{len(texts) + 1}", "kind": kind, "source": label, "text": body})
    media = []
    for i, f in enumerate(files):
        ct = f.content_type or ""
        data = await f.read()
        if not data:
            continue
        if ct.startswith("image/"):
            if ct not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                raise HTTPException(415, f"Unsupported image type {ct}")
            media.append({"id": f"m{i + 1}", "kind": "photo", "source": f.filename, "media_type": ct, "data": data})
        elif ct.startswith("video/"):
            media.append({"id": f"m{i + 1}", "kind": "dashcam", "source": f.filename, "media_type": ct, "data": data})
        elif ct in ("text/plain", "application/octet-stream") and f.filename.lower().endswith(".txt"):
            texts.append({"id": f"t{len(texts) + 1}", "kind": "other", "source": f.filename,
                          "text": data.decode("utf-8", errors="replace")})
        else:
            raise HTTPException(415, f"Unsupported file type for {f.filename}: {ct}")
    if not texts and not media:
        raise HTTPException(400, "Submit at least one text or file.")
    try:
        case, timeline = extract_case(texts, media, jurisdiction)
    except MissingCredentials as e:
        raise HTTPException(401, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:  # surface auth / network problems to the UI
        name = type(e).__name__
        if name in ("AuthenticationError", "PermissionDeniedError"):
            raise HTTPException(401, "Extraction service credentials missing or invalid. Set ANTHROPIC_API_KEY.")
        if name in ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"):
            raise HTTPException(503, f"Extraction service unavailable ({name}). Try again shortly.")
        if name == "BadRequestError":  # e.g. low credit balance, oversized request
            body = getattr(e, "body", None)
            msg = body.get("error", {}).get("message") if isinstance(body, dict) else None
            raise HTTPException(400, f"Extraction service rejected the request: {msg or e}")
        raise
    return {"case": case.model_dump(), "timeline": timeline}


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def no_stale_static(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # revalidate so UI edits show up immediately
    return resp
