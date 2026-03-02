"""
ETL script for processing psychological orientation (Orientación HV) data.

Structured as pure, testable functions following the same conventions as
registro_hv.py.  The main() function at the bottom orchestrates the full
pipeline and is the only entry point that reads environment variables or
writes files to disk.
"""

import pandas as pd
import numpy as np
import os


# ---------------------------------------------------------------------------
# 1. INGESTION
# ---------------------------------------------------------------------------

def load_orientados(filepath: str, sheet_name: str = "BD_Indicador_1") -> pd.DataFrame:
    """
    Read the 'orientados' sheet from the SISE-psicología Excel file.

    Normalisation applied:
      - Column names lowercased.
      - Spaces replaced with underscores.

    Args:
        filepath:   Path to the Excel file (or Kestra virtual path 'sise_psico').
        sheet_name: Name of the sheet to read.

    Returns:
        pd.DataFrame with normalised column names.
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df.columns = df.columns.str.lower()
    return df


def load_talleres(filepath: str, sheet_name: str = "Reporte_Indicador_2") -> pd.DataFrame:
    """
    Read the 'talleres FIS' sheet from the SISE-psicología Excel file.

    Same normalisation as load_orientados().

    Args:
        filepath:   Path to the Excel file (or Kestra virtual path 'sise_psico').
        sheet_name: Name of the sheet to read.

    Returns:
        pd.DataFrame with normalised column names.
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    df.columns = df.columns.str.lower()
    return df


def load_registrados(filepath: str, sheet_name: str = "BD_Acumulado-2024-2026") -> pd.DataFrame:
    """
    Read the cumulative CV registrations Excel file.

    Args:
        filepath:   Path to the Excel file (or Kestra virtual path 'registries').
        sheet_name: Name of the sheet to read.

    Returns:
        Raw pd.DataFrame (column normalisation handled in clean_registrados()).
    """
    return pd.read_excel(filepath, sheet_name=sheet_name)


def load_psicologas(filepath: str, sheet_name: str = "Orientados") -> pd.DataFrame:
    """
    Read the psychologist tracking Excel file.

    Drops the known spurious 'Unnamed: 22' column if present.

    Args:
        filepath:   Path to the Excel file (or Kestra virtual path 'psicologist').
        sheet_name: Name of the sheet to read.

    Returns:
        pd.DataFrame ready for cleaning.
    """
    df = pd.read_excel(filepath, sheet_name=sheet_name)
    if "Unnamed: 22" in df.columns:
        df = df.drop("Unnamed: 22", axis=1)
    return df


# ---------------------------------------------------------------------------
# 2. CLEANING
# ---------------------------------------------------------------------------

def clean_orientados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse date columns, lowercase string values, and rename columns for
    the orientados DataFrame.

    Steps:
      1. Parse 'fechaagendamiento', 'fechaejecucion', 'fechaevaluacion' as
         datetime.
      2. Lowercase all string cell values.
      3. Rename columns to their semantic names.
      4. Derive integer 'mes_orientado' and 'año_orientado' from
         'fechaejecucion_orientacion'.

    Args:
        df: Raw orientados DataFrame from load_orientados().

    Returns:
        Cleaned and enriched DataFrame.
    """
    date_cols = ["fechaagendamiento", "fechaejecucion", "fechaevaluacion"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)

    df = df.rename(columns={
        "fechaagendamiento": "fechaagendamiento_orientacion",
        "fechaejecucion":    "fechaejecucion_orientacion",
        "fechaevaluacion":   "fechaevaluacion_orientacion",
        "usuarionombre":     "orientador",
    })

    df["mes_orientado"] = (
        pd.to_numeric(df["fechaejecucion_orientacion"].dt.month, errors="coerce")
        .round()
        .astype("Int64")
    )
    df["año_orientado"] = (
        pd.to_numeric(df["fechaejecucion_orientacion"].dt.year, errors="coerce")
        .round()
        .astype("Int64")
    )
    return df


def clean_talleres(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse date columns, lowercase string values, rename columns, and
    derive 'mes_taller' / 'año_taller' for the talleres DataFrame.

    Then aggregate to one row per 'numerodocumento', keeping the first
    value for most fields and joining unique 'programagobierno' values
    with commas.

    Args:
        df: Raw talleres DataFrame from load_talleres().

    Returns:
        Aggregated and cleaned DataFrame (one row per person).
    """
    date_cols = ["fechaagendamiento", "fechaejecucion", "fechaevaluacion"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])

    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.lower() if isinstance(x, str) else x)

    df = df.rename(columns={
        "fechaagendamiento": "fechaagendamiento_taller",
        "fechaejecucion":    "fechaejecucion_taller",
        "fechaevaluacion":   "fechaevaluacion_taller",
        "usuarionombre":     "tallerista",
    })

    df["mes_taller"] = (
        pd.to_numeric(df["fechaejecucion_taller"].dt.month, errors="coerce")
        .round()
        .astype("Int64")
    )
    df["año_taller"] = (
        pd.to_numeric(df["fechaejecucion_taller"].dt.year, errors="coerce")
        .round()
        .astype("Int64")
    )

    first_cols = [
        "indicador", "tipodireccionamiento", "tipodocumento", "correoelectronico",
        "primernombre", "segundonombre", "primerapellido", "segundoapellido",
        "sexo", "ciudad", "departamento", "area", "tipo", "subtipo",
        "nombreportafolio", "nombreconvocatoria", "fechaagendamiento_taller",
        "fechaejecucion_taller", "fechaevaluacion_taller", "aprobacion",
        "porcentajeasistencia", "prestadornombre", "institucionnombre",
        "instituciondireccion", "institucionmunicipio", "instituciondepartamento",
        "programagobiernosino", "alianzasentidadesexternas", "tallerista",
        "agencianombre", "numerotelefono", "mes_taller", "año_taller",
    ]
    agg_spec = {col: "first" for col in first_cols if col in df.columns}
    if "programagobierno" in df.columns:
        agg_spec["programagobierno"] = lambda x: ",".join(map(str, x.dropna().unique()))

    return df.groupby("numerodocumento").agg(agg_spec).reset_index()


def clean_registrados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename the key identifier columns in the registrados DataFrame and
    aggregate to one row per 'numerodocumento'.

    'Programa de Gobierno' and 'Condiciones Especiales' are joined across
    multiple rows with commas so no information is lost.

    Args:
        df: Raw registrados DataFrame from load_registrados().

    Returns:
        Aggregated DataFrame (one row per person).
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
    Rename the key identifier column in the psicologas DataFrame,
    lowercase all string values, and aggregate to one row per
    'numerodocumento'.

    'POBLACIÓN' and 'TALLER FIS' are joined with commas across rows.

    Args:
        df: Raw psicologas DataFrame from load_psicologas().

    Returns:
        Aggregated DataFrame (one row per person).
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
# 3. MERGING
# ---------------------------------------------------------------------------

def merge_all(
    orientados: pd.DataFrame,
    talleres:   pd.DataFrame,
    registrados: pd.DataFrame,
    psicologas:  pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge all four source DataFrames into a single wide DataFrame.

    Merge order:
      1. orientados  ← talleres        (outer join on numerodocumento)
         Duplicate columns from the join (suffix _x / _y) are resolved
         with combine_first() so that orientados values take precedence.
      2. result      ← registrados     (left join; brings in 'Programa de
         Gobierno' and 'Condiciones Especiales')
      3. result      ← psicologas      (left join; brings in 'EDAD' and
         'POBLACIÓN')
      4. 'POBLACIÓN' is appended to 'condiciones_especiales' then dropped.
      5. All column names are lowercased and spaces replaced by underscores.
      6. 'edad' is coerced to nullable Int64.

    Args:
        orientados:  Cleaned orientados DataFrame.
        talleres:    Cleaned talleres DataFrame.
        registrados: Cleaned registrados DataFrame.
        psicologas:  Cleaned psicologas DataFrame.

    Returns:
        Merged DataFrame ready for classification.
    """
    # --- 1. orientados + talleres (outer) ---
    df = orientados.merge(talleres, on="numerodocumento", how="outer")

    shared_cols = [
        "indicador", "tipodireccionamiento", "tipodocumento", "correoelectronico",
        "primernombre", "segundonombre", "primerapellido", "segundoapellido",
        "sexo", "ciudad", "departamento", "area", "tipo", "subtipo",
        "nombreportafolio", "nombreconvocatoria", "aprobacion",
        "porcentajeasistencia", "prestadornombre", "institucionnombre",
        "instituciondireccion", "institucionmunicipio", "instituciondepartamento",
        "programagobiernosino", "programagobierno", "alianzasentidadesexternas",
        "agencianombre", "numerotelefono",
    ]
    for col in shared_cols:
        x, y = f"{col}_x", f"{col}_y"
        if x in df.columns and y in df.columns:
            df[col] = df[x].astype(object).combine_first(df[y].astype(object))
            df.drop(columns=[x, y], inplace=True)

    # --- 2. + registrados ---
    df = df.merge(
        registrados[["numerodocumento", "Programa de Gobierno", "Condiciones Especiales"]],
        on="numerodocumento", how="left",
    )

    # --- 3. + psicologas ---
    df = df.merge(
        psicologas[["numerodocumento", "EDAD", "POBLACIÓN"]],
        on="numerodocumento", how="left",
    )

    # --- 4. Enrich condiciones_especiales with POBLACIÓN ---
    df["Condiciones Especiales"] = df.apply(
        lambda row: (
            f"{row['Condiciones Especiales']}, {row['POBLACIÓN']}"
            if pd.notnull(row["POBLACIÓN"])
            else row["Condiciones Especiales"]
        ),
        axis=1,
    )
    df = df.drop("POBLACIÓN", axis=1)

    # --- 5. Normalise column names ---
    df.columns = df.columns.str.lower().str.replace(" ", "_")

    # --- 6. Coerce edad ---
    df["edad"] = pd.to_numeric(df["edad"], errors="coerce").round().astype("Int64")

    return df


# ---------------------------------------------------------------------------
# 4. DERIVED COLUMNS
# ---------------------------------------------------------------------------

def derive_age_range(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'rango_de_edad' column based on the 'edad' column.

    Bands:
      <18 | 18-28 | 29-39 | 40-49 | 50-59 | >60

    Args:
        df: DataFrame with an integer 'edad' column.

    Returns:
        DataFrame with 'rango_de_edad' added.
    """
    def _band(age) -> str | float:
        try:
            age = int(age)
        except (TypeError, ValueError):
            return np.nan
        if 0 < age < 18:   return "< 18"
        if 18 <= age < 29:  return "18-28"
        if 29 <= age < 40:  return "29-39"
        if 40 <= age < 50:  return "40-49"
        if 50 <= age < 60:  return "50-59"
        if 60 <= age < 2000: return "> 60"
        return np.nan

    df["rango_de_edad"] = df["edad"].apply(_band)
    return df


# ---------------------------------------------------------------------------
# 5. POPULATION CLASSIFICATION
# ---------------------------------------------------------------------------

def classify_ethnic_groups(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive the 'grupos_etnicos' column from 'condiciones_especiales'.

    See registro_hv.py for full pattern documentation.

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

    def _classify(text: str):
        groups = [
            label for label, pat in patterns.items()
            if pd.Series([text]).str.contains(pat, regex=True).iloc[0]
        ]
        return groups if groups else np.nan

    df["grupos_etnicos"] = df["condiciones_especiales"].apply(_classify)
    return df


def classify_vca(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag victims of the armed conflict ('VCA').

    Condition: 'programa_de_gobierno' contains 'armado'  OR
               'condiciones_especiales' contains 'vca' / 'v.c.a'.

    Args:
        df: DataFrame with both relevant columns.

    Returns:
        DataFrame with 'vca' column added.
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
    Classify disability type from 'condiciones_especiales'.

    The first matching pattern wins; 'capacidad' is the catch-all and
    is intentionally placed last.

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
        unclassified = df["discapacidad"].isna()
        mask = unclassified & df["condiciones_especiales"].str.contains(
            pattern, case=False, na=False
        )
        df.loc[mask, "discapacidad"] = label

    return df


def classify_migrants(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag migrants and returnees ('Migrante o Retornado').

    Condition: 'condiciones_especiales' contains 'migr'/'retor'  OR
               'tipodocumento' contains 'dni', 'ppt', or 'ce'
               (fragments of common migrant document types).

    Args:
        df: DataFrame with 'condiciones_especiales' and 'tipodocumento'.

    Returns:
        DataFrame with 'migrante' column added.
    """
    df["migrante"] = ""
    mask = (
        df["condiciones_especiales"].str.contains(r"migr|retor", na=False) |
        df["tipodocumento"].str.contains(r"dni|ppt|ce", na=False)
    )
    df.loc[mask, "migrante"] = "Migrante o Retornado"
    df["migrante"] = df["migrante"].where(df["migrante"] != "", other=pd.NA)
    return df


def classify_vvg(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag victims of gender-based violence ('vvg').

    Condition: 'condiciones_especiales' contains 'viole' or 'vvg'.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'vvg' column added.
    """
    df["vvg"] = ""
    mask = df["condiciones_especiales"].str.contains(r"viole|vvg", na=False)
    df.loc[mask, "vvg"] = "vvg"
    df["vvg"] = df["vvg"].where(df["vvg"] != "", other=pd.NA)
    return df


def classify_reintegrated(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag people in a reintegration/reincorporation programme.

    Condition: 'condiciones_especiales' contains 'rein'.

    Args:
        df: DataFrame with 'condiciones_especiales' column.

    Returns:
        DataFrame with 'reincorporados' column added.
    """
    df["reincorporados"] = ""
    mask = df["condiciones_especiales"].str.contains("rein", na=False)
    df.loc[mask, "reincorporados"] = "reincorporados"
    df["reincorporados"] = df["reincorporados"].where(df["reincorporados"] != "", other=pd.NA)
    return df


def run_all_classifications(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convenience wrapper: run all six population-classification steps
    in the correct order.

    Args:
        df: Merged and date-parsed DataFrame.

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
# 6. FINAL CLEANING
# ---------------------------------------------------------------------------

def final_string_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lowercase and strip all object columns, then replace the string
    'nan' with pd.NA.

    Args:
        df: Fully classified DataFrame.

    Returns:
        Cleaned DataFrame.
    """
    for col in df.columns:
        if (
            df[col].dtype == object
            or pd.api.types.is_string_dtype(df[col])
        ) and not pd.api.types.is_bool_dtype(df[col]):
            df[col] = df[col].astype(str).str.lower().str.strip()
    df = df.replace("nan", pd.NA)
    return df


# ---------------------------------------------------------------------------
# 7. FILTERING & EXPORT
# ---------------------------------------------------------------------------

def filter_orientados_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """
    Keep rows where 'fechaejecucion_orientacion' falls in month/year.

    Args:
        df:    Fully transformed DataFrame.
        month: Target month (1–12).
        year:  Target year.

    Returns:
        Filtered DataFrame.
    """
    mask = (df["mes_orientado"] == month) & (df["año_orientado"] == year)
    return df[mask].copy()


def filter_talleres_by_month(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """
    Keep rows where 'fechaejecucion_taller' falls in month/year.

    Args:
        df:    Fully transformed DataFrame.
        month: Target month (1–12).
        year:  Target year.

    Returns:
        Filtered DataFrame.
    """
    mask = (df["mes_taller"] == month) & (df["año_taller"] == year)
    return df[mask].copy()


def filter_export(df: pd.DataFrame, month: int, year: int) -> pd.DataFrame:
    """
    Keep rows that appear in the target month either as an orientation
    session OR as a taller session.

    This mirrors the original export filter:
        (mes_orientado == month) | (mes_taller == month AND año_taller == year)

    Args:
        df:    Fully transformed DataFrame.
        month: Target month (1–12).
        year:  Target year.

    Returns:
        Filtered DataFrame for export.
    """
    mask = (
        (df["mes_orientado"] == month) |
        ((df["mes_taller"] == month) & (df["año_taller"] == year))
    )
    return df[mask].copy()


def export_parquet(df: pd.DataFrame, month: int, year: int) -> str:
    """
    Export the monthly DataFrame to a compressed parquet file.

    Filename pattern: orientados_<year>_<month>.parquet

    Args:
        df:    Monthly DataFrame to export.
        month: Integer month used in the filename.
        year:  Integer year used in the filename.

    Returns:
        The filename that was written.
    """
    filename = f"orientados_{year}_{month}.parquet"
    df.to_parquet(filename, compression="zstd")
    return filename


def write_count(count: int, filepath: str) -> None:
    """
    Write a record count to a plain-text file for Kestra outputFiles.

    Args:
        count:    Number of records.
        filepath: Destination filename (e.g. 'psico_count.txt').
    """
    with open(filepath, "w") as f:
        f.write(str(count))


# ---------------------------------------------------------------------------
# 8. REPORTING
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame, month: int, year: int) -> None:
    """
    Print population breakdowns for psychological orientation sessions
    and FIS workshops held during month/year.

    Args:
        df:    Fully transformed DataFrame (all months).
        month: Month to summarise.
        year:  Year to summarise.
    """
    def _count(mask) -> int:
        return int(mask.sum())

    for label, f_month in [
        ("orientados", (df["mes_orientado"] == month) & (df["año_orientado"] == year)),
        ("taller FIS", (df["mes_taller"]    == month) & (df["año_taller"]    == year)),
    ]:
        print(f"\n--- {label} mes {month}/{year} ---")
        print(f"  Hombres:   {_count(f_month & (df['sexo'] == 'm'))}")
        print(f"  Mujeres:   {_count(f_month & (df['sexo'] == 'f'))}")
        print(f"  PCD:       {_count(f_month & df['discapacidad'].notna())}")
        print(f"  VCA:       {_count(f_month & df['vca'].notna())}")
        print(f"  VVG:       {_count(f_month & df['vvg'].notna())}")
        print(f"  Migrantes: {_count(f_month & df['migrante'].notna())}")
        print(f"  Étnicos:   {_count(f_month & df['grupos_etnicos'].notna())}")
        print(f"  Reinc.:    {_count(f_month & df['reincorporados'].notna())}")
        print(f"  ≥60 años:  {_count(f_month & (df['edad'] >= 60))}")
        print(f"  29-59:     {_count(f_month & (df['edad'] >= 29) & (df['edad'] < 60))}")
        print(f"  ≤28 años:  {_count(f_month & (df['edad'] <= 28))}")


# ---------------------------------------------------------------------------
# 9. MAIN PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------

def run_pipeline(
    sise_psico_path: str,
    registries_path: str,
    psicologist_path: str,
    month: int,
    year: int,
) -> pd.DataFrame:
    """
    Execute the full ETL pipeline and return the combined monthly DataFrame.

    Steps:
        1.  load_orientados / load_talleres / load_registrados / load_psicologas
        2.  clean_orientados / clean_talleres / clean_registrados / clean_psicologas
        3.  merge_all
        4.  derive_age_range
        5.  run_all_classifications
        6.  final_string_clean

    The returned DataFrame contains ALL months; use filter_orientados_by_month(),
    filter_talleres_by_month(), or filter_export() to slice it.

    Args:
        sise_psico_path:  Path to the SISE-psicología Excel file.
        registries_path:  Path to the cumulative registrations Excel file.
        psicologist_path: Path to the psychologist tracking Excel file.
        month:            Target month (1–12).
        year:             Target year.

    Returns:
        Fully processed DataFrame.
    """
    orientados  = clean_orientados(load_orientados(sise_psico_path))
    talleres    = clean_talleres(load_talleres(sise_psico_path))
    registrados = clean_registrados(load_registrados(registries_path))
    psicologas  = clean_psicologas(load_psicologas(psicologist_path))

    df = merge_all(orientados, talleres, registrados, psicologas)
    df = derive_age_range(df)
    df = run_all_classifications(df)
    df = final_string_clean(df)
    return df


def main():
    """
    Entry point when the script is run directly (or by Kestra).

    Reads MONTH and YEAR from environment variables, executes the full
    pipeline against the Kestra virtual paths, writes parquet output and
    count text files, and prints a summary.
    """
    month = int(os.getenv("MONTH"))
    year  = int(os.getenv("YEAR"))

    df = run_pipeline("sise_psico", "registries", "psicologist", month, year)

    print_summary(df, month, year)

    oriented  = filter_orientados_by_month(df, month, year)
    workshops = filter_talleres_by_month(df, month, year)
    export_df = filter_export(df, month, year)

    filename = export_parquet(export_df, month, year)

    num_oriented  = len(oriented)
    num_workshops = len(workshops)

    print(f"\nNumber of people attended by psychologist during {month}/{year}: {num_oriented}")
    write_count(num_oriented, "psico_count.txt")

    print(f"Number of people who attended workshops during {month}/{year}: {num_workshops}")
    write_count(num_workshops, "workshop_count.txt")

    print(f"Output written to: {filename}")


if __name__ == "__main__":
    main()