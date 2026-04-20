"""
FastAPI entrypoint for the DDR generator.

Endpoints
---------
GET  /health            -> liveness
POST /generate-report   -> multipart upload of inspection_pdf + thermal_pdf,
                           returns JSON: {markdown, observations, images[]}
POST /generate-report.md-> same inputs, returns raw markdown
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .extractor import detect_findings, extract_pdf
from .merger import merge_findings
from .ddr_builder import build_ddr_offline, build_ddr_with_llm

load_dotenv()

WORK_ROOT = Path(os.getenv("DDR_WORK_DIR", tempfile.gettempdir())) / "ddr_runs"
WORK_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="DDR Generator",
    description="Generates a Detailed Diagnostic Report from an Inspection PDF + Thermal PDF.",
    version="1.0.0",
)

# Serve extracted images so they can be rendered from the DDR markdown.
app.mount("/assets", StaticFiles(directory=str(WORK_ROOT)), name="assets")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _save_upload(upload: UploadFile, dest: Path) -> None:
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)


def _pipeline(inspection_path: Path, thermal_path: Path, run_dir: Path, use_llm: bool,
              metadata: Optional[dict] = None) -> dict:
    images_dir = run_dir / "images"
    images_dir.mkdir(exist_ok=True)

    ins_doc = extract_pdf(str(inspection_path), "inspection", str(images_dir))
    thr_doc = extract_pdf(str(thermal_path), "thermal", str(images_dir))

    ins_findings = detect_findings(ins_doc)
    thr_findings = detect_findings(thr_doc)
    merged = merge_findings(ins_findings, thr_findings)

    # Rewrite image paths to use the /assets URL so the returned markdown
    # can be rendered directly by a frontend.
    rel_root = run_dir.name
    for m in merged:
        m.image_paths = [
            f"/assets/{rel_root}/images/{Path(p).name}" for p in m.image_paths
        ]

    markdown: str
    if use_llm and os.getenv("OPENAI_API_KEY"):
        try:
            markdown = build_ddr_with_llm(merged, metadata=metadata)
        except Exception as e:  # graceful fallback
            markdown = (
                build_ddr_offline(merged, metadata=metadata)
                + f"\n\n> _LLM call failed ({e!s}); served offline template._"
            )
    else:
        markdown = build_ddr_offline(merged, metadata=metadata)

    return {
        "markdown": markdown,
        "observations": [
            {
                "area": m.area,
                "defect": m.defect,
                "severity": m.severity,
                "sources": m.sources,
                "pages": m.pages,
                "images": m.image_paths,
                "conflict_note": m.conflict_note,
            }
            for m in merged
        ],
        "run_id": run_dir.name,
    }


@app.post("/generate-report")
async def generate_report(
    inspection_pdf: UploadFile = File(...),
    thermal_pdf: UploadFile = File(...),
    address: Optional[str] = Form(None),
    client: Optional[str] = Form(None),
    date: Optional[str] = Form(None),
    use_llm: bool = Form(True),
):
    if not inspection_pdf.filename or not thermal_pdf.filename:
        raise HTTPException(status_code=400, detail="Both PDFs are required.")

    run_dir = WORK_ROOT / f"run-{uuid.uuid4().hex[:12]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    ins_path = run_dir / "inspection.pdf"
    thr_path = run_dir / "thermal.pdf"
    _save_upload(inspection_pdf, ins_path)
    _save_upload(thermal_pdf, thr_path)

    metadata = {k: v for k, v in {"address": address, "client": client, "date": date}.items() if v}
    result = _pipeline(ins_path, thr_path, run_dir, use_llm=use_llm, metadata=metadata)
    return JSONResponse(result)


@app.post("/generate-report.md", response_class=PlainTextResponse)
async def generate_report_md(
    inspection_pdf: UploadFile = File(...),
    thermal_pdf: UploadFile = File(...),
    use_llm: bool = Form(True),
):
    run_dir = WORK_ROOT / f"run-{uuid.uuid4().hex[:12]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    ins_path = run_dir / "inspection.pdf"
    thr_path = run_dir / "thermal.pdf"
    _save_upload(inspection_pdf, ins_path)
    _save_upload(thermal_pdf, thr_path)
    result = _pipeline(ins_path, thr_path, run_dir, use_llm=use_llm)
    return result["markdown"]
