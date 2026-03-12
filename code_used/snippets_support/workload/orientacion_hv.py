"""
ETL script for processing psychological orientation (Orientación HV) data.

OUTPUT MODEL — one row per session event
-----------------------------------------
Each orientation session and each workshop session produces its own row.
A person who attended 2 orientation sessions and 1 workshop produces 3 rows.

Row structure:
  tipo_evento            : 'orientacion' | 'taller'
  fechaagendamiento      : scalar date of THIS session
  fechaejecucion         : scalar date of THIS session
  fechaevaluacion        : scalar date of THIS session
  mes_evento             : integer month of fechaejecucion
  anio_evento            : integer year  of fechaejecucion
  + all person demographic / programme columns (repeated per row)

The parquet filename pattern is:  orientados_<year>_<month>.parquet
Only rows whose mes_evento / anio_evento matches the requested month/year
are exported.
"""

import pandas as pd
import numpy as np
import os


# ---------------------------------------------------------------------------
# 0. CONSTANTS
# ---------------------------------------------------------------------------

# Scalar date column names used after exploding
ORIENTACION_DATE_COLS = [
    "fechaagendamiento_orientacion",
    "fechaejecucion_orientacion",
    "fechaevaluacion_orientacion",
]
TALLER_DATE_COLS = [
    "fechaagendamiento_taller",
    "fechaejecucion_taller",
    "fechaevaluacion_taller",
]

# Person-level demographic / programme columns that are repeated on every row
PERSON_COLS = [
    "numerodocumento", "tipodocumento", "correoelectronico",
    "primernombre", "segundonombre", "primerapellido", "segundoapellido",
    "sexo", "ciudad", "departamento", "edad", "rango_de_edad",
    "area", "tipo", "subtipo", "nombreportafolio", "nombreconvocatoria",
    "aprobacion", "porcentajeasistencia",
    "prestadornombre", "institucionnombre", "instituciondireccion",
    "institucionmunicipio", "instituciondepartamento",
    "programagobiernosino", "programagobierno", "alianzasentidadesexternas",
    "agencianombre", "numerotelefono", "programa_de_gobierno",
    "condiciones_especiales",
    "grupos_etnicos", "vca", "discapacidad", "migrante", "vvg", "reincorporados",
]

# ---------------------------------------------------------------------------
# NULL-LIKE STRINGS — produced by astype(str) on None / pd.NA / np.nan
# across different pandas versions (1.x, 2.x, 3.x).
#
# pandas < 3  : None  -> "None",  pd.NA (StringDtype) -> "<NA>"
# pandas >= 3 : both  -> "nan"
#
# After .str.lower() they become: "none", "<na>", "nan"
# All must be mapped back to pd.NA in final_string_clean so that
# PostgreSQL / BigQuery receive a proper NULL, not a literal string.
# ---------------------------------------------------------------------------
_NULL_LIKE_STRINGS = {"nan", "none", "<na>", "nat", "null", "n/a"}


# ---------------------------------------------------------------------------
# 1. INGESTION
# ---------------------------------------------------------------------------

def load_orientados(filepath: str, sheet_name: str = "BD_Indicador_1") -> pd.DataFrame:
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df.columns = df.columns.str.lower()
    return df


def load_talleres(filepath: str, sheet_name: str = "Reporte_Indicador_2") -> pd.DataFrame:
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df.columns = df.columns.str.lower()
    return df


def load_registrados(filepath: str, sheet_name: str = "BD_Acumulado-2024-2026") -> pd.DataFrame:
    return pd.read_excel(filepath, sheet_name=sheet_name)


def load_psicologas(filepath: str, sheet_name: str = "Orientados") -> pd.DataFrame:
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    if "Unnamed: 22" in df.columns:
        df = df.drop("Unnamed: 22", axis=1)
    return df


# ---------------------------------------------------------------------------
# 2. CLEANING — produce one row per session (NOT per person)
# ---------------------------------------------------------------------------

def clean_orientados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the orientados sheet and return ONE ROW PER ORIENTATION SESSION.

    Each raw row already represents one session; we just parse dates,
    lowercase strings, and rename columns.  No groupby is performed.

    Returns columns:
        numerodocumento, fechaagendamiento_orientacion,
        fechaejecucion_orientacion, fechaevaluacion_orientacion,
        orientador, indicador, tipodireccionamiento, tipodocumento,
        correoelectronico, primernombre, segundonombre, primerapellido,
        segundoapellido, sexo, ciudad, departamento,
        area, tipo, subtipo, nombreportafolio, nombreconvocatoria,
        aprobacion, porcentajeasistencia, prestadornombre, institucionnombre,
        instituciondireccion, institucionmunicipio, instituciondepartamento,
        programagobiernosino, alianzasentidadesexternas, agencianombre,
        numerotelefono
    """
    for col in ["fechaagendamiento", "fechaejecucion", "fechaevaluacion"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)

    df = df.rename(columns={
        "fechaagendamiento": "fechaagendamiento_orientacion",
        "fechaejecucion":    "fechaejecucion_orientacion",
        "fechaevaluacion":   "fechaevaluacion_orientacion",
        "usuarionombre":     "orientador",
    })

    str_cols = df.select_dtypes(include=["object", "str"]).columns
    df[str_cols] = df[str_cols].apply(
        lambda col: col.map(lambda v: v.lower() if isinstance(v, str) else v)
    )

    return df


def clean_talleres(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the talleres sheet and return ONE ROW PER WORKSHOP SESSION.

    Same logic as clean_orientados — each raw row is one session.
    """
    for col in ["fechaagendamiento", "fechaejecucion", "fechaevaluacion"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)

    df = df.rename(columns={
        "fechaagendamiento": "fechaagendamiento_taller",
        "fechaejecucion":    "fechaejecucion_taller",
        "fechaevaluacion":   "fechaevaluacion_taller",
        "usuarionombre":     "tallerista",
    })

    return df


def clean_registrados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate to one row per person — used only to enrich demographics.
    """
    df.columns = df.columns.str.replace("Número Documento", "numerodocumento")

    first_cols = [
        "No. ", "Programa / Aliado\n(Si aplica)", "Barrio donde vive",
        "Tipo Documento", "TIPO_REGISTRO", "Nombres", "Apellidos", "Celular",
        "Teléfono", "Canal de Registro", "Edad", "Rango_Edad", "Género",
        "Nivel de Estudio", "Título Homologado", "Ciudad de Residencia",
        "Email", "Fecha Registro", "Detalle Discapacidades", "Situación Laboral",
        "Agente Registra", "Fecha Actualización", "% Hoja Vida",
        "Prestador Anterior", "Fecha Cambio Prestador",
        "Vereda/Localidad/Centro Poblado", "Pertenece A", "SISE_OFFLINE",
        "Mes", "Año", "Punto Atención",
    ]
    agg_spec = {col: "first" for col in first_cols if col in df.columns}
    for col in ["Programa de Gobierno", "Condiciones Especiales"]:
        if col in df.columns:
            agg_spec[col] = lambda x: ",".join(map(str, x.dropna().unique()))

    return df.groupby("numerodocumento").agg(agg_spec).reset_index()


def clean_psicologas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate to one row per person — used only to enrich EDAD / POBLACIÓN.
    """
    df.columns = df.columns.str.replace("NUMERO.1", "numerodocumento")

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)

    first_cols = [
        "MES", "NUMERO", "FECHA", "ORIENTADOR", "NOMBRE", "TD", "GENERO",
        "EDAD", "RANGO", "TELEFONO", "BARRIO", "NIVEL DE FORMACIÓN",
        "FORMACIÓN", "EXPERIENCIA LABORAL", "CORREO ELECTRONICO",
        "OBSERVACIONES", "INTÉRES CURSO FORMACIÓN",
        "VALIDACIÓN DE BACHILLERATO (SI / NO)", "A TENER EN CUENTA",
    ]
    agg_spec = {col: "first" for col in first_cols if col in df.columns}
    for col in ["POBLACIÓN", "TALLER FIS"]:
        if col in df.columns:
            agg_spec[col] = lambda x: ",".join(map(str, x.dropna().unique()))

    return df.groupby("numerodocumento").agg(agg_spec).reset_index()


# ---------------------------------------------------------------------------
# 3. BUILD EVENT ROWS
# ---------------------------------------------------------------------------

def build_orientacion_events(orientados: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the cleaned orientados DataFrame into event rows.

    Each row represents one orientation session.  Adds:
        tipo_evento    = 'orientacion'
        mes_evento     = month of fechaejecucion_orientacion
        anio_evento    = year  of fechaejecucion_orientacion

    Drops rows where fechaejecucion_orientacion is NaT.
    """
    df = orientados.copy()
    df["tipo_evento"] = "orientacion"

    df["mes_evento"]  = df["fechaejecucion_orientacion"].dt.month.astype("Int64")
    df["anio_evento"] = df["fechaejecucion_orientacion"].dt.year.astype("Int64")

    # Drop rows with no execution date — they cannot be placed in any month
    df = df.dropna(subset=["fechaejecucion_orientacion"])
    return df


def build_taller_events(talleres: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the cleaned talleres DataFrame into event rows.

    Each row represents one workshop session.  Adds:
        tipo_evento    = 'taller'
        mes_evento     = month of fechaejecucion_taller
        anio_evento    = year  of fechaejecucion_taller

    Drops rows where fechaejecucion_taller is NaT.
    """
    df = talleres.copy()
    df["tipo_evento"] = "taller"

    # Rename taller date cols to generic names for the unified events table
    df = df.rename(columns={
        "fechaagendamiento_taller": "fechaagendamiento_orientacion",
        "fechaejecucion_taller":    "fechaejecucion_orientacion",
        "fechaevaluacion_taller":   "fechaevaluacion_orientacion",
    })

    df["mes_evento"]  = df["fechaejecucion_orientacion"].dt.month.astype("Int64")
    df["anio_evento"] = df["fechaejecucion_orientacion"].dt.year.astype("Int64")

    df = df.dropna(subset=["fechaejecucion_orientacion"])
    return df


# ---------------------------------------------------------------------------
# 4. MERGING — enrich events with person demographics
# ---------------------------------------------------------------------------

def enrich_events(
    events: pd.DataFrame,
    registrados: pd.DataFrame,
    psicologas:  pd.DataFrame,
) -> pd.DataFrame:
    """
    Left-join the events table with registrados and psicologas to bring in
    demographics (edad, condiciones_especiales, programa_de_gobierno, etc.).

    The join is always on numerodocumento.  Events rows are never dropped.

    Steps:
        1. Merge events ← registrados  (brings Programa de Gobierno,
           Condiciones Especiales)
        2. Merge events ← psicologas   (brings EDAD, POBLACIÓN)
        3. Append POBLACIÓN to condiciones_especiales, then drop POBLACIÓN.
        4. Normalise all column names to lowercase_with_underscores.
        5. Coerce edad to nullable Int64.
    """
    df = events.merge(
        registrados[["numerodocumento", "Programa de Gobierno", "Condiciones Especiales"]],
        on="numerodocumento", how="left",
    )
    df = df.merge(
        psicologas[["numerodocumento", "EDAD", "POBLACIÓN"]],
        on="numerodocumento", how="left",
    )

    df["Condiciones Especiales"] = df.apply(
        lambda row: (
            f"{row['Condiciones Especiales']}, {row['POBLACIÓN']}"
            if pd.notnull(row["POBLACIÓN"])
            else row["Condiciones Especiales"]
        ),
        axis=1,
    )
    df = df.drop("POBLACIÓN", axis=1)

    df.columns = df.columns.str.lower().str.replace(" ", "_")
    df["edad"] = pd.to_numeric(df["edad"], errors="coerce").round().astype("Int64")
    return df


# ---------------------------------------------------------------------------
# 5. DERIVED COLUMNS
# ---------------------------------------------------------------------------

def derive_age_range(df: pd.DataFrame) -> pd.DataFrame:
    def _band(age) -> str:
        try:
            age = int(age)
        except (TypeError, ValueError):
            return np.nan
        if 0 < age < 18:     return "< 18"
        if 18 <= age < 29:   return "18-28"
        if 29 <= age < 40:   return "29-39"
        if 40 <= age < 50:   return "40-49"
        if 50 <= age < 60:   return "50-59"
        if 60 <= age < 2000: return "> 60"
        return np.nan

    df["rango_de_edad"] = df["edad"].apply(_band)
    return df


# ---------------------------------------------------------------------------
# 6. POPULATION CLASSIFICATION
# ---------------------------------------------------------------------------

def classify_ethnic_groups(df: pd.DataFrame) -> pd.DataFrame:
    df["condiciones_especiales"] = (
        df["condiciones_especiales"].astype(str).str.lower().fillna("")
    )
    patterns = {
        "Afrodescendiente":  r"negr|afro|mulat|palen",
        "Raizal y/o Isleño": r"raiz",
        "Indígenas":         r"ind[íi]",
        "Gitano":            r"git",
    }
    def _classify(text: str):
        groups = [l for l, p in patterns.items()
                  if pd.Series([text]).str.contains(p, regex=True).iloc[0]]
        return groups if groups else np.nan
    df["grupos_etnicos"] = df["condiciones_especiales"].apply(_classify)
    return df


def classify_vca(df: pd.DataFrame) -> pd.DataFrame:
    df["programa_de_gobierno"] = df["programa_de_gobierno"].fillna("").astype(str)
    df["vca"] = pd.Series(dtype="object")
    mask = (
        df["programa_de_gobierno"].str.contains("armado", na=False) |
        df["condiciones_especiales"].str.contains(r"vca|v\.c\.a", na=False)
    )
    df.loc[mask, "vca"] = "VCA"
    return df


def classify_disability(df: pd.DataFrame) -> pd.DataFrame:
    df["discapacidad"] = pd.Series([np.nan] * len(df), dtype="object")
    patterns = {
        r"ognitiv|telect": "Cognitiva o Intelectual",
        r"[íi]sic":        "Física",
        r"visual":         "Visual",
        r"auditiva":       "Auditiva",
        r"múltiple":       "Múltiple",
        r"sordoceguera":   "Sordoceguera",
        r"psicosocial":    "Psicosocial",
        r"capacidad":      "Discapacidad",
    }
    for pattern, label in patterns.items():
        mask = df["discapacidad"].isna() & df["condiciones_especiales"].str.contains(
            pattern, case=False, na=False)
        df.loc[mask, "discapacidad"] = label
    return df


def classify_migrants(df: pd.DataFrame) -> pd.DataFrame:
    # FIX: initialise as object dtype with np.nan so that:
    #   (a) string labels can be assigned via .loc without a TypeError
    #       (pandas 3 raises TypeError when assigning a str into float64)
    #   (b) no StringDtype is used — StringDtype silently converts None back
    #       to pd.NA, which serialises as "<NA>"/"<na>" on pandas < 3
    #   (c) the .where()/.replace() dance that produced "none"/"<na>" strings
    #       is eliminated entirely
    df["migrante"] = pd.Series(np.nan, index=df.index, dtype=object)
    mask = (
        df["condiciones_especiales"].str.contains(r"migr|retor", na=False) |
        df["tipodocumento"].str.contains(r"dni|ppt|ce", na=False)
    )
    df.loc[mask, "migrante"] = "Migrante o Retornado"
    return df


def classify_vvg(df: pd.DataFrame) -> pd.DataFrame:
    # FIX: object dtype + direct label assignment — see classify_migrants.
    # Replaces the fragile .where(col != "", other=pd.NA).replace({pd.NA: None})
    # chain that produced "none"/"<na>" literal strings on pandas < 3.
    df["vvg"] = pd.Series(np.nan, index=df.index, dtype=object)
    mask = df["condiciones_especiales"].str.contains(r"viole|vvg", na=False)
    df.loc[mask, "vvg"] = "vvg"
    return df


def classify_reintegrated(df: pd.DataFrame) -> pd.DataFrame:
    # FIX: same pattern as classify_vvg / classify_migrants.
    df["reincorporados"] = pd.Series(np.nan, index=df.index, dtype=object)
    mask = df["condiciones_especiales"].str.contains("rein", na=False)
    df.loc[mask, "reincorporados"] = "reincorporados"
    return df


def run_all_classifications(df: pd.DataFrame) -> pd.DataFrame:
    df = classify_ethnic_groups(df)
    df = classify_vca(df)
    df = classify_disability(df)
    df = classify_migrants(df)
    df = classify_vvg(df)
    df = classify_reintegrated(df)
    return df


# ---------------------------------------------------------------------------
# 7. FINAL CLEANING
# ---------------------------------------------------------------------------

def final_string_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lowercase and strip all object / string columns, then replace every
    null-like string with pd.NA so PostgreSQL / BigQuery receive a proper NULL.

    Null-like strings that must be normalised
    -----------------------------------------
    Different pandas versions serialise None / pd.NA differently through
    astype(str):

      pandas < 3  :  None              -> "None"  -> after .lower() -> "none"
                     pd.NA (StringDtype) -> "<NA>" -> after .lower() -> "<na>"
      pandas >= 3 :  both              -> "nan"

    Only replacing "nan" (the original code) silently passes "none" and
    "<na>" through to the database as literal strings on pandas < 3.
    We replace the full set of known null-like tokens after lowercasing.

    Skips:
      - DATE_SCALAR_COLS: datetime columns must stay as datetime64
      - NUMERIC_COLS: porcentajeasistencia, edad, mes_evento, anio_evento
        must stay numeric so Parquet writes DOUBLE/INT64, not BYTE_ARRAY.
    """
    DATE_SCALAR_COLS = {
        "fechaagendamiento_orientacion",
        "fechaejecucion_orientacion",
        "fechaevaluacion_orientacion",
    }
    NUMERIC_COLS = {
        "porcentajeasistencia", "edad", "mes_evento", "anio_evento",
    }
    for col in df.columns:
        if col in DATE_SCALAR_COLS or col in NUMERIC_COLS:
            continue
        if (
            df[col].dtype == object or pd.api.types.is_string_dtype(df[col])
        ) and not pd.api.types.is_bool_dtype(df[col]):
            df[col] = df[col].astype(str).str.lower().str.strip()

    # FIX: replace the complete set of null-like tokens, not just "nan".
    # This is the single most important fix: it catches "none" (from None on
    # pandas < 3) and "<na>" (from pd.NA / StringDtype on pandas < 3) as well
    # as "nan", "nat", "null", "n/a" and empty strings.
    df = df.replace(list(_NULL_LIKE_STRINGS), pd.NA)
    return df


# ---------------------------------------------------------------------------
# 8. FILTERING & EXPORT
# ---------------------------------------------------------------------------

def filter_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """Keep only rows whose mes_evento / anio_evento match month/year."""
    return df[
        (df["mes_evento"] == month) & (df["anio_evento"] == year)
    ].copy()


def filter_orientacion_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    return df[
        (df["tipo_evento"] == "orientacion") &
        (df["mes_evento"] == month) &
        (df["anio_evento"] == year)
    ].copy()


def filter_taller_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    return df[
        (df["tipo_evento"] == "taller") &
        (df["mes_evento"] == month) &
        (df["anio_evento"] == year)
    ].copy()


def export_parquet(df: pd.DataFrame, month: int, year: int) -> str:
    """
    Export the monthly event rows to a compressed parquet file.

    Enforces correct Parquet physical types before writing:
      porcentajeasistencia → float64   (Parquet DOUBLE,  BigQuery FLOAT64)
      edad, mes_evento, anio_evento → Int64  (Parquet INT64, BigQuery INT64)
    Date columns are written as TIMESTAMP (pandas datetime64).

    Filename: orientados_<year>_<month>.parquet
    """
    df = df.copy()

    float_cols = ["porcentajeasistencia"]
    int_cols   = ["edad", "mes_evento", "anio_evento"]

    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    filename = f"orientados_{year}_{month}.parquet"
    df.to_parquet(filename, compression="zstd")
    return filename


def write_count(count: int, filepath: str) -> None:
    with open(filepath, "w") as f:
        f.write(str(count))


# ---------------------------------------------------------------------------
# 9. REPORTING
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, month: int, year: int) -> None:
    monthly = filter_by_month(df, month, year)

    for label, tipo in [("orientados", "orientacion"), ("taller FIS", "taller")]:
        sub = monthly[monthly["tipo_evento"] == tipo]
        print(f"\n--- {label} mes {month}/{year} ({len(sub)} sesiones) ---")
        print(f"  Hombres:   {(sub['sexo'] == 'm').sum()}")
        print(f"  Mujeres:   {(sub['sexo'] == 'f').sum()}")
        print(f"  PCD:       {sub['discapacidad'].notna().sum()}")
        print(f"  VCA:       {sub['vca'].notna().sum()}")
        print(f"  VVG:       {sub['vvg'].notna().sum()}")
        print(f"  Migrantes: {sub['migrante'].notna().sum()}")
        print(f"  Étnicos:   {sub['grupos_etnicos'].notna().sum()}")
        print(f"  Reinc.:    {sub['reincorporados'].notna().sum()}")


# ---------------------------------------------------------------------------
# 10. MAIN PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_pipeline(
    sise_psico_path: str,
    registries_path: str,
    psicologist_path: str,
    month: int,
    year: int,
) -> pd.DataFrame:
    """
    Execute the full ETL pipeline and return the combined events DataFrame
    (all months, all event types).

    Steps:
        1.  Load all four source files.
        2.  clean_orientados / clean_talleres  → one row per session
        3.  clean_registrados / clean_psicologas → one row per person (for enrichment)
        4.  build_orientacion_events / build_taller_events
        5.  Combine orientation + taller events into one DataFrame
        6.  enrich_events with demographics
        7.  derive_age_range
        8.  run_all_classifications
        9.  final_string_clean

    Returns:
        Flat events DataFrame — one row per session.
    """
    orientados   = clean_orientados(load_orientados(sise_psico_path))
    talleres     = clean_talleres(load_talleres(sise_psico_path))
    registrados  = clean_registrados(load_registrados(registries_path))
    psicologas   = clean_psicologas(load_psicologas(psicologist_path))

    orientacion_events = build_orientacion_events(orientados)
    taller_events      = build_taller_events(talleres)

    # Union all events — column sets differ (orientador vs tallerista), so
    # pd.concat fills missing columns with NaN automatically.
    events = pd.concat([orientacion_events, taller_events], ignore_index=True)

    events = enrich_events(events, registrados, psicologas)
    events = derive_age_range(events)
    events = run_all_classifications(events)
    events = final_string_clean(events)
    return events


def main():
    """
    Entry point for Kestra execution.

    Reads MONTH and YEAR from environment variables, runs the pipeline,
    exports the monthly parquet, and writes count text files.
    """
    month = int(os.getenv("MONTH"))
    year  = int(os.getenv("YEAR"))

    df = run_pipeline("sise_psico", "registries", "psicologist", month, year)

    print_summary(df, month, year)

    export_df  = filter_by_month(df, month, year)
    oriented   = filter_orientacion_by_month(df, month, year)
    workshops  = filter_taller_by_month(df, month, year)

    filename = export_parquet(export_df, month, year)

    num_oriented  = len(oriented)
    num_workshops = len(workshops)

    print(f"\nOrientation sessions exported for {month}/{year}: {num_oriented}")
    write_count(num_oriented, "psico_count.txt")

    print(f"Workshop sessions exported for {month}/{year}: {num_workshops}")
    write_count(num_workshops, "workshop_count.txt")

    print(f"Output written to: {filename}")


if __name__ == "__main__":
    main()