# Architecture

## Pipeline

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Inspection   │   │ Thermal      │   │ Merge /      │   │ DDR builder  │
│ PDF          │──►│ PDF          │──►│ dedupe /     │──►│ (LLM + offline│
│              │   │              │   │ conflict     │   │  fallback)    │
│  extractor   │   │  extractor   │   │  detection   │   │              │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
        │                 │                                    │
        └── images ───────┘                                    ▼
                 saved to /assets/{run_id}/images/     Markdown DDR
                 (served via StaticFiles)              + JSON observations
```

## Components

### `extractor.py`

- **Text blocks**: `page.get_text("blocks")` keeps bbox + text so we know
  where on the page a statement lives.
- **Images**: `page.get_images(full=True)` + `pdf.extract_image(xref)`;
  content-hashed to dedupe repeating logos / headers.
- **Image → text association**: for each image, find the closest text block
  on the same page and store it as `nearby_text` / `caption_guess`. This is
  what later maps an image to its observation.
- **Finding detection**: keyword scan over `AREA_KEYWORDS` + `DEFECT_KEYWORDS`
  with a lightweight severity heuristic (keywords like "urgent", "structural"
  → high; "monitor", "cosmetic" → low).

### `merger.py`

- Groups findings by `(area, defect)` key.
- **Dedupe inside a bucket** uses `rapidfuzz.fuzz.token_set_ratio > 85` so
  phrasing differences don't produce duplicates.
- **Conflict flag** when both sources appear in the bucket AND their severity
  hints differ — we keep the highest severity and attach a `conflict_note`.
- Image paths from all contributing findings are unioned, so an image from
  the thermal report can appear under an observation originally raised by the
  inspection report.

### `ddr_builder.py`

Two code paths so the system is always operational:

- **`build_ddr_with_llm`** — calls OpenAI GPT-4o-mini with a strict system
  prompt (`prompts/ddr_system.txt`) that enforces the 7 required sections,
  bans fabrication, and requires `Not Available` for missing fields.
- **`build_ddr_offline`** — deterministic template, used when
  `OPENAI_API_KEY` is absent or the API call fails. Produces the same 7
  sections from the merged observations directly.

### `main.py`

- FastAPI endpoints that save uploads into a per-request `run_dir`, run the
  pipeline, and rewrite image paths to `/assets/{run_id}/images/...` URLs so
  a frontend can render the returned markdown with images intact.

## Design decisions

| Decision                                        | Why                                                       |
|-------------------------------------------------|-----------------------------------------------------------|
| PyMuPDF instead of `pdfplumber` + `pdf2image`   | One dependency for both text blocks *and* image xrefs.    |
| Content hash for image dedupe                   | Sample reports repeat headers/logos on every page.        |
| Fuzzy match for text dedupe                     | "Cracked tiles near ridge" vs. "Cracked roof tiles" etc.  |
| Offline fallback DDR                            | Assignment must still run without an API key.             |
| Severity from keywords, not the LLM             | Deterministic, auditable, works offline.                  |
| Images attached by nearest-on-page + token overlap | Simple, explainable, no ML dependency.                 |
| Per-request `run_dir` under a mounted StaticFiles | Returned Markdown stays renderable end-to-end.          |

## Limits / known gaps

- **Scanned PDFs**: if either report is image-only, text extraction yields
  nothing and findings will be empty. Dropping `pytesseract` / `ocrmypdf`
  in front of the extractor is the natural extension.
- **Complex layouts**: multi-column pages can fragment a finding across
  text blocks. The fuzzy-dedupe step mitigates but does not eliminate this.
- **Image → area mapping** is heuristic, not semantic. For production a
  vision model (e.g. GPT-4o vision) should label the image and we'd merge
  on that label.
- **Severity**: keyword-only. An LLM severity pass would be more nuanced but
  would also make output non-deterministic.

## Extending

- Swap `build_ddr_with_llm` for Gemini / Claude by replacing the client.
- Add OCR: call `ocrmypdf` on the uploaded PDF before `extract_pdf`.
- Add vision captioning: for each `ImageAsset`, send it to `gpt-4o` with a
  caption-only prompt, store the result on `caption_guess`, then use it in
  the merge key.
- Persist runs: swap `tempfile`-based `WORK_ROOT` for S3 + a database
  row per run so reports are re-downloadable.
