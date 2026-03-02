"""
db_operations_orientacion.py
============================
Database helpers for the orientacion_hv integration test suite.

Mirrors the structure of db_operations.py (used by test_integration.py for
registro_hv) but is scoped exclusively to the orientacion schema:

  - Different column mapping   (orientacion has date pairs for orientacion +
                                taller, no fecha_registro / fecha_accion)
  - Different table DDL        (orientacion columns, not registro_hv columns)
  - Different MERGE key        (numerodocumento + fechaejecucion_orientacion)
  - Different unique_row_id    (hash of numerodocumento + fechaejecucion +
                                orientador + numerotelefono)

PUBLIC API
----------
  make_engine()                 → sqlalchemy.Engine
  prepare_dataframe(df)         → pd.DataFrame   (rename + coerce columns)
  validate_columns(df)          → list[str]       (missing DB column names)
  create_tables(engine, t, s)   → None
  drop_tables(engine, t, s)     → None
  load_to_staging(df, engine, staging, filename) → int  (rows loaded)
  merge_staging_to_main(engine, table, staging)  → None

CONSTANTS
---------
  COLUMN_MAPPING        parquet col → DB col
  EXPECTED_DB_COLUMNS   full list of non-generated DB columns
"""

import os
import hashlib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Column mapping: parquet output of orientacion_hv.py → PostgreSQL columns
# ---------------------------------------------------------------------------

COLUMN_MAPPING: dict[str, str] = {
    # Identifiers
    "numerodocumento":               "numerodocumento",
    "tipodocumento":                 "tipodocumento",

    # Orientation session dates
    "fechaagendamiento_orientacion": "fechaagendamiento_orientacion",
    "fechaejecucion_orientacion":    "fechaejecucion_orientacion",
    "fechaevaluacion_orientacion":   "fechaevaluacion_orientacion",
    "orientador":                    "orientador",
    "mes_orientado":                 "mes_orientado",
    "año_orientado":                 "anio_orientado",   # accent stripped

    # Workshop (taller) dates
    "fechaagendamiento_taller":      "fechaagendamiento_taller",
    "fechaejecucion_taller":         "fechaejecucion_taller",
    "fechaevaluacion_taller":        "fechaevaluacion_taller",
    "tallerista":                    "tallerista",
    "mes_taller":                    "mes_taller",
    "año_taller":                    "anio_taller",      # accent stripped

    # Service / programme metadata
    "indicador":                     "indicador",
    "tipodireccionamiento":          "tipodireccionamiento",
    "correoelectronico":             "correoelectronico",
    "primernombre":                  "primernombre",
    "segundonombre":                 "segundonombre",
    "primerapellido":                "primerapellido",
    "segundoapellido":               "segundoapellido",
    "sexo":                          "sexo",
    "ciudad":                        "ciudad",
    "departamento":                  "departamento",
    "area":                          "area",
    "tipo":                          "tipo",
    "subtipo":                       "subtipo",
    "nombreportafolio":              "nombreportafolio",
    "nombreconvocatoria":            "nombreconvocatoria",
    "aprobacion":                    "aprobacion",
    "porcentajeasistencia":          "porcentajeasistencia",
    "prestadornombre":               "prestadornombre",
    "institucionnombre":             "institucionnombre",
    "instituciondireccion":          "instituciondireccion",
    "institucionmunicipio":          "institucionmunicipio",
    "instituciondepartamento":       "instituciondepartamento",
    "programagobiernosino":          "programagobiernosino",
    "programagobierno":              "programagobierno",
    "alianzasentidadesexternas":     "alianzasentidadesexternas",
    "agencianombre":                 "agencianombre",
    "numerotelefono":                "numerotelefono",

    # Enrichment from registrados / psicologas
    "programa_de_gobierno":          "programa_de_gobierno",
    "condiciones_especiales":        "condiciones_especiales",
    "edad":                          "edad",
    "rango_de_edad":                 "rango_de_edad",

    # Population classification
    "grupos_etnicos":                "grupos_etnicos",
    "vca":                           "vca",
    "discapacidad":                  "discapacidad",
    "migrante":                      "migrante",
    "vvg":                           "vvg",
    "reincorporados":                "reincorporados",
}

# All columns that must be present in the prepared DataFrame before DB load.
# Excludes auto-generated columns: id, unique_row_id, filename, created_at.
EXPECTED_DB_COLUMNS: list[str] = list(COLUMN_MAPPING.values())


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def make_engine() -> Engine:
    """
    Build a SQLAlchemy engine from environment variables.

    Variables (with defaults for local development):
      DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    """
    host     = os.getenv("DB_HOST",     "localhost")
    port     = os.getenv("DB_PORT",     "5432")
    name     = os.getenv("DB_NAME",     "postgres")
    user     = os.getenv("DB_USER",     "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    return create_engine(
        f"postgresql://{user}:{password}@{host}:{port}/{name}",
        future=True,
    )


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename parquet columns to DB column names and coerce types.

    Steps:
      1. Rename via COLUMN_MAPPING (unknown columns are dropped).
      2. Cast 'edad', 'mes_orientado', 'anio_orientado', 'mes_taller',
         'anio_taller' to nullable Int64.
      3. Cast date columns to datetime.
      4. Convert list-valued 'grupos_etnicos' to comma-joined string.
      5. Replace numpy NaN with None in object/string columns.
         Uses a column-by-column approach because df.where(pd.notnull(df), None)
         silently no-ops on object dtype in pandas 2.x, leaving numpy NaN in
         place and causing SQLAlchemy type errors on insertion.
         Numeric and datetime columns are left untouched — their nullable types
         (Int64, datetime64) handle pd.NA / NaT correctly at the DB layer.

    Args:
        df: Raw parquet DataFrame from orientacion_hv.run_pipeline().

    Returns:
        DB-ready DataFrame.
    """
    # 1. Rename and drop unknown columns
    df = df.rename(columns=COLUMN_MAPPING)
    df = df[[c for c in EXPECTED_DB_COLUMNS if c in df.columns]]

    # 2. Integer columns
    int_cols = ["edad", "mes_orientado", "anio_orientado", "mes_taller", "anio_taller"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # 3. Datetime columns
    dt_cols = [
        "fechaagendamiento_orientacion", "fechaejecucion_orientacion",
        "fechaevaluacion_orientacion",   "fechaagendamiento_taller",
        "fechaejecucion_taller",         "fechaevaluacion_taller",
    ]
    for col in dt_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # 4. grupos_etnicos: list → comma-joined string (or None)
    if "grupos_etnicos" in df.columns:
        df["grupos_etnicos"] = df["grupos_etnicos"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else x
        )

    # 5. numpy NaN → None in object/string columns only.
    str_cols = df.select_dtypes(include=["object", "string", "str"]).columns
    for col in str_cols:
        df[col] = df[col].astype(object).where(df[col].notna(), other=None)

    return df


def validate_columns(df: pd.DataFrame) -> list[str]:
    """
    Return a list of expected DB columns that are absent from df.

    An empty list means the column mapping is complete.

    Args:
        df: DataFrame returned by prepare_dataframe().

    Returns:
        List of missing column names (empty = no drift detected).
    """
    return [c for c in EXPECTED_DB_COLUMNS if c not in df.columns]


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS {table} (
        id                             SERIAL PRIMARY KEY,
        numerodocumento                VARCHAR(50),
        tipodocumento                  VARCHAR(50),
        fechaagendamiento_orientacion  TIMESTAMP,
        fechaejecucion_orientacion     TIMESTAMP,
        fechaevaluacion_orientacion    TIMESTAMP,
        orientador                     VARCHAR(200),
        mes_orientado                  INTEGER,
        anio_orientado                 INTEGER,
        fechaagendamiento_taller       TIMESTAMP,
        fechaejecucion_taller          TIMESTAMP,
        fechaevaluacion_taller         TIMESTAMP,
        tallerista                     VARCHAR(200),
        mes_taller                     INTEGER,
        anio_taller                    INTEGER,
        indicador                      VARCHAR(100),
        tipodireccionamiento           VARCHAR(100),
        correoelectronico              VARCHAR(255),
        primernombre                   VARCHAR(100),
        segundonombre                  VARCHAR(100),
        primerapellido                 VARCHAR(100),
        segundoapellido                VARCHAR(100),
        sexo                           VARCHAR(20),
        ciudad                         VARCHAR(100),
        departamento                   VARCHAR(100),
        area                           VARCHAR(100),
        tipo                           VARCHAR(100),
        subtipo                        VARCHAR(100),
        nombreportafolio               VARCHAR(200),
        nombreconvocatoria             VARCHAR(200),
        aprobacion                     VARCHAR(50),
        porcentajeasistencia           NUMERIC(5,2),
        prestadornombre                VARCHAR(200),
        institucionnombre              VARCHAR(200),
        instituciondireccion           TEXT,
        institucionmunicipio           VARCHAR(100),
        instituciondepartamento        VARCHAR(100),
        programagobiernosino           VARCHAR(10),
        programagobierno               TEXT,
        alianzasentidadesexternas      TEXT,
        agencianombre                  VARCHAR(200),
        numerotelefono                 VARCHAR(30),
        programa_de_gobierno           TEXT,
        condiciones_especiales         TEXT,
        edad                           INTEGER,
        rango_de_edad                  VARCHAR(50),
        grupos_etnicos                 VARCHAR(200),
        vca                            VARCHAR(50),
        discapacidad                   VARCHAR(100),
        migrante                       VARCHAR(100),
        vvg                            VARCHAR(50),
        reincorporados                 VARCHAR(100),
        unique_row_id                  VARCHAR(32),
        filename                       VARCHAR(255),
        created_at                     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def create_tables(engine: Engine, table: str, staging: str) -> None:
    """
    Create main and staging tables if they do not already exist.

    Args:
        engine:  SQLAlchemy engine.
        table:   Fully-qualified main table name   (e.g. 'public.orientacion').
        staging: Fully-qualified staging table name (e.g. 'public.orientacion_staging').
    """
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL.format(table=table)))
        conn.execute(text(_TABLE_DDL.format(table=staging)))


def drop_tables(engine: Engine, table: str, staging: str) -> None:
    """
    Drop both tables unconditionally (used in test teardown).

    Args:
        engine:  SQLAlchemy engine.
        table:   Main table name.
        staging: Staging table name.
    """
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


# ---------------------------------------------------------------------------
# Load & merge
# ---------------------------------------------------------------------------

def _make_unique_row_id(row: pd.Series) -> str:
    """
    Build a deterministic 32-char MD5 hash that uniquely identifies an
    orientation record.

    Key fields:
      numerodocumento + fechaejecucion_orientacion + orientador + numerotelefono

    Args:
        row: A single DataFrame row.

    Returns:
        32-character hex MD5 string.
    """
    parts = [
        str(row.get("numerodocumento", "") or ""),
        str(row.get("fechaejecucion_orientacion", "") or ""),
        str(row.get("orientador", "") or ""),
        str(row.get("numerotelefono", "") or ""),
    ]
    return hashlib.md5("".join(parts).encode()).hexdigest()


def load_to_staging(
    df: pd.DataFrame,
    engine: Engine,
    staging: str,
    filename: str,
) -> int:
    """
    Prepare, deduplicate, annotate, and bulk-load a DataFrame to the
    staging table.

    Steps:
      1. prepare_dataframe() — rename columns, coerce types, replace NaN.
      2. Deduplicate on (numerodocumento, fechaejecucion_orientacion) so
         that upstream duplicates never reach the MERGE.
      3. Add 'unique_row_id' (MD5) and 'filename'.
      4. Truncate staging, then bulk-insert via to_sql().

    Args:
        df:       Raw pipeline output from orientacion_hv.run_pipeline().
        engine:   SQLAlchemy engine.
        staging:  Fully-qualified staging table name.
        filename: Source filename tag written to the 'filename' column.

    Returns:
        Number of rows actually loaded into staging after deduplication.
    """
    prepared = prepare_dataframe(df.copy())

    # Deduplicate: same person + same session date = same event
    prepared = prepared.drop_duplicates(
        subset=["numerodocumento", "fechaejecucion_orientacion"]
    )

    prepared["unique_row_id"] = prepared.apply(_make_unique_row_id, axis=1)
    prepared["filename"]      = filename

    schema, tname = staging.split(".", 1)

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {staging}"))

    prepared.to_sql(
        tname,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=200,
    )

    return len(prepared)


def merge_staging_to_main(engine: Engine, table: str, staging: str) -> None:
    """
    Merge rows from staging into the main table using INSERT … ON CONFLICT DO NOTHING.

    The conflict target is 'unique_row_id' (a unique index must exist on that
    column).  This guarantees idempotency: running the same month twice never
    produces duplicate rows.

    Note: the unique index is created here if it does not exist, so tests
    remain self-contained without requiring pre-seeded schema state.

    Args:
        engine:  SQLAlchemy engine.
        table:   Fully-qualified main table name.
        staging: Fully-qualified staging table name.
    """
    with engine.begin() as conn:
        # Ensure the unique constraint exists (idempotent DDL)
        index_name = table.replace(".", "_").replace("public_", "") + "_uq"
        conn.execute(text(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table} (unique_row_id)
        """))

        # Merge
        conn.execute(text(f"""
            INSERT INTO {table} (
                numerodocumento, tipodocumento,
                fechaagendamiento_orientacion, fechaejecucion_orientacion,
                fechaevaluacion_orientacion, orientador,
                mes_orientado, anio_orientado,
                fechaagendamiento_taller, fechaejecucion_taller,
                fechaevaluacion_taller, tallerista,
                mes_taller, anio_taller,
                indicador, tipodireccionamiento, correoelectronico,
                primernombre, segundonombre, primerapellido, segundoapellido,
                sexo, ciudad, departamento, area, tipo, subtipo,
                nombreportafolio, nombreconvocatoria, aprobacion,
                porcentajeasistencia, prestadornombre, institucionnombre,
                instituciondireccion, institucionmunicipio, instituciondepartamento,
                programagobiernosino, programagobierno, alianzasentidadesexternas,
                agencianombre, numerotelefono,
                programa_de_gobierno, condiciones_especiales,
                edad, rango_de_edad,
                grupos_etnicos, vca, discapacidad, migrante, vvg, reincorporados,
                unique_row_id, filename
            )
            SELECT
                numerodocumento, tipodocumento,
                fechaagendamiento_orientacion, fechaejecucion_orientacion,
                fechaevaluacion_orientacion, orientador,
                mes_orientado, anio_orientado,
                fechaagendamiento_taller, fechaejecucion_taller,
                fechaevaluacion_taller, tallerista,
                mes_taller, anio_taller,
                indicador, tipodireccionamiento, correoelectronico,
                primernombre, segundonombre, primerapellido, segundoapellido,
                sexo, ciudad, departamento, area, tipo, subtipo,
                nombreportafolio, nombreconvocatoria, aprobacion,
                porcentajeasistencia, prestadornombre, institucionnombre,
                instituciondireccion, institucionmunicipio, instituciondepartamento,
                programagobiernosino, programagobierno, alianzasentidadesexternas,
                agencianombre, numerotelefono,
                programa_de_gobierno, condiciones_especiales,
                edad, rango_de_edad,
                grupos_etnicos, vca, discapacidad, migrante, vvg, reincorporados,
                unique_row_id, filename
            FROM {staging}
            ON CONFLICT (unique_row_id) DO NOTHING
        """))