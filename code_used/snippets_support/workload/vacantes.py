"""
vacantes.py
-----------
Processes raw job postings (vacantes) from an Excel file,
filters by a given month/year, and exports the result as a
compressed Parquet file alongside a record-count text file.

Environment variables (injected by Kestra):
    MONTH   – integer month of interest (1-12)
    YEAR    – integer year of interest  (e.g. 2026)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE_FILE = "job_posting"
SHEET_NAME = "Vacantes"

COLUMNS_TO_DROP = ["empre_reg"]

COLUMNS_TO_KEEP = [
    "código_proceso",
    "nombre_vacante",
    "cargo",
    "#_postulados",
    "empresa",
    "tipodocumentoempresa",
    "numerodocumentoempresa",
    "fecha_registro",
    "fecha_vencimiento",
    "estado_actual",
    "tipo_de_vacante",
    "puestos_de_trabajo",
    "tipo_de_contrato",
    "agente_aprobó",
    "mes",
    "año",
    "punto_atención",
    "país",
]

DATE_COLUMNS = ["fecha_registro", "fecha_vencimiento"]

# Excel's epoch anchor
EXCEL_BASE_DATE = datetime(1899, 12, 30)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_excel(path: str, sheet: str) -> pd.DataFrame:
    """Read the raw Excel sheet into a DataFrame."""
    log.info("Reading Excel file '%s', sheet '%s'", path, sheet)
    return pd.read_excel(path, sheet_name=sheet)


def export_parquet(df: pd.DataFrame, path: str) -> None:
    """Persist the DataFrame as a zstd-compressed Parquet file."""
    log.info("Exporting %d rows to '%s'", len(df), path)
    df.to_parquet(path, compression="zstd")


def write_record_count(count: int, path: str = "record_count.txt") -> None:
    """Write the record count to a plain-text file for downstream tasks."""
    with open(path, "w") as fh:
        fh.write(str(count))
    log.info("Record count (%d) written to '%s'", count, path)


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------
def normalise_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names and replace spaces with underscores."""
    df.columns = df.columns.str.lower().str.replace(" ", "_", regex=False)
    return df


def drop_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Drop columns that exist in *cols*, silently ignoring missing ones."""
    existing = [c for c in cols if c in df.columns]
    return df.drop(columns=existing)


def select_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Return only the subset of *cols* that are present in the DataFrame."""
    available = [c for c in cols if c in df.columns]
    missing = set(cols) - set(available)
    if missing:
        log.warning("Expected columns not found and will be skipped: %s", missing)
    return df[available]


# ---------------------------------------------------------------------------
# Data cleaning
# ---------------------------------------------------------------------------
def clean_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every object-dtype column:
    - Replace the literal string 'nan' and empty strings with pd.NA.
    - Cast to str, strip whitespace, and lowercase.
    """
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].replace({"nan": pd.NA, "": pd.NA})
        df[col] = (
            df[col]
            .astype(str)
            .str.strip()
            .str.lower()
            .replace("nan", pd.NA)   # catch any 'nan' introduced by .astype(str)
        )
    return df


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def _parse_single_date(date_str: str | float | None) -> datetime | pd.NaT:
    """
    Parse a single date value that may be:
      1. An Excel serial number (float/int stored as string, e.g. '45679').
      2. A slash-delimited string with optional AM/PM time (DD/MM/YYYY …).
      3. A dash-delimited string in DD-MM-YYYY format.

    Returns pd.NaT for any value that cannot be parsed.
    """
    if pd.isna(date_str) or str(date_str).strip() in ("", "nat", "none"):
        return pd.NaT

    date_str = str(date_str).strip()

    # --- 1. Excel serial number ---
    if "/" not in date_str and "-" not in date_str:
        try:
            serial = float(date_str)
            if serial > 0:
                return EXCEL_BASE_DATE + timedelta(days=serial)
        except ValueError:
            pass

    # --- 2. Slash-delimited (DD/MM/YYYY [HH:MM:SS a/p. m.]) ---
    if "/" in date_str:
        try:
            cleaned = (
                date_str.replace(" p. m.", " PM")
                        .replace(" a. m.", " AM")
                        .replace(" p.m.", " PM")
                        .replace(" a.m.", " AM")
            )
            if "PM" in cleaned or "AM" in cleaned:
                return pd.to_datetime(cleaned, format="%d/%m/%Y %I:%M:%S %p")
            day, month, year = cleaned.split()[0].split("/")
            return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass

    # --- 3. Dash-delimited (DD-MM-YYYY) ---
    parts = date_str.split("-")
    if len(parts) == 3:
        try:
            if len(parts[0]) <= 2 and int(parts[0]) <= 31:
                day, month, year = parts
                return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass

    log.debug("Unable to parse date value: '%s'", date_str)
    return pd.NaT


def parse_date_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Apply _parse_single_date to each column in *columns* and floor to day."""
    for col in columns:
        if col not in df.columns:
            continue
        df[col] = df[col].fillna("").apply(_parse_single_date)
        df[col] = df[col].dt.floor("D")
    return df


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def filter_by_period(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """Keep only rows where 'mes' == *month* and 'año' == *year*."""
    mask = (df["mes"] == month) & (df["año"] == year)
    filtered = df[mask].copy()
    log.info(
        "Filtered to month=%d / year=%d: %d → %d rows",
        month, year, len(df), len(filtered),
    )
    return filtered


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------
def run_pipeline(month: int, year: int) -> None:
    """End-to-end processing: load → clean → filter → export."""
    # 1. Load
    df = load_excel(SOURCE_FILE, SHEET_NAME)

    # 2. Normalise shape
    df = normalise_column_names(df)
    df = drop_columns(df, COLUMNS_TO_DROP)

    # 3. Clean strings before anything else
    df = clean_string_columns(df)

    # 4. Parse date columns
    df = parse_date_columns(df, DATE_COLUMNS)

    # 5. Select only the columns we need
    df = select_columns(df, COLUMNS_TO_KEEP)

    # 6. Filter to the requested period
    df = filter_by_period(df, month, year)

    # 7. Export
    output_parquet = f"vacantes_{year}_{month}.parquet"
    export_parquet(df, output_parquet)

    record_count = len(df)
    write_record_count(record_count)
    log.info(
        "Pipeline complete. %d records written for %d/%d.",
        record_count, month, year,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    month = int(os.getenv("MONTH", "1"))
    year = int(os.getenv("YEAR", "2026"))

    log.info("Starting vacantes pipeline for month=%d / year=%d", month, year)
    run_pipeline(month, year)