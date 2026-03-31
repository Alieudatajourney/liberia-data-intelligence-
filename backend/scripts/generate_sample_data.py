"""
backend/scripts/generate_sample_data.py
=========================================
Generates realistic sample Excel files in data/raw/ for development and testing.

Each file intentionally has:
  - Different column names (no consistency across files)
  - Multiple sheets
  - Some messy values (blanks, N/A, mixed types)
  - Varying structures

This mirrors what real LISGIS datasets look like and lets you run
the ingestion pipeline without needing real source files.

Run:
    python backend/scripts/generate_sample_data.py
"""

import sys
import logging
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
BACKEND_DIR  = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd
import numpy as np
from app.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

RAW_DIR = PROJECT_ROOT / "data" / "raw"

COUNTIES = [
    "Montserrado", "Nimba", "Bong", "Lofa", "Grand Bassa",
    "Margibi", "Grand Gedeh", "Maryland", "Sinoe", "Bomi",
    "Grand Cape Mount", "Gbarpolu", "Grand Kru", "Rivercess", "River Gee",
]


# ---------------------------------------------------------------------------
# File 1: LISGIS_Census_2008.xlsx
# Two sheets: Population, Households
# Columns: County Name, Year, Total Population, Male Population, Female Population
# ---------------------------------------------------------------------------
def create_census_2008() -> Path:
    path = RAW_DIR / "LISGIS_Census_2008.xlsx"

    # Sheet 1: Population
    population_data = []
    for county in COUNTIES:
        population_data.append({
            "County Name":        county,
            "Year":               2008,
            "Total Population":   round(np.random.uniform(50_000, 1_500_000)),
            "Male Population":    round(np.random.uniform(25_000, 750_000)),
            "Female Population":  round(np.random.uniform(25_000, 750_000)),
            "Notes":              np.random.choice(["", "", "", "Estimate", "N/A"]),
        })
    df_population = pd.DataFrame(population_data)

    # Sheet 2: Households
    household_data = []
    for county in COUNTIES:
        household_data.append({
            "County Name":        county,
            "Year":               2008,
            "Total Households":   round(np.random.uniform(10_000, 300_000)),
            "Average HH Size":    round(np.random.uniform(3.5, 6.5), 1),
            # Deliberately different column name from Sheet 1
            "Urban HH (%)":       round(np.random.uniform(10, 80), 1),
        })
    df_households = pd.DataFrame(household_data)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_population.to_excel(writer, sheet_name="Population",  index=False)
        df_households.to_excel(writer, sheet_name="Households", index=False)

    logger.info("Created: %s (2 sheets, %d rows each)", path.name, len(COUNTIES))
    return path


# ---------------------------------------------------------------------------
# File 2: Employment_Survey_2016.xlsx
# One sheet: Employment
# Deliberately different column names from File 1
# ---------------------------------------------------------------------------
def create_employment_2016() -> Path:
    path = RAW_DIR / "Employment_Survey_2016.xlsx"

    rows = []
    for county in COUNTIES:
        for gender in ["Male", "Female"]:
            rows.append({
                # Note: "District" instead of "County Name" — intentionally inconsistent
                "District":              county,
                "Survey Year":           2016,
                "Gender":                gender,
                "Employment Rate (%)":   round(np.random.uniform(30, 75), 1),
                "Unemployment Rate (%)": round(np.random.uniform(5, 40), 1),
                # Some intentionally blank values
                "Youth Employment (%)":  np.random.choice(
                    [round(np.random.uniform(15, 60), 1), None, None, "N/A"]
                ),
            })

    df = pd.DataFrame(rows)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Employment Data", index=False)

    logger.info("Created: %s (1 sheet, %d rows)", path.name, len(rows))
    return path


# ---------------------------------------------------------------------------
# File 3: Agriculture-Data-2019.xlsx  (uses hyphens — tests name derivation)
# Two sheets: Crop Production, Land Use
# ---------------------------------------------------------------------------
def create_agriculture_2019() -> Path:
    path = RAW_DIR / "Agriculture-Data-2019.xlsx"

    crops = ["Rice", "Cassava", "Rubber", "Palm Oil", "Cocoa", "Coffee"]

    # Sheet 1: Crop Production
    crop_rows = []
    for county in COUNTIES:
        for crop in crops:
            crop_rows.append({
                "County":            county,
                "Crop Type":         crop,
                "Year":              2019,
                "Production (MT)":   round(np.random.uniform(100, 50_000)),
                "Area Planted (Ha)": round(np.random.uniform(50, 20_000)),
                "Yield (MT/Ha)":     round(np.random.uniform(0.5, 4.5), 2),
            })
    df_crops = pd.DataFrame(crop_rows)

    # Sheet 2: Land Use (completely different columns from Sheet 1)
    land_rows = []
    for county in COUNTIES:
        land_rows.append({
            "County":              county,
            "Reporting Year":      2019,         # different column name for year
            "Forest Cover (%)":    round(np.random.uniform(20, 80), 1),
            "Agricultural Land (%)": round(np.random.uniform(10, 50), 1),
            "Protected Area (%)":  round(np.random.uniform(0, 30), 1),
        })
    df_land = pd.DataFrame(land_rows)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_crops.to_excel(writer, sheet_name="Crop Production", index=False)
        df_land.to_excel(writer,  sheet_name="Land Use",        index=False)

    logger.info("Created: %s (2 sheets)", path.name)
    return path


# ---------------------------------------------------------------------------
# File 4: health_indicators_2020.xlsx (lowercase — tests case handling)
# One sheet with some blank rows and a merged-style header row
# ---------------------------------------------------------------------------
def create_health_2020() -> Path:
    path = RAW_DIR / "health_indicators_2020.xlsx"

    rows = []
    for county in COUNTIES:
        rows.append({
            # Another completely different set of column names
            "location":              county,
            "reference_year":        2020,
            "under5_mortality_rate": round(np.random.uniform(40, 180), 1),
            "maternal_mortality":    round(np.random.uniform(100, 1200), 0),
            "skilled_birth_attendant_pct": round(np.random.uniform(20, 95), 1),
            "malaria_prevalence_pct": round(np.random.uniform(10, 70), 1),
            "stunting_rate_pct":     round(np.random.uniform(20, 65), 1),
            "source":                "Ministry of Health / DHS 2020",
        })

    df = pd.DataFrame(rows)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Health Indicators", index=False)

    logger.info("Created: %s (1 sheet, %d rows)", path.name, len(rows))
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Writing sample Excel files to: %s", RAW_DIR)

    created = [
        create_census_2008(),
        create_employment_2016(),
        create_agriculture_2019(),
        create_health_2020(),
    ]

    print("\n" + "─" * 50)
    print("  SAMPLE DATA GENERATED")
    print("─" * 50)
    for p in created:
        print(f"  {p.name}")
    print("─" * 50)
    print(f"\n  Now run the ingestion pipeline:")
    print(f"  python backend/scripts/run_ingestion.py\n")


if __name__ == "__main__":
    main()
