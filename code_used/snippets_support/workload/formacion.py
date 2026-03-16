# formacion.py
"""
Formacion pipeline — ingestion and transformation module.

Entry point (called by Kestra):
    python formacion.py

Reads two env vars injected by Kestra:
    GCS_BUCKET   full bucket + prefix, e.g.
                 "operations-raw-data_public-employment-pulse/formacion"
    MONTH        integer month of interest (used to stamp output parquet)
    YEAR         integer year  of interest (used to stamp output parquet)

Pipeline steps
--------------
1. ingest_from_gcs()      List the bucket prefix, detect the sheet in each
                          file, download + concat into a single raw DataFrame,
                          then restrict to the 27 columns in SELECT_COLUMNS.
2. normalize_column_names()  Clean column headers.
3. rename with RENAME_DICT   Map long/special column names to short keys.
                             Note: "indique_el_curso_al_que_desea_inscribirse" (no
                             trailing underscore) maps to "curso_inscrito" only.
4. filter_valid_records()    Drop rows missing numero_de_documento or nombres.
5. cast_datetime_columns()   Parse date columns.
6. clean_edad()              Extract numeric age, derive rango_de_edad.
7. lowercase_string_columns() Lowercase all object columns.
8. clean_genero()            Map full gender labels to single characters.
9. add_population_flags()    Derive VVG, VCA, migrante, étnico, discapacidad,
                             reincorporados columns.
10. Write output parquet + record_count.txt for Kestra to consume.
"""

import os
import io
import pandas as pd
import numpy as np
import gcsfs

# ── Constants ────────────────────────────────────────────────────────────────

# Sheet-name lookup: maps a substring of the Excel filename (lowercase) to the sheet name inside that file.
# Add new entries here whenever a new course file is onboarded.
SHEET_MAP: dict[str, str] = {
    "atencion al cliente":  "Matriculados ATENCION MEDIOS DI",
    "bisuteria":            "Hoja1",
    "cocteleria":           "COCTELERIA BASICA - MAYOR DE 18",
    "alimentos":            "Hoja1",
}

# Fallback: if no SHEET_MAP key matches the filename, read the first sheet.
DEFAULT_SHEET_INDEX = 0

RENAME_DICT: dict[str, str] = {
    # ── Long / special-character headers ─────────────────────────────────────
    "para_prestarte_un_mejor_servicio_y_cumplir_nuestras_funciones,_la_alcaldía_distrital_de_barranquilla_tratará_tus_datos_personales_conforme_a_la_ley_1581_de_2012._conoce_tus_derechos_y_cómo_ejercerlos_en_nuestra_política_de_tratamiento_de_datos_en": "autorizacion_datos",
    "¿ha_realizado_cursos_en_el_centro_de_oportunidades?": "cursos_previos_co",
    "dirección_de_residencia:_(ejemplo:_k_10_47b_133_ó_c_23_20_30)": "direccion_residencia",
    "correo_electrónico_@": "email",
    "último_nivel_de_estudio_aprobado": "formacion",
    "¿tiene_alguna_discapacidad?": "tipo_discapacidad",
    "adjunte_fotocopia_de_su_cédula": "anexo_cedula",
    "indique_el_curso_al_que_desea_inscribirse": "curso_inscrito",
    # ── Accented identity columns → clean unaccented DB names ────────────────
    # normalize_column_names preserves accents; map them here so the parquet
    # always lands with the exact names the DB schema and column_mapping expect.
    # NOTE: "género" and "tipo_de_población" are intentionally NOT renamed here
    # because clean_genero() and flag_population() reference them by their
    # accented names. They are stripped of accents at the DB loading step.
    "número_de_documento":  "numero_de_documento",
    "número_documento":     "numero_de_documento",   # alternate header spelling
    "nombre_completo":      "nombres",               
    "teléfono":             "telefono",
}

# Exact set of columns to keep after normalize_column_names + RENAME_DICT.
SELECT_COLUMNS: list[str] = [
    "adjudicado",
    "autorizacion_datos",         # renamed from long privacy-policy header
    "fecha_de_registro",
    "nombres",                    # renamed from "nombre_completo"
    "tipo_de_documento",
    "numero_de_documento",        # renamed from "número_de_documento"
    "asistencia",
    "telefono",                   # renamed from "teléfono"
    "cursos_previos_co",          # renamed from "¿ha_realizado_cursos_en_...?"
    "sise",
    "país_de_nacimiento",
    "departamento_de_nacimiento",
    "ciudad_de_nacimiento",
    "fecha_de_nacimiento",
    "edad",
    "género",
    "direccion_residencia",       # renamed from "dirección_de_residencia:_..."
    "barrio",
    "municipio_de_residencia",
    "email",                      # renamed from "correo_electrónico_@"
    "celular",
    "celular_adicional",
    "formacion",                  # renamed from "último_nivel_de_estudio_aprobado"
    "tipo_de_población",
    "tipo_discapacidad",          # renamed from "¿tiene_alguna_discapacidad?"
    "curso_inscrito",             # renamed from "indique_el_curso_al_que_desea_inscribirse"
    "anexo_cedula",               # renamed from "adjunte_fotocopia_de_su_cédula"
]

DATETIME_COLUMNS: list[str] = ["fecha_de_nacimiento", "fecha_de_registro"]

GENERO_MAPPING: dict[str, str] = {
    "masculino": "m",
    "femenino":  "f",
    "intersexual": "i",
}

# Ordered dict: specific patterns first so they win over the catch-all
DISCAPACIDAD_PATTERNS: dict[str, str] = {
    r"ognitiv|telect":  "Cognitiva o Intelectual",
    r"[ií]sic":         "Física",
    r"visual":          "Visual",
    r"auditiva":        "Auditiva",
    r"múltiple":        "Múltiple",
    r"sordoceguera":    "Sordoceguera",
    r"psicosocial":     "Psicosocial",
    r"capacidad":       "Discapacidad",   
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def resolve_sheet(filename: str, xl: pd.ExcelFile) -> str:
    """
    Return the sheet name to read from *xl* based on the filename.

    Priority:
      1. First SHEET_MAP key whose substring appears in the filename.
      2. The sheet at DEFAULT_SHEET_INDEX if no key matches.
    """
    name_lower = filename.lower()
    for keyword, sheet_name in SHEET_MAP.items():
        if keyword in name_lower:
            if sheet_name in xl.sheet_names:
                return sheet_name
            # keyword matched but sheet name was not found — fall through
    return xl.sheet_names[DEFAULT_SHEET_INDEX]


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Strip, lowercase and underscore all column headers."""
    df.columns = (
        df.columns
        .str.replace(r"\r|\n", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )
    return df


def classify_age(age: int | float) -> str | float:
    """Map a numeric age to a labelled bucket; return NaN for out-of-range."""
    brackets = [
        (1,    18,   "< 18"),
        (18,   29,   "18-28"),
        (29,   40,   "29-39"),
        (40,   50,   "40-49"),
        (50,   60,   "50-59"),
        (60,   2000, "> 60"),
    ]
    for low, high, label in brackets:
        if low <= age < high:
            return label
    return np.nan


# ── Ingestion ─────────────────────────────────────────────────────────────────

def ingest_from_gcs(
    bucket_prefix: str,
    fs: gcsfs.GCSFileSystem,
    rename_dict: dict[str, str],
    skiprows: int = 2,
) -> pd.DataFrame:
    """
    Single unified task: list every .xlsx file under *bucket_prefix* in GCS,
    read the relevant sheet from each one, normalise + rename columns, and
    return a single concatenated DataFrame containing only the columns that
    are common to all files.

    Args:
        bucket_prefix : GCS path without gs://, e.g.
                        "my-bucket/formacion"
        fs            : authenticated GCSFileSystem instance
        rename_dict   : column rename mapping applied after normalisation
        skiprows      : rows to skip before the header row in each sheet

    Returns:
        Combined DataFrame with common columns only.

    Raises:
        FileNotFoundError : if no .xlsx files are found under the prefix
        ValueError        : if the files share no common columns
    """
    # 1. Discover all Excel files under the prefix ─────────────────────────
    all_paths: list[str] = fs.glob(f"{bucket_prefix}/*.xlsx")
    if not all_paths:
        raise FileNotFoundError(
            f"No .xlsx files found under gs://{bucket_prefix}"
        )
    print(f"  Found {len(all_paths)} file(s) under gs://{bucket_prefix}")

    dataframes: list[pd.DataFrame] = []
    column_sets: list[set] = []

    # 2. Download, read and normalise each file ─────────────────────────────
    for gcs_path in sorted(all_paths):
        filename = os.path.basename(gcs_path)

        with fs.open(gcs_path, "rb") as f:
            raw_bytes = f.read()

        xl = pd.ExcelFile(io.BytesIO(raw_bytes))
        sheet_name = resolve_sheet(filename, xl)

        df = pd.read_excel(
            io.BytesIO(raw_bytes),
            sheet_name=sheet_name,
            skiprows=skiprows,
            header=0,
        )

        df = normalize_column_names(df)
        df.rename(columns=rename_dict, inplace=True)
        df["_source_file"] = filename   # traceability column; dropped later

        dataframes.append(df)
        column_sets.append(set(df.columns))
        print(f"    ✓ {filename:55s} → sheet: '{sheet_name}' | rows: {len(df)}")

    # 3. Verify at least one common column exists as a sanity check ──────────
    data_col_sets = [cs - {"_source_file"} for cs in column_sets]
    common_columns = list(data_col_sets[0].intersection(*data_col_sets[1:]))

    if not common_columns:
        raise ValueError(
            "No common columns found across the Excel files in "
            f"gs://{bucket_prefix}. Check RENAME_DICT and sheet contents."
        )

    all_columns = sorted(
        set().union(*data_col_sets),
        key=lambda c: (c not in common_columns, c)
    )
    print(f"\n  Common columns ({len(common_columns)}): {sorted(common_columns)}")
    print(f"  Total columns after outer join ({len(all_columns)}): {all_columns}")

    # 4. Outer concat: keep ALL columns from all files, NaN-fill missing ones.
    combined = pd.concat(
        dataframes,
        join="outer",
        ignore_index=True,
    )
    combined = combined.drop(columns=["_source_file"])

    # 5. Restrict to the declared column set. Any column not in SELECT_COLUMNS is silently dropped so that noise
    cols_to_keep = [c for c in SELECT_COLUMNS if c in combined.columns]
    missing = [c for c in SELECT_COLUMNS if c not in combined.columns]
    if missing:
        print(f"  ⚠  Columns declared in SELECT_COLUMNS but absent from files: {missing}")
    combined = combined[cols_to_keep]

    print(f"  Combined DataFrame: {len(combined)} rows × {len(combined.columns)} columns\n")
    return combined


# ── Cleaning ──────────────────────────────────────────────────────────────────

def cast_datetime_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Coerce specified columns to datetime; unparseable values become NaT."""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def clean_edad(df: pd.DataFrame) -> pd.DataFrame:
    """Extract numeric age and append a rango_de_edad bucket column."""
    df["edad"] = (
        df["edad"].astype(str)
        .str.extract(r"(\d+)")   
        .iloc[:, 0]              
        .astype("Int64")         
    )
    df["rango_de_edad"] = df["edad"].apply(
        lambda x: classify_age(x) if pd.notna(x) else np.nan
    )
    return df


def lowercase_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase the values of every object-dtype column."""
    obj_cols = df.select_dtypes(include="object").columns
    df[obj_cols] = df[obj_cols].apply(lambda col: col.str.lower())
    return df


def clean_genero(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Normalise gender labels using *mapping* (case-insensitive)."""
    if "género" in df.columns:
        df["género"] = df["género"].str.lower().replace(mapping)
    return df


def filter_valid_records(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split *df* into valid and invalid partitions.

    A record is invalid when any of the mandatory identity columns is null
    or contains only whitespace after string normalisation.  These rows
    carry no usable information and must never reach the database.

    Returns:
        (valid, invalid) — two DataFrames whose lengths sum to len(df).
    """
    
    REQUIRED = ["numero_de_documento", "nombres"]

    # Only check columns that actually exist in this DataFrame
    cols_to_check = [c for c in REQUIRED if c in df.columns]

    # Build a mask: True where the row is missing at least one required field.
    invalid_mask = pd.Series(False, index=df.index)
    for col in cols_to_check:
        is_null  = df[col].isna()
        is_blank = df[col].astype(str).str.strip().eq("")
        invalid_mask |= is_null | is_blank

    valid   = df[~invalid_mask].reset_index(drop=True)
    invalid = df[invalid_mask].reset_index(drop=True)

    if len(invalid) > 0:
        print(f"  ⚠  Dropped {len(invalid)} invalid row(s) "
              f"(null/blank in: {cols_to_check})")

    return valid, invalid


# ── Population flags ──────────────────────────────────────────────────────────

def flag_population(
    df: pd.DataFrame,
    new_col: str,
    patterns: list[str],
    label: str,
    source_col: str = "tipo_de_población",
    extra_col: str | None = None,
    extra_patterns: list[str] | None = None,
    regex: bool = True,
) -> pd.DataFrame:
    """
    Create *new_col* set to *label* where any of *patterns* match
    *source_col* (case-insensitive), or pd.NA otherwise.

    Pass regex=False when patterns contain literal special characters
    (e.g. parentheses in the NARP label).
    Optionally extend the mask via *extra_col* + *extra_patterns*.
    """
    if regex:
        mask = df[source_col].str.contains(
            "|".join(patterns), case=False, na=False, regex=True
        )
    else:
        # Literal match: any pattern is a substring anywhere in the cell
        mask = pd.Series(False, index=df.index)
        for p in patterns:
            mask |= df[source_col].str.contains(p, case=False, na=False, regex=False)

    if extra_col and extra_patterns:
        mask |= df[extra_col].str.contains(
            "|".join(extra_patterns), case=False, na=False, regex=True
        )

    # Build as object Series so NaN stays as pd.NA, not the string "nan"
    result = pd.Series(pd.NA, index=df.index, dtype=object)
    result[mask] = label
    df[new_col] = result
    return df


def flag_discapacidad(
    df: pd.DataFrame,
    patterns: dict[str, str],
) -> pd.DataFrame:
    """
    Classify disability type into a 'discapacidad' column.
    Patterns are evaluated in insertion order; the first match wins,
    so specific patterns must precede the catch-all in *patterns*.
    """

    df["discapacidad"] = pd.array([pd.NA] * len(df), dtype=object)
    for pattern, label in patterns.items():
        mask = (
            df["tipo_discapacidad"].str.contains(pattern, case=False, na=False)
            & df["discapacidad"].isna()   # first-match wins
        )
        df.loc[mask, "discapacidad"] = label
    return df


def add_population_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Orchestrate all population segmentation flags."""
    df = flag_population(df, "vvg",            ["viole", "vvg"],   "vvg")
    df = flag_population(df, "vca",            ["conflic"],         "vca")
    df = flag_population(df, "reincorporados", ["rein"],            "reincorporados")
    df = flag_population(
        df, "grupos_etnicos",
        ["narp (negro, afrocolombiano, raizal o palenquero)"],
        "Grupos etnicos",
        regex=False,
    )
    df = flag_population(
        df, "migrante", ["migr", "retor"], "Migrante o Retornado",
        extra_col="tipo_de_documento",
        extra_patterns=["ermiso", "tranje", "acional"],
    )
    df = flag_discapacidad(df, DISCAPACIDAD_PATTERNS)
    return df


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(
    bucket_prefix: str,
    month: int,
    year: int,
) -> pd.DataFrame:
    """
    Full end-to-end pipeline.

    1. Ingest (list + download + concat) all Excel files from GCS.
    2. Clean and transform.
    3. Return the processed DataFrame.
    """
    fs = gcsfs.GCSFileSystem()

    # ── Ingest ────────────────────────────────────────────────────────────
    inscritos = ingest_from_gcs(bucket_prefix, fs, RENAME_DICT)

    # ── Validate ──────────────────────────────────────────────────────────
    inscritos, _ = filter_valid_records(inscritos)

    # ── Transform ─────────────────────────────────────────────────────────
    inscritos = cast_datetime_columns(inscritos, DATETIME_COLUMNS)
    inscritos = clean_edad(inscritos)
    inscritos = lowercase_string_columns(inscritos)
    inscritos = clean_genero(inscritos, GENERO_MAPPING)
    inscritos = add_population_flags(inscritos)

    # ── Pipeline metadata ─────────────────────────────────────────────────
    inscritos["mes"]  = month
    inscritos["anio"] = year

    # Drop internal traceability column (kept in _source_file only for debugging during development).
    inscritos = inscritos.drop(columns=["_source_file"], errors="ignore")

    return inscritos


# ── Entry point (called by Kestra) ────────────────────────────────────────────

if __name__ == "__main__":
    bucket_prefix = os.environ["GCS_BUCKET"]
    month         = int(os.environ["MONTH"])
    year          = int(os.environ["YEAR"])

    inscritos = run_pipeline(bucket_prefix, month, year)

    # Write output artefacts consumed by Kestra outputFiles
    data_processed = os.environ.get("DATA_PROCESSED", "formacion")
    output_name = f"{data_processed}_{year}_{month}.parquet"
    inscritos.to_parquet(output_name, index=False)
    print(f"  Written: {output_name}  ({len(inscritos)} rows)")

    with open("record_count.txt", "w") as f:
        f.write(str(len(inscritos)))
    print(f"  Written: record_count.txt  ({len(inscritos)} records)")