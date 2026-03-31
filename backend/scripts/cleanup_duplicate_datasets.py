"""
backend/scripts/cleanup_duplicate_datasets.py
==============================================
Removes the old "...Liberia" duplicate datasets (IDs 1-5) that were
created by an earlier ingestion run. The newer, clean-named datasets
(IDs 6-10) are kept.

Deleting a Dataset cascades to its Indicators and Observations.

Run via Railway shell:
    python backend/scripts/cleanup_duplicate_datasets.py
"""
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.models import Dataset  # noqa: F401 — registers ORM

TO_DELETE = [
    "Health Facilities Liberia",
    "Disease Burden Liberia",
    "Water and Sanitation Liberia",
    "Vulnerability Index Liberia",
    "Composite Health Risk Liberia",
]

db = SessionLocal()
try:
    deleted = 0
    for name in TO_DELETE:
        ds = db.query(Dataset).filter_by(name=name).first()
        if ds:
            db.delete(ds)
            deleted += 1
            print(f"  Deleted: {name!r} (id={ds.id})")
        else:
            print(f"  Not found (already gone?): {name!r}")
    db.commit()
    print(f"\nDone. {deleted} dataset(s) removed (indicators + observations cascade-deleted).")
finally:
    db.close()
