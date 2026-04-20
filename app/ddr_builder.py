"""
Build the final DDR markdown.

Two paths:
- `build_ddr_with_llm`  -> calls OpenAI GPT-4o with the merged observations.
- `build_ddr_offline`   -> deterministic template fallback (used when no API
                           key is configured or the LLM call fails).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from .merger import MergedObservation, SEV_RANK

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "ddr_system.txt"


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _observations_to_llm_payload(obs: List[MergedObservation]) -> str:
    payload = []
    for m in obs:
        payload.append(
            {
                "area": m.area,
                "defect": m.defect,
                "severity": m.severity,
                "sources": m.sources,
                "pages": m.pages,
                "observations": m.raw_texts,
                "image_paths": m.image_paths,
                "conflict_note": m.conflict_note,
            }
        )
    return json.dumps(payload, indent=2)


def build_ddr_with_llm(
    observations: List[MergedObservation],
    metadata: Optional[dict] = None,
    model: str = "gpt-4o-mini",
) -> str:
    """Call OpenAI to produce the DDR. Requires OPENAI_API_KEY."""
    from openai import OpenAI

    client = OpenAI()
    system = _load_system_prompt()
    user = (
        f"Property metadata (may be incomplete):\n"
        f"{json.dumps(metadata or {}, indent=2)}\n\n"
        f"Merged observations (JSON):\n{_observations_to_llm_payload(observations)}"
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content.strip()


def build_ddr_offline(
    observations: List[MergedObservation],
    metadata: Optional[dict] = None,
) -> str:
    """Deterministic fallback that still produces a valid DDR."""
    md = metadata or {}
    lines: list[str] = []

    lines.append("# Detailed Diagnostic Report (DDR)\n")
    lines.append(f"- Property Address: {md.get('address', 'Not Available')}")
    lines.append(f"- Client Name:      {md.get('client', 'Not Available')}")
    lines.append(f"- Inspection Date:  {md.get('date', 'Not Available')}\n")

    # 1. Summary
    lines.append("## Property Issue Summary\n")
    if not observations:
        lines.append("No observations were extracted. Source quality may be low.\n")
    else:
        highs = [o for o in observations if o.severity == "high"]
        meds = [o for o in observations if o.severity == "medium"]
        lows = [o for o in observations if o.severity == "low"]
        lines.append(
            f"A combined review of the inspection and thermal reports identified "
            f"{len(observations)} distinct observations: "
            f"{len(highs)} high severity, {len(meds)} medium, {len(lows)} low.\n"
        )

    # 2. Areawise Observations
    lines.append("## Areawise Observations\n")
    by_area: dict[str, list[MergedObservation]] = {}
    for o in observations:
        by_area.setdefault(o.area, []).append(o)
    for area, items in sorted(by_area.items()):
        lines.append(f"### {area}\n")
        for o in items:
            src = "[Both]" if len(o.sources) > 1 else f"[{o.sources[0].title()}]"
            lines.append(f"- **{o.defect.title()}** {src} — {o.raw_texts[0]}")
            for img in o.image_paths:
                lines.append(f"  ![finding]({img})")
            if not o.image_paths:
                lines.append("  _Image: Not Available_")
        lines.append("")

    # 3. Probable Root Cause
    lines.append("## Probable Root Cause\n")
    defects = {o.defect.lower() for o in observations}
    causes = []
    if "moisture" in defects or "leak" in defects or "stain" in defects:
        causes.append("water ingress and inadequate moisture management")
    if "termite" in defects:
        causes.append("active or historical termite activity")
    if "crack" in defects:
        causes.append("structural movement or thermal expansion")
    if "hot spot" in defects or "thermal anomaly" in defects:
        causes.append("electrical or insulation irregularities visible in thermal imaging")
    lines.append(
        "Likely contributing factors: " + ", ".join(causes) + "."
        if causes
        else "Root cause analysis requires further on-site investigation."
    )
    lines.append("")

    # 4. Severity Assessment
    lines.append("## Severity Assessment\n")
    for level in ("high", "medium", "low"):
        group = [o for o in observations if o.severity == level]
        if not group:
            continue
        lines.append(f"### {level.title()} severity")
        for o in group:
            lines.append(
                f"- {o.area} / {o.defect} — {_reason_for(level)}"
            )
        lines.append("")

    # 5. Recommended Actions
    lines.append("## Recommended Actions\n")
    actions = _recommend(observations)
    for i, a in enumerate(actions, 1):
        lines.append(f"{i}. {a}")
    if not actions:
        lines.append("No specific actions derivable from extracted content.")
    lines.append("")

    # 6. Additional Notes
    lines.append("## Additional Notes\n")
    conflicts = [o for o in observations if o.conflict_note]
    if conflicts:
        for o in conflicts:
            lines.append(f"- {o.area} / {o.defect}: {o.conflict_note}")
    else:
        lines.append("No cross-source conflicts detected.")
    lines.append(
        "\nThis DDR is generated automatically from the supplied PDFs and should "
        "be validated by a licensed inspector before action."
    )

    # 7. Missing / Unclear
    lines.append("\n## Missing or Unclear Information\n")
    for k in ("address", "client", "date"):
        if not md.get(k):
            lines.append(f"- {k.title()}: Not Available")
    if not any(o.image_paths for o in observations):
        lines.append("- Property-specific images: Not Available")

    return "\n".join(lines)


def _reason_for(level: str) -> str:
    return {
        "high": "may affect structural integrity or safety; prioritize follow-up.",
        "medium": "likely to worsen without intervention; schedule remediation.",
        "low": "cosmetic or maintenance-grade; address during routine upkeep.",
    }[level]


def _recommend(obs: List[MergedObservation]) -> list[str]:
    recs: list[str] = []
    defects = {o.defect.lower() for o in obs}
    if "termite" in defects:
        recs.append("Engage a licensed pest inspector for termite assessment and treatment.")
    if "moisture" in defects or "leak" in defects or "stain" in defects:
        recs.append("Investigate water ingress sources; repair flashings and seal leaks.")
    if "crack" in defects:
        recs.append("Have cracked tiles/walls assessed by a structural engineer.")
    if "hot spot" in defects or "thermal anomaly" in defects:
        recs.append("Book an electrician to investigate thermal anomalies in wiring/panels.")
    if "missing" in defects:
        recs.append("Install missing fittings (e.g. vermin caps, waste grates) per code.")
    if not recs:
        recs.append("Conduct a full follow-up inspection for items flagged above.")
    return recs
