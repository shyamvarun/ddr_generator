"""
Merge findings from inspection + thermal reports.

Responsibilities:
- Group findings by normalized (area, defect) key.
- Remove duplicates.
- Keep provenance (which source mentioned it).
- Flag conflicts when sources disagree on severity.
- Carry image paths from whichever source has them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from rapidfuzz import fuzz

from .extractor import Finding


@dataclass
class MergedObservation:
    area: str
    defect: str
    severity: str
    sources: List[str] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)
    raw_texts: List[str] = field(default_factory=list)
    image_paths: List[str] = field(default_factory=list)
    conflict_note: str = ""


SEV_RANK = {"low": 1, "medium": 2, "high": 3}


def _key(area: str, defect: str) -> str:
    return f"{area.strip().lower()}|{defect.strip().lower()}"


def merge_findings(
    inspection: List[Finding],
    thermal: List[Finding],
) -> List[MergedObservation]:
    """Combine findings across both reports."""
    buckets: Dict[str, List[Finding]] = defaultdict(list)
    for f in inspection + thermal:
        buckets[_key(f.area, f.defect)].append(f)

    merged: List[MergedObservation] = []
    for key, group in buckets.items():
        # dedupe very similar raw_text entries inside the same bucket
        deduped_texts: List[str] = []
        for f in group:
            if not any(fuzz.token_set_ratio(f.raw_text, t) > 85 for t in deduped_texts):
                deduped_texts.append(f.raw_text)

        severities = [SEV_RANK.get(f.severity_hint, 2) for f in group]
        max_sev = max(severities)
        min_sev = min(severities)
        severity = {1: "low", 2: "medium", 3: "high"}[max_sev]
        conflict_note = (
            "Sources disagree on severity — highest retained."
            if max_sev != min_sev and len({f.source for f in group}) > 1
            else ""
        )

        merged.append(
            MergedObservation(
                area=group[0].area,
                defect=group[0].defect,
                severity=severity,
                sources=sorted({f.source for f in group}),
                pages=sorted({f.page for f in group}),
                raw_texts=deduped_texts,
                image_paths=sorted({p for f in group for p in f.image_paths}),
                conflict_note=conflict_note,
            )
        )

    # sort: high severity first, then by area
    merged.sort(key=lambda m: (-SEV_RANK[m.severity], m.area))
    return merged
