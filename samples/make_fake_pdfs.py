"""Generate tiny fake PDFs for a smoke test (no network required)."""
import fitz
from pathlib import Path

OUT = Path(__file__).parent

def make(path: Path, title: str, paragraphs: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 50
    page.insert_text((50, y), title, fontsize=16); y += 30
    for p in paragraphs:
        page.insert_textbox(
            fitz.Rect(50, y, 550, y + 120),
            p,
            fontsize=11,
        )
        y += 130
    doc.save(path)
    doc.close()

make(
    OUT / "inspection_sample.pdf",
    "Inspection Report — 12 Example St",
    [
        "Roof Void: Termite damage observed to roof trusses in the north wing. "
        "Cracked roof tiles visible near the ridge may allow water penetration.",
        "Eaves / Flashings: Moisture staining around the sewer vent pipe suggests previous leaks.",
        "Laundry: Vermin protection cap is missing from the floor waste pipe. "
        "Hot water overflow should be diverted away from building foundations.",
        "Ensuite: Cracked tiles noted in the shower floor; general wear to cabinetry.",
    ],
)

make(
    OUT / "thermal_sample.pdf",
    "Thermal Imaging Report — 12 Example St",
    [
        "Roof Void: Thermal anomaly consistent with moisture behind ceiling lining near the ridge. "
        "Matches visual report of cracked roof tiles.",
        "Bedroom: Hot spot detected on wall near power outlet — possible electrical overheat. Urgent.",
        "Laundry: No thermal anomaly detected near floor waste area.",
    ],
)
print("wrote", list(OUT.glob("*.pdf")))
