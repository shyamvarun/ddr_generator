"""
Command-line alternative to the FastAPI endpoint:

    python -m app.cli --inspection path/to/inspection.pdf \
                      --thermal    path/to/thermal.pdf \
                      --out        ./out/ddr.md
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .extractor import detect_findings, extract_pdf
from .merger import merge_findings
from .ddr_builder import build_ddr_offline, build_ddr_with_llm


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Generate a DDR markdown report.")
    parser.add_argument("--inspection", required=True, help="Inspection report PDF")
    parser.add_argument("--thermal", required=True, help="Thermal report PDF")
    parser.add_argument("--out", default="ddr.md", help="Output markdown file")
    parser.add_argument("--offline", action="store_true", help="Skip LLM call")
    parser.add_argument("--address", default=None)
    parser.add_argument("--client", default=None)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    work = out_path.parent / f"{out_path.stem}_assets"
    work.mkdir(parents=True, exist_ok=True)

    ins = extract_pdf(args.inspection, "inspection", str(work))
    thr = extract_pdf(args.thermal, "thermal", str(work))
    merged = merge_findings(detect_findings(ins), detect_findings(thr))

    meta = {k: v for k, v in {"address": args.address, "client": args.client, "date": args.date}.items() if v}

    if not args.offline and os.getenv("OPENAI_API_KEY"):
        try:
            md = build_ddr_with_llm(merged, metadata=meta)
        except Exception as e:
            md = build_ddr_offline(merged, metadata=meta) + f"\n\n> LLM fallback: {e}"
    else:
        md = build_ddr_offline(merged, metadata=meta)

    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote DDR -> {out_path}")
    print(f"Assets    -> {work}")


if __name__ == "__main__":
    main()
