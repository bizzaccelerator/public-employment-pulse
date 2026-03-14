"""
formacion_db_operations.py
==========================
Database operations for the formacion ETL pipeline.

Mirrors the structure of db_operations.py (registro_hv) so the same
integration-test patterns apply to both pipelines.

WHY THIS FILE EXISTS
--------------------
The original Kestra 'load_data_to_staging' task embeds column mapping,
type coercions and SQL operations inside an inline YAML script: block
that cannot be imported or tested independently.

Extracting them here achieves two things:
  1. The Kestra task can call these functions instead of duplicating the
     logic inline (update the task's script: block to import and call
     load_to_staging() directly).
  2. Integration tests can call the same functions against a real test
     database without going through Kestra at all.

COLUMN MAPPING CONTRACT
-----------------------
COLUMN_MAPPING is the single source of truth between the parquet columns
produced by formacion.py and the PostgreSQL columns declared in CREATE TABLE.
Any drift between the two is caught by the integration tests, not silently
in production.
"""

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Column mapping: parquet name → database column name
# ---------------------------------------------------------------------------

COLUMN_MAPPING: dict[str, str] = {
    # Identity
    "tipo_de_documento":   "tipo_de_documento",
    "numero_de_documento": "numero_de_documento",
    "nombres":             "nombres",
    "apellidos":           "apellidos",
    "celular":             "celular",
    "email":               "email",
    # Demographics
    "edad":                "edad",
    "rango_de_edad":       "rango_de_edad",
    "género":              "genero",           # accent → no accent
    "direccion_residencia":"direccion_residencia",
    "localidad":           "localidad",
    "barrio":              "barrio",
    # Education & course
    "formacion":           "formacion",
    "curso_inscrito":      "curso_inscrito",
    "curso_de_interes":    "curso_de_interes",
    # Program metadata
    "autorizacion_datos":  "autorizacion_datos",
    "cursos_previos_co":   "cursos_previos_co",
    "anexo_cedula":        "anexo_cedula",
    # Dates
    "fecha_de_nacimiento": "fecha_de_nacimiento",
    "fecha_de_registro":   "fecha_de_registro",
    # Population flags
    "tipo_discapacidad":   "tipo_discapacidad",
    "discapacidad":        "discapacidad",
    "grupos_etnicos":      "grupos_etnicos",
    "vca":                 "vca",
    "migrante":            "migrante",
    "vvg":                 "vvg",
    "reincorporados":      "reincorporados",
    # Pipeline metadata
    "mes":                 "mes",
    "anio":                "anio",
}

# All DB column names the staging table expects (excluding auto-generated ones)
EXPECTED_DB_COLUMNS: set[str] = set(COLUMN_MAPPING.values())

# Date columns that require explicit casting
DATE_COLUMNS: list[str] = ["fecha_de_nacimiento", "fecha_de_registro"]

# Numeric columns
NUMERIC_COLUMNS: list[str] = ["edad", "mes", "anio"]


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def make_engine(
    host:     str | None = None,
    port:     str | None = None,
    db:       str | None = None,
    user:     str | None = None,
    password: str | None = None,
) -> Engine:
    """
    Build a SQLAlchemy engine from explicit parameters or environment variables.

    Explicit parameters take priority; falls back to DB_HOST / DB_PORT /
    DB_NAME / DB_USER / DB_PASSWORD environment variables (matching the
    Kestra task's env: block).
    """
    h  = host     or os.getenv("DB_HOST",     "localhost")
    p  = port     or os.getenv("DB_PORT",     "5432")
    d  = db       or os.getenv("DB_NAME",     "postgres")
    u  = user     or os.getenv("DB_USER",     "postgres")
    pw = password or os.getenv("DB_PASSWORD", "postgres")
    return create_engine(f"postgresql://{u}:{pw}@{h}:{p}/{d}")


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply column renaming, type coercions, and null normalisation so the
    DataFrame is ready for insertion into the staging table.

    Steps applied (in order):
      1. Rename columns using COLUMN_MAPPING (unknown columns are kept so
         nothing is silently dropped).
      2. Coerce date columns to datetime.
      3. Coerce numeric columns (edad, mes, anio) to numeric.
      4. Replace numpy NaN / pd.NA with None for proper SQL NULL insertion.

    Args:
        df: DataFrame as produced by formacion.run_pipeline().

    Returns:
        DataFrame ready to be written to the staging table.
    """
    df = df.rename(columns=COLUMN_MAPPING)

    # --- date columns ---
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # --- numeric columns ---
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- numpy NaN / pd.NA → None (SQL NULL) ---
    # pd.NA cannot be replaced by df.replace({np.nan: None}) alone, so we
    # use a two-pass approach: first replace np.nan, then convert pd.NA via
    # where on object columns.
    df = df.replace({np.nan: None})
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].where(df[col].notna(), other=None)

    return df


def validate_columns(df: pd.DataFrame) -> list[str]:
    """
    Return a list of expected DB columns that are missing from *df* after
    prepare_dataframe() has been called.

    An empty list means all expected columns are present.
    A non-empty list means the column mapping is out of sync with the schema.

    Args:
        df: DataFrame after prepare_dataframe().

    Returns:
        Sorted list of missing column names (empty if all present).
    """
    return sorted(EXPECTED_DB_COLUMNS - set(df.columns))


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id                    SERIAL PRIMARY KEY,
    -- Identity
    tipo_de_documento     VARCHAR(100),
    numero_de_documento   VARCHAR(50),
    nombres               VARCHAR(255),
    apellidos             VARCHAR(255),
    celular               VARCHAR(50),
    email                 VARCHAR(255),
    -- Demographics
    edad                  INTEGER,
    rango_de_edad         VARCHAR(50),
    genero                VARCHAR(10),
    direccion_residencia  VARCHAR(255),
    localidad             VARCHAR(255),
    barrio                VARCHAR(255),
    -- Education & course
    formacion             VARCHAR(255),
    curso_inscrito        VARCHAR(255),
    curso_de_interes      VARCHAR(255),
    -- Program metadata
    autorizacion_datos    TEXT,
    cursos_previos_co     VARCHAR(10),
    anexo_cedula          TEXT,
    -- Dates
    fecha_de_nacimiento   TIMESTAMP,
    fecha_de_registro     TIMESTAMP,
    -- Population flags
    tipo_discapacidad     VARCHAR(255),
    discapacidad          VARCHAR(100),
    grupos_etnicos        VARCHAR(100),
    vca                   VARCHAR(100),
    migrante              VARCHAR(100),
    vvg                   VARCHAR(100),
    reincorporados        VARCHAR(100),
    -- Pipeline metadata
    mes                   INTEGER,
    anio                  INTEGER,
    filename              VARCHAR(255),
    unique_row_id         VARCHAR(32),
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

MERGE_SQL = """
MERGE INTO {target} AS T
USING {source} AS S
    ON T.unique_row_id = S.unique_row_id
WHEN NOT MATCHED THEN
    INSERT (
        unique_row_id, filename,
        tipo_de_documento, numero_de_documento, nombres, apellidos,
        celular, email, edad, rango_de_edad, genero,
        direccion_residencia, localidad, barrio,
        formacion, curso_inscrito, curso_de_interes,
        autorizacion_datos, cursos_previos_co, anexo_cedula,
        fecha_de_nacimiento, fecha_de_registro,
        tipo_discapacidad, discapacidad, grupos_etnicos,
        vca, migrante, vvg, reincorporados,
        mes, anio, created_at
    )
    VALUES (
        S.unique_row_id, S.filename,
        S.tipo_de_documento, S.numero_de_documento, S.nombres, S.apellidos,
        S.celular, S.email, S.edad, S.rango_de_edad, S.genero,
        S.direccion_residencia, S.localidad, S.barrio,
        S.formacion, S.curso_inscrito, S.curso_de_interes,
        S.autorizacion_datos, S.cursos_previos_co, S.anexo_cedula,
        S.fecha_de_nacimiento, S.fecha_de_registro,
        S.tipo_discapacidad, S.discapacidad, S.grupos_etnicos,
        S.vca, S.migrante, S.vvg, S.reincorporados,
        S.mes, S.anio, S.created_at
    );
"""


def create_tables(engine: Engine, table: str, staging_table: str) -> None:
    """Create the main and staging tables if they do not already exist."""
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_SQL.format(table=table)))
        conn.execute(text(CREATE_TABLE_SQL.format(table=staging_table)))


def drop_tables(engine: Engine, table: str, staging_table: str) -> None:
    """Drop both tables unconditionally. Used in test teardown."""
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {staging_table}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


# ---------------------------------------------------------------------------
# Load pipeline
# ---------------------------------------------------------------------------

def load_to_staging(
    df: pd.DataFrame,
    engine: Engine,
    staging_table: str,
    filename: str,
) -> int:
    """
    Prepare the DataFrame and load it into the staging table.

    Also computes unique_row_id and filename in SQL after loading,
    mirroring the Kestra 'add_unique_id_and_filename' task.

    Deduplication strategy
    ----------------------
    PostgreSQL MERGE evaluates all source rows against the target snapshot
    taken at the START of the statement. If two staging rows share the same
    unique_row_id and the target is empty, both appear as NOT MATCHED and
    both get inserted, defeating deduplication.

    Fix: after computing unique_row_id, keep only MAX(id) per key before
    the MERGE runs.

    Args:
        df:            Monthly DataFrame from run_pipeline().
        engine:        SQLAlchemy engine.
        staging_table: Target staging table name.
        filename:      Value written to the 'filename' column.

    Returns:
        Number of rows in staging after deduplication (offered to MERGE).
    """
    prepared = prepare_dataframe(df.copy())

    # Keep only columns that exist in the DB schema
    db_cols = [c for c in prepared.columns if c in EXPECTED_DB_COLUMNS]
    prepared = prepared[db_cols]

    schema  = staging_table.split(".")[0] if "." in staging_table else None
    tbl_name = staging_table.split(".")[-1]

    prepared.to_sql(
        tbl_name,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )

    # Step 1: compute unique_row_id + set filename (mirrors Kestra task).
    # mes is included so the same person enrolled in different months
    # produces a distinct key and both rows survive the MERGE.
    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE {staging_table}
            SET
                unique_row_id = md5(
                    COALESCE(tipo_de_documento,   '') ||
                    COALESCE(numero_de_documento, '') ||
                    COALESCE(nombres,             '') ||
                    COALESCE(apellidos,           '') ||
                    COALESCE(fecha_de_registro::text, '') ||
                    COALESCE(mes::text,           '')
                ),
                filename = :filename
            WHERE unique_row_id IS NULL
        """), {"filename": filename})

    # Step 2: deduplicate staging — keep only the last-loaded row per key
    with engine.begin() as conn:
        conn.execute(text(f"""
            DELETE FROM {staging_table}
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM   {staging_table}
                GROUP BY unique_row_id
            )
        """))

    # Return post-dedup count: rows actually offered to MERGE
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM {staging_table}")
        ).scalar()


def merge_staging_to_main(
    engine: Engine,
    table: str,
    staging_table: str,
) -> None:
    """
    Merge new rows from staging into the main table using unique_row_id
    as the deduplication key. Insert-only — existing rows are not updated.
    """
    with engine.begin() as conn:
        conn.execute(text(MERGE_SQL.format(
            target=table,
            source=staging_table,
        )))