"""
ETL script for processing CV (Hoja de Vida) registration data.

The script is structured as a set of pure, testable functions.
The main() function at the bottom orchestrates the full pipeline
and is the only entry point that reads environment variables or
writes files to disk.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os


# ---------------------------------------------------------------------------
# 1. INGESTION
# ---------------------------------------------------------------------------

def load_excel(filepath: str, sheet_name: str = "BD_Acumulado-2024-2026") -> pd.DataFrame:
    """
    Read the raw Excel file and return a DataFrame with normalised column names.

    Normalisation:
      - All column names are lowercased.
      - Spaces are replaced with underscores.
      - Completely unnamed columns (Unnamed: ...) are dropped.
      - Rows where every cell is NaN are dropped.

    Args:
        filepath:   Path to the .xlsx file (or Kestra virtual path 'excel_file').
        sheet_name: Name of the Excel sheet to read.

    Returns:
        pd.DataFrame with normalised columns, unnamed columns removed,
        and fully-empty rows removed.
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df.columns = df.columns.str.lower().str.replace(" ", "_")
    df = df.loc[:, ~df.columns.str.contains("^unnamed", case=False, na=False)]
    df = df.dropna(axis=0, how="all")
    return df


# ---------------------------------------------------------------------------
# 2. CLEANING
# ---------------------------------------------------------------------------

def clean_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip leading/trailing whitespace from a predefined set of string columns.

    These columns are known to arrive from Excel with extra spaces or mixed
    types (e.g. Excel numbers stored as text). Converting to str first
    guarantees the .strip() call never raises.

    número_documento requires special handling: when any row in the column
    is null, pandas reads the entire column as float64 (e.g. 111111.0).
    A plain astype(str) then produces "111111.0" instead of "111111",
    breaking all downstream string comparisons and uniqueness logic.
    The fix converts via Int64 first (which preserves nulls as <NA>),
    then to str, then replaces the "<NA>" sentinel back to pd.NA so that
    filter_valid_records() can correctly identify missing document numbers.

    Args:
        df: Raw DataFrame from load_excel().

    Returns:
        DataFrame with the target columns cast to str and stripped.
    """
    # --- número_documento: integer-safe conversion to avoid "111111.0" ---
    if "número_documento" in df.columns:
        df["número_documento"] = (
            pd.to_numeric(df["número_documento"], errors="coerce")
            .astype("Int64")       # nullable integer — preserves NaN as <NA>
            .astype(str)           # "111111", not "111111.0"
            .replace("<NA>", pd.NA)  # restore proper null for filter_valid_records
        )

    # --- all other string columns: plain strip ---
    str_cols = [
        "teléfono", "título_homologado", "ciudad_de_residencia", "email",
        "programa_de_gobierno", "fecha_actualización", "%_hoja_vida",
        "fecha_cambio_prestador", "vereda/localidad/centro_poblado", "celular",
    ]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df


def filter_valid_records(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split the dataset into valid and invalid records.

    A record is considered *invalid* when either tipo_documento OR
    número_documento is null. These rows cannot be reliably identified
    in the database and are separated for manual review.

    Args:
        df: Cleaned DataFrame.

    Returns:
        (valid, invalid) — two DataFrames. 'valid' contains rows that
        have both document type and document number. 'invalid' contains
        the rest.
    """
    mask_no_td = df["tipo_documento"].isnull()
    mask_no_nd = df["número_documento"].isnull()
    invalid_idx = set(df[mask_no_td].index) | set(df[mask_no_nd].index)

    invalid = df[df.index.isin(invalid_idx)].copy()
    valid = df[~df.index.isin(invalid_idx)].copy()
    return valid, invalid


def filter_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Keep only rows whose 'año' column matches the requested year.

    Args:
        df:   Valid records DataFrame.
        year: Integer year (e.g. 2025).

    Returns:
        Filtered DataFrame.
    """
    return df[df["año"] == year].copy()


def replace_string_nan(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace the literal string 'nan' with pd.NA across all columns.

    When Excel cells that were originally empty are cast to str via
    astype(str), they become the string 'nan' rather than a proper null.
    This function corrects that.

    Args:
        df: DataFrame that may contain 'nan' strings.

    Returns:
        DataFrame with 'nan' strings replaced by pd.NA.
    """
    for col in df.columns:
        df[col] = df[col].replace("nan", pd.NA)
    return df


def normalise_gender(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise the 'género' column so that lowercase 'm'/'f' become
    uppercase 'M'/'F'.

    Args:
        df: DataFrame with a 'género' column.

    Returns:
        DataFrame with normalised gender values.
    """
    if "género" in df.columns:
        df["género"] = df["género"].replace({"m": "M", "f": "F"})
    return df


# ---------------------------------------------------------------------------
# 3. DATE PARSING
# ---------------------------------------------------------------------------

def parse_dates(date_str) -> pd.Timestamp:
    """
    Parse a single date value that may arrive in several formats:

      1. Excel serial number  (e.g. "45679" or "45679.0")
      2. DD/MM/YYYY [HH:MM:SS [a. m.|p. m.]]
      3. DD-MM-YYYY

    The function is designed to be used with DataFrame.apply().

    Args:
        date_str: Raw cell value (str, float, int, or NaN).

    Returns:
        pd.Timestamp if parsing succeeds, pd.NaT otherwise.
    """
    if pd.isna(date_str) or str(date_str).strip() == "":
        return pd.NaT

    date_str = str(date_str).strip()

    # --- Case 1: Excel serial number ---
    try:
        excel_num = float(date_str)
        if excel_num > 0 and "/" not in date_str and "-" not in date_str:
            base_date = datetime(1899, 12, 30)
            return base_date + timedelta(days=excel_num)
    except ValueError:
        pass

    # --- Case 2: Slash-delimited (DD/MM/YYYY ...) ---
    if "/" in date_str:
        try:
            cleaned = date_str.replace(" p. m.", " PM").replace(" a. m.", " AM")
            if "PM" in cleaned or "AM" in cleaned:
                return pd.to_datetime(cleaned, format="%d/%m/%Y %I:%M:%S %p")
            parts = date_str.split()[0].split("/")
            if len(parts) == 3:
                day, month, year = parts
                return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass

    # --- Case 3: Dash-delimited (DD-MM-YYYY) ---
    if "-" in date_str and len(date_str.split("-")) == 3:
        try:
            parts = date_str.split("-")
            if len(parts[0]) <= 2 and int(parts[0]) <= 31:
                day, month, year = parts
                return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass

    return pd.NaT


def parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply parse_dates() to the three source date columns and derive
    'fecha_accion' (the latest of the three) and 'mes' (action month).

    Side effects on df (all additive or in-place replacements):
      - 'fecha_registro', 'fecha_actualización', 'fecha_cambio_prestador'
        are converted to pd.Timestamp.
      - 'fecha_accion' is added as the row-wise max of the three dates,
        floored to midnight.
      - 'mes' column is dropped and re-derived from 'fecha_accion'.

    Args:
        df: DataFrame with the three raw date columns present.

    Returns:
        DataFrame with parsed dates and derived columns.
    """
    date_cols = ["fecha_registro", "fecha_actualización", "fecha_cambio_prestador"]
    for col in date_cols:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).apply(parse_dates)

    df["fecha_accion"] = df[date_cols].max(axis=1)
    df["fecha_accion"] = df["fecha_accion"].dt.floor("D")

    if "mes" in df.columns:
        df = df.drop("mes", axis=1)
    df["mes"] = df["fecha_accion"].dt.month

    return df


# ---------------------------------------------------------------------------
# 4. POPULATION CLASSIFICATION
# ---------------------------------------------------------------------------

def classify_ethnic_groups(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive the 'grupos_etnicos' column from 'condiciones_especiales'.

    Four groups are detected via regex on the lowercased text:
      - Afrodescendiente  (negr|afro|mulat|palen)
      - Raizal y/o Isleño (raiz)
      - Indígenas         (indí)
      - Gitano            (git)

    A record may belong to multiple groups; the result is stored as a
    Python list. Records matching none of the patterns receive np.nan.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'grupos_etnicos' column added.
    """
    df["condiciones_especiales"] = (
        df["condiciones_especiales"].astype(str).str.lower().fillna("")
    )

    patterns = {
        "Afrodescendiente":  r"negr|afro|mulat|palen",
        "Raizal y/o Isleño": r"raiz",
        "Indígenas":         r"indí",
        "Gitano":            r"git",
    }

    def _classify(text: str) -> list | float:
        groups = [label for label, pattern in patterns.items()
                  if pd.Series([text]).str.contains(pattern, regex=True).iloc[0]]
        return groups if groups else np.nan

    df["grupos_etnicos"] = df["condiciones_especiales"].apply(_classify)
    return df


def classify_vca(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag victims of the armed conflict ('VCA').

    A record is flagged when:
      - 'programa_de_gobierno' contains 'armado', OR
      - 'condiciones_especiales' contains 'vca' or 'v.c.a'.

    Args:
        df: DataFrame with 'programa_de_gobierno' and
            'condiciones_especiales' columns.

    Returns:
        DataFrame with 'vca' column added ('VCA' or NaN).
    """
    df["programa_de_gobierno"] = df["programa_de_gobierno"].fillna("").astype(str)
    df["vca"] = pd.Series(dtype="object")

    mask = (
        df["programa_de_gobierno"].str.contains("armado", na=False) |
        df["condiciones_especiales"].str.contains(r"vca|v\.c\.a", na=False)
    )
    df.loc[mask, "vca"] = "VCA"
    return df


def classify_disability(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classify the type of disability from 'condiciones_especiales'.

    Patterns are matched in order; the **first** match wins. Records with
    no matching pattern receive np.nan.

    The 'capacidad' catch-all pattern is intentionally placed last so
    that more specific labels (Física, Visual, etc.) take priority.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'discapacidad' column added.
    """
    df["discapacidad"] = pd.Series([np.nan] * len(df), dtype="object")

    patterns = {
        r"ognitiv|telect": "Cognitiva o Intelectual",
        r"[ií]sic":        "Física",
        r"visual":         "Visual",
        r"auditiva":       "Auditiva",
        r"múltiple":       "Múltiple",
        r"sordoceguera":   "Sordoceguera",
        r"psicosocial":    "Psicosocial",
        r"capacidad":      "Discapacidad",
    }

    for pattern, label in patterns.items():
        # Only apply label to rows that have NOT been labelled yet
        unclassified = df["discapacidad"].isna()
        mask = unclassified & df["condiciones_especiales"].str.contains(
            pattern, case=False, na=False
        )
        df.loc[mask, "discapacidad"] = label

    return df


def classify_migrants(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag migrants and returnees ('Migrante o Retornado').

    A record is flagged when:
      - 'condiciones_especiales' contains 'migr' or 'retor', OR
      - 'tipo_documento' contains 'acional', 'ermiso', or 'tranje'
        (fragments of 'Nacional', 'Permiso', 'Extranjero').

    Args:
        df: DataFrame with 'condiciones_especiales' and
            'tipo_documento' columns.

    Returns:
        DataFrame with 'migrante' column added.
    """
    df["migrante"] = ""
    mask = (
        df["condiciones_especiales"].str.contains(r"migr|retor", na=False) |
        df["tipo_documento"].str.contains(r"acional|ermiso|tranje", na=False)
    )
    df.loc[mask, "migrante"] = "Migrante o Retornado"
    df["migrante"] = df["migrante"].replace("", np.nan)
    return df


def classify_vvg(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag victims of gender-based violence ('vvg').

    A record is flagged when 'condiciones_especiales' contains
    'viole' or 'vvg'.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'vvg' column added.
    """
    df["vvg"] = ""
    mask = df["condiciones_especiales"].str.contains(r"viole|vvg", na=False)
    df.loc[mask, "vvg"] = "vvg"
    df["vvg"] = df["vvg"].replace("", np.nan)
    return df


def classify_reintegrated(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag people in a reintegration/reincorporation programme.

    A record is flagged when 'condiciones_especiales' contains 'rein'.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'reincorporados' column added.
    """
    df["reincorporados"] = ""
    mask = df["condiciones_especiales"].str.contains("rein", na=False)
    df.loc[mask, "reincorporados"] = "reincorporados"
    df["reincorporados"] = df["reincorporados"].replace("", np.nan)
    return df


def run_all_classifications(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convenience wrapper: run all five population-classification steps
    in the correct order.

    Args:
        df: Cleaned and date-parsed DataFrame.

    Returns:
        DataFrame with all classification columns added.
    """
    df = classify_ethnic_groups(df)
    df = classify_vca(df)
    df = classify_disability(df)
    df = classify_migrants(df)
    df = classify_vvg(df)
    df = classify_reintegrated(df)
    return df


# ---------------------------------------------------------------------------
# 5. FILTERING & EXPORT
# ---------------------------------------------------------------------------

def filter_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """
    Keep only rows whose 'fecha_accion' falls in the requested month/year.

    This is the final slice that produces the monthly parquet file.

    Args:
        df:    Fully transformed DataFrame.
        month: Integer month (1–12).
        year:  Integer year (e.g. 2025).

    Returns:
        Filtered DataFrame.
    """
    dt = pd.to_datetime(df["fecha_accion"])
    mask = (dt.dt.month == month) & (dt.dt.year == year)
    return df[mask].copy()


def export_parquet(df: pd.DataFrame, month: int, year: int) -> str:
    """
    Export the monthly DataFrame to a compressed parquet file.

    Filename pattern: registro_hv_<year>_<month>.parquet

    Args:
        df:    Monthly DataFrame to export.
        month: Integer month used in the filename.
        year:  Integer year used in the filename.

    Returns:
        The filename that was written.
    """
    filename = f"registro_hv_{year}_{month}.parquet"
    df.to_parquet(filename, compression="zstd")
    return filename


def write_record_count(count: int, filepath: str = "record_count.txt") -> None:
    """
    Write the number of processed records to a plain-text file.

    Kestra reads this file via outputFiles to surface the count in the
    email notification task.

    Args:
        count:    Number of records.
        filepath: Destination path (default 'record_count.txt').
    """
    with open(filepath, "w") as f:
        f.write(str(count))


# ---------------------------------------------------------------------------
# 6. REPORTING (optional — prints to stdout captured by Kestra logs)
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, month: int, year: int) -> None:
    """
    Print a human-readable summary of monthly registration counts.

    Mirrors the print statements from the original script but now
    operates on an already-filtered DataFrame.

    Args:
        df:    Monthly DataFrame.
        month: Month being summarised.
        year:  Year being summarised.
    """
    def _count(mask):
        return int(mask.sum())

    dt = pd.to_datetime(df["fecha_accion"])
    in_month = (dt.dt.month == month) & (dt.dt.year == year)

    for canal, tipo, label in [
        ("Autoregistro", "Registro_nuevo", "autoregistro nuevo"),
        ("Agencia",      "Registro_nuevo", "registro nuevo"),
        ("Agencia",      "Actualizacion",  "actualizado"),
    ]:
        fr = in_month & (df["canal_de_registro"] == canal) & (df["tipo_registro"] == tipo)
        print(f"\n--- HV {label} mes {month}/{year} ---")
        print(f"  Hombres:   {_count(fr & (df['género'] == 'M'))}")
        print(f"  Mujeres:   {_count(fr & (df['género'] == 'F'))}")
        print(f"  PCD:       {_count(fr & df['discapacidad'].notna())}")
        print(f"  VCA:       {_count(fr & df['vca'].notna())}")
        print(f"  VVG:       {_count(fr & df['vvg'].notna())}")
        print(f"  Migrantes: {_count(fr & df['migrante'].notna())}")
        print(f"  Étnicos:   {_count(fr & df['grupos_etnicos'].notna())}")
        print(f"  Reinc.:    {_count(fr & df['reincorporados'].notna())}")
        print(f"  ≥60 años:  {_count(fr & (df['edad'] >= 60))}")
        print(f"  29-59:     {_count(fr & (df['edad'] >= 29) & (df['edad'] < 60))}")
        print(f"  ≤28 años:  {_count(fr & (df['edad'] <= 28))}")


# ---------------------------------------------------------------------------
# 7. MAIN PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_pipeline(filepath: str, month: int, year: int) -> pd.DataFrame:
    """
    Execute the full ETL pipeline and return the monthly DataFrame.

    This function is called both by main() (for production) and by
    integration tests (with a fixture file).

    Steps:
        1. load_excel
        2. clean_string_columns
        3. filter_valid_records  (invalid rows are discarded here)
        4. filter_by_year
        5. replace_string_nan
        6. normalise_gender
        7. parse_date_columns
        8. run_all_classifications
        9. filter_by_month

    Args:
        filepath: Path to the source Excel file.
        month:    Target month (1–12).
        year:     Target year.

    Returns:
        Processed monthly DataFrame ready for export.
    """
    df = load_excel(filepath)
    df = clean_string_columns(df)
    df, _ = filter_valid_records(df)
    df = filter_by_year(df, year)
    df = replace_string_nan(df)
    df = normalise_gender(df)
    df = parse_date_columns(df)
    df = run_all_classifications(df)
    df = filter_by_month(df, month, year)
    return df


def main():
    """
    Entry point when the script is run directly (or by Kestra).

    Reads MONTH and YEAR from environment variables, executes the full
    pipeline against the 'excel_file' virtual path injected by Kestra,
    writes the parquet output and record_count.txt, and prints a summary.
    """
    month = int(os.getenv("MONTH"))
    year  = int(os.getenv("YEAR"))

    df = run_pipeline("excel_file", month, year)

    print_summary(df, month, year)

    filename = export_parquet(df, month, year)
    count = len(df)
    write_record_count(count)

    print(f"\nNumber of valid records processed for {month}/{year}: {count}")
    print(f"Output written to: {filename}")


if __name__ == "__main__":
    main()