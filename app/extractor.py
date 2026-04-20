"""
PDF extraction utilities.

Extracts text blocks and embedded images from a PDF and associates each
image with the nearest text block (used later to map images to DDR areas).
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from PIL import Image


@dataclass
class TextBlock:
    page: int
    bbox: tuple          # (x0, y0, x1, y1)
    text: str

    @property
    def center(self) -> tuple:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)


@dataclass
class ImageAsset:
    page: int
    bbox: tuple
    path: str            # saved image path on disk
    nearby_text: str = ""  # text near the image, used as caption hint
    caption_guess: str = ""

    @property
    def center(self) -> tuple:
        x0, y0, x1, y1 = self.bbox
        return ((x0 + x1) / 2, (y0 + y1) / 2)


@dataclass
class ExtractedDocument:
    source_path: str
    kind: str                              # "inspection" | "thermal"
    text_blocks: List[TextBlock] = field(default_factory=list)
    images: List[ImageAsset] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(b.text for b in self.text_blocks)


def _hash_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()[:10]


def extract_pdf(
    pdf_path: str,
    kind: str,
    out_dir: str,
) -> ExtractedDocument:
    """Extract text blocks and images from a PDF.

    Images are saved to ``out_dir`` and deduplicated by content hash so a logo
    appearing on every page is only stored once.
    """
    os.makedirs(out_dir, exist_ok=True)
    doc = ExtractedDocument(source_path=pdf_path, kind=kind)
    seen_hashes: set[str] = set()

    with fitz.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf, start=1):
            # ---- text blocks ----
            for block in page.get_text("blocks"):
                x0, y0, x1, y1, text, *_ = block
                text = (text or "").strip()
                if not text:
                    continue
                doc.text_blocks.append(
                    TextBlock(page=page_idx, bbox=(x0, y0, x1, y1), text=text)
                )

            # ---- images ----
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    base = pdf.extract_image(xref)
                except Exception:
                    continue
                img_bytes = base.get("image")
                if not img_bytes:
                    continue
                h = _hash_bytes(img_bytes)
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)

                ext = base.get("ext", "png")
                fname = f"{kind}_p{page_idx}_{h}.{ext}"
                fpath = str(Path(out_dir) / fname)
                try:
                    with open(fpath, "wb") as f:
                        f.write(img_bytes)
                except Exception:
                    continue

                # find bbox of this image on the page (best-effort)
                bbox = (0, 0, 0, 0)
                try:
                    rects = page.get_image_rects(xref)
                    if rects:
                        r = rects[0]
                        bbox = (r.x0, r.y0, r.x1, r.y1)
                except Exception:
                    pass

                doc.images.append(
                    ImageAsset(page=page_idx, bbox=bbox, path=fpath)
                )

    _attach_nearby_text(doc)
    return doc


def _attach_nearby_text(doc: ExtractedDocument, radius: float = 150.0) -> None:
    """For each image, find the closest text block on the same page."""
    for img in doc.images:
        best: Optional[TextBlock] = None
        best_d = float("inf")
        for tb in doc.text_blocks:
            if tb.page != img.page:
                continue
            dx = tb.center[0] - img.center[0]
            dy = tb.center[1] - img.center[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best_d = d
                best = tb
        if best and best_d <= radius * 4:
            img.nearby_text = best.text[:400]
            # first non-empty line is a good caption guess
            first_line = next(
                (ln.strip() for ln in best.text.splitlines() if ln.strip()),
                "",
            )
            img.caption_guess = first_line[:160]


# ---- lightweight section / finding detection -------------------------------

AREA_KEYWORDS = [
    "roof", "roof void", "roof structure", "eaves", "flashing",
    "garage", "bedroom", "living", "kitchen", "bathroom", "ensuite",
    "laundry", "wet area", "wall", "ceiling", "floor", "window",
    "exterior", "interior", "foundation", "subfloor", "plumbing",
    "electrical", "driveway", "fence",
]

DEFECT_KEYWORDS = [
    "crack", "termite", "moisture", "leak", "stain", "damp",
    "damage", "missing", "corrosion", "rust", "rot", "mould",
    "mold", "warp", "loose", "broken", "worn", "hot spot",
    "thermal anomaly", "overheat", "cold spot",
]


@dataclass
class Finding:
    area: str
    defect: str
    severity_hint: str
    source: str            # "inspection" | "thermal"
    page: int
    raw_text: str
    image_paths: List[str] = field(default_factory=list)


def detect_findings(doc: ExtractedDocument) -> List[Finding]:
    findings: List[Finding] = []
    for tb in doc.text_blocks:
        text_low = tb.text.lower()
        area = next((a for a in AREA_KEYWORDS if a in text_low), "")
        defect = next((d for d in DEFECT_KEYWORDS if d in text_low), "")
        if not (area or defect):
            continue
        # skip obvious headers / TOC-only lines
        if len(tb.text.strip()) < 12:
            continue
        severity = _severity_hint(text_low)
        findings.append(
            Finding(
                area=area.title() if area else "General",
                defect=defect or "observation",
                severity_hint=severity,
                source=doc.kind,
                page=tb.page,
                raw_text=re.sub(r"\s+", " ", tb.text).strip()[:800],
            )
        )
    _attach_images_to_findings(doc, findings)
    return findings


def _severity_hint(text: str) -> str:
    if any(w in text for w in ["urgent", "immediate", "severe", "structural"]):
        return "high"
    if any(w in text for w in ["monitor", "minor", "cosmetic", "wear"]):
        return "low"
    return "medium"


def _attach_images_to_findings(doc: ExtractedDocument, findings: List[Finding]) -> None:
    """Attach each image to the finding whose text best matches its caption."""
    for img in doc.images:
        if not img.nearby_text:
            continue
        caption_low = img.nearby_text.lower()
        best: Optional[Finding] = None
        best_score = 0
        for f in findings:
            if f.page != img.page:
                continue
            score = 0
            if f.area.lower() in caption_low:
                score += 2
            if f.defect.lower() in caption_low:
                score += 2
            # longest-common token overlap
            raw_tokens = set(re.findall(r"[a-z]{4,}", f.raw_text.lower()))
            cap_tokens = set(re.findall(r"[a-z]{4,}", caption_low))
            score += len(raw_tokens & cap_tokens)
            if score > best_score:
                best_score = score
                best = f
        if best and best_score >= 2:
            best.image_paths.append(img.path)
