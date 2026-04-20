# DDR Generator — AI Generalist Assignment

Generate a structured **Detailed Diagnostic Report (DDR)** from a property
**Inspection Report PDF** + **Thermal Report PDF**.

The system extracts text and images from both PDFs, detects areas and defects,
merges findings across sources (removing duplicates, flagging conflicts, mapping
images to the correct observation), and emits a Markdown DDR with the seven
required sections. Missing fields are explicitly marked `Not Available` — the
system never fabricates data.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# optional: LLM-powered generation
echo "OPENAI_API_KEY=sk-..." > .env

# run the API
uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

### CLI (no server needed)

```bash
python -m app.cli \
  --inspection samples/inspection_sample.pdf \
  --thermal    samples/thermal_sample.pdf \
  --out        samples/sample_ddr.md \
  --offline           # skip the LLM call
```

### API

`POST /generate-report` — multipart form

| field            | type      | required | notes                                |
|------------------|-----------|----------|--------------------------------------|
| `inspection_pdf` | file      | yes      | inspection report PDF                |
| `thermal_pdf`    | file      | yes      | thermal report PDF                   |
| `address`        | string    | no       | property address for metadata block  |
| `client`         | string    | no       | client name                          |
| `date`           | string    | no       | inspection date                      |
| `use_llm`        | bool      | no       | default `true`; falls back if no key |

Response:

```json
{
  "markdown": "# Detailed Diagnostic Report ...",
  "observations": [ { "area": "Roof", "defect": "termite", "severity": "high",
                      "sources": ["inspection","thermal"], "images": ["/assets/..png"],
                      "pages": [2, 3], "conflict_note": "" } ],
  "run_id": "run-ab12cd34ef56"
}
```

`POST /generate-report.md` returns the Markdown directly (handy for piping into
a doc converter).

Extracted images are served from `/assets/{run_id}/images/` so the DDR Markdown
is directly renderable.

---

## DDR sections produced

1. Property Issue Summary
2. Areawise Observations (images inlined per finding)
3. Probable Root Cause
4. Severity Assessment (High / Medium / Low with reasoning)
5. Recommended Actions
6. Additional Notes (surfaces cross-source conflicts)
7. Missing or Unclear Information

---

## Project layout

```
ddr_generator/
├── app/
│   ├── main.py          FastAPI endpoints
│   ├── cli.py           Command-line entry point
│   ├── extractor.py     PDF → text blocks, images, findings
│   ├── merger.py        Cross-source dedupe + conflict detection
│   └── ddr_builder.py   LLM + offline fallback DDR generation
├── prompts/
│   └── ddr_system.txt   LLM system prompt (deterministic structure)
├── samples/             Fake PDFs + generated sample DDR
├── docs/
│   └── architecture.md  How it works, design decisions, limits
├── requirements.txt
└── README.md
```

See `docs/architecture.md` for the design notes and `samples/sample_ddr.md`
for a ready-made DDR generated from the included sample inputs.
