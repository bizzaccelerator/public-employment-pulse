"""
db_operations_vacantes.py
=========================
Database operations for the vacantes (job postings) pipeline.

WHY THIS FILE EXISTS
--------------------
In the original pipeline the column mapping, type coercions, and staging
table load lived inside a Kestra `script:` block — inline YAML text that
cannot be imported or tested independently.

Extracting them here achieves two things:
  1. The Kestra 'load_data_to_staging' task can import and call
     load_to_staging() directly instead of duplicating the logic inline.
  2. Integration tests (test_integration_vacantes.py) can call the same
     functions against a real test database without going through Kestra.

COLUMN MAPPING CONTRACT
-----------------------
COLUMN_MAPPING is the single source of truth between the parquet column
names produced by vacantes.py and the PostgreSQL column names declared
in the CREATE TABLE statement.  Any drift between these two is caught
by the integration tests.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Column mapping: parquet name  →  database column name
# ---------------------------------------------------------------------------

COLUMN_MAPPING: dict[str, str] = {
    "código_proceso":     "codigo_proceso",
    "nombre_vacante":     "nombre_vacante",
    "cargo":              "cargo",
    "#_postulados":       "n_postulados",
    "empresa":            "empresa",
    "tipodocumentoempresa": "tipodocumentoempresa",
    "numerodocumentoempresa": "numerodocumentoempresa",
    "fecha_registro":     "fecha_registro",
    "fecha_vencimiento":  "fecha_vencimiento",
    "estado_actual":      "estado_actual",
    "tipo_de_vacante":    "tipo_de_vacante",
    "puestos_de_trabajo": "puestos_de_trabajo",
    "tipo_de_contrato":   "tipo_de_contrato",
    "agente_aprobó":      "agente_aprobo",
    "punto_atención":     "punto_atencion",
    "país":               "pais",
    "mes":                "mes",
    "año":                "anio",
}

# All DB column names the staging table expects (excluding auto-generated ones)
EXPECTED_DB_COLUMNS: set[str] = set(COLUMN_MAPPING.values())

# Date columns that require explicit datetime casting
DATE_COLUMNS: list[str] = ["fecha_registro", "fecha_vencimiento"]

# Numeric columns that require explicit coercion
NUMERIC_COLUMNS: list[str] = [
    "n_postulados", "numerodocumentoempresa", "puestos_de_trabajo",
    "mes", "anio",
]


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def make_engine(
    host: str | None = None,
    port: str | None = None,
    db: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> Engine:
    """
    Build a SQLAlchemy engine from explicit parameters or environment variables.

    Explicit parameters take priority; falls back to DB_HOST / DB_PORT /
    DB_NAME / DB_USER / DB_PASSWORD environment variables (matching the
    Kestra task's env: block).

    Args:
        host, port, db, user, password: Optional explicit connection details.

    Returns:
        SQLAlchemy Engine connected to PostgreSQL.
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
      1. Rename columns using COLUMN_MAPPING (unknown columns are kept as-is
         so nothing is silently dropped).
      2. Parse date columns to datetime.
      3. Coerce numeric columns to float (nullable).
      4. Stringify any list/array values (defensive — vacantes has none
         currently, but guards against upstream schema changes).
      5. Replace numpy NaN with None for proper SQL NULL insertion.

    Args:
        df: DataFrame as produced by vacantes.run_pipeline().

    Returns:
        DataFrame ready to be written to the staging table.
    """
    df = df.rename(columns=COLUMN_MAPPING)

    # --- date columns ---
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col], format="mixed", dayfirst=True, errors="coerce"
            )

    # --- numeric columns ---
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- list/array columns → string (defensive guard) ---
    for col in df.columns:
        if df[col].dtype == "object":
            if df[col].apply(lambda x: isinstance(x, (list, np.ndarray))).any():
                df[col] = df[col].apply(
                    lambda x: str(x) if isinstance(x, (list, np.ndarray)) else x
                )

    # --- numpy NaN → None (SQL NULL) ---
    df = df.replace({np.nan: None})

    return df


def validate_columns(df: pd.DataFrame) -> list[str]:
    """
    Return a list of expected DB columns that are missing from the DataFrame
    after renaming.

    An empty list means all expected columns are present.  A non-empty list
    means the column mapping is out of sync with the schema — the integration
    tests treat this as a hard failure.

    Args:
        df: DataFrame after prepare_dataframe() has been called.

    Returns:
        Sorted list of missing column names (empty if all present).
    """
    present = set(df.columns)
    return sorted(EXPECTED_DB_COLUMNS - present)


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id                    SERIAL PRIMARY KEY,
    codigo_proceso        VARCHAR(255),
    nombre_vacante        VARCHAR(255),
    cargo                 VARCHAR(255),
    n_postulados          INTEGER,
    empresa               VARCHAR(255),
    tipodocumentoempresa  VARCHAR(50),
    numerodocumentoempresa BIGINT,
    fecha_registro        TIMESTAMP,
    fecha_vencimiento     TIMESTAMP,
    estado_actual         VARCHAR(100),
    tipo_de_vacante       VARCHAR(100),
    puestos_de_trabajo    INTEGER,
    tipo_de_contrato      VARCHAR(100),
    agente_aprobo         VARCHAR(255),
    punto_atencion        VARCHAR(255),
    pais                  VARCHAR(100),
    mes                   INTEGER,
    anio                  INTEGER,
    unique_row_id         VARCHAR(32),
    filename              VARCHAR(255),
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
    codigo_proceso, nombre_vacante, cargo, n_postulados, empresa,
    tipodocumentoempresa, numerodocumentoempresa, fecha_registro,
    fecha_vencimiento, estado_actual, tipo_de_vacante, puestos_de_trabajo,
    tipo_de_contrato, agente_aprobo, punto_atencion, pais,
    mes, anio, created_at
  )
  VALUES (
    S.unique_row_id, S.filename,
    S.codigo_proceso, S.nombre_vacante, S.cargo, S.n_postulados, S.empresa,
    S.tipodocumentoempresa, S.numerodocumentoempresa, S.fecha_registro,
    S.fecha_vencimiento, S.estado_actual, S.tipo_de_vacante,
    S.puestos_de_trabajo, S.tipo_de_contrato, S.agente_aprobo,
    S.punto_atencion, S.pais, S.mes, S.anio, S.created_at
  );
"""


def create_tables(engine: Engine, table: str, staging_table: str) -> None:
    """
    Create the main and staging tables if they do not already exist.

    Args:
        engine:        SQLAlchemy engine.
        table:         Fully-qualified main table name  (e.g. 'public.vacantes').
        staging_table: Fully-qualified staging table name.
    """
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_SQL.format(table=table)))
        conn.execute(text(CREATE_TABLE_SQL.format(table=staging_table)))


def drop_tables(engine: Engine, table: str, staging_table: str) -> None:
    """
    Drop both tables unconditionally.  Used in test teardown.

    Args:
        engine:        SQLAlchemy engine.
        table:         Main table name.
        staging_table: Staging table name.
    """
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

    Mirrors the Kestra tasks in order:
      1. prepare_dataframe()  — rename + coerce types
      2. to_sql()             — load into staging
      3. UPDATE               — set unique_row_id and filename
         (mirrors 'data_table_add_unique_id_and_filename' Kestra task)
      4. DELETE duplicates    — keep MAX(id) per unique_row_id before MERGE

    WHY DEDUPLICATION IS NECESSARY
    --------------------------------
    PostgreSQL MERGE evaluates all source rows against the target snapshot
    taken at the START of the statement.  If two staging rows share the same
    unique_row_id and the target table is empty, both appear as NOT MATCHED
    simultaneously and both get inserted, defeating deduplication.

    This can happen when the same job posting appears twice in the monthly
    Excel extract, or when a vacancy is updated within the same month and
    the identity fields (empresa, cargo, tipo_de_contrato, fecha_registro)
    happen to be unchanged between versions.

    Fix: keep only the last-loaded row per unique_row_id (MAX(id)) before
    the MERGE executes.

    Args:
        df:            Monthly DataFrame from vacantes.run_pipeline().
        engine:        SQLAlchemy engine.
        staging_table: Target staging table (schema-qualified or bare name).
        filename:      Value written to the 'filename' column.

    Returns:
        Number of rows in staging after deduplication (the count offered
        to MERGE, not the raw input count).
    """
    prepared = prepare_dataframe(df.copy())

    # Keep only columns that exist in the DB schema
    db_cols  = [c for c in prepared.columns if c in EXPECTED_DB_COLUMNS]
    prepared = prepared[db_cols]

    # Infer schema prefix and bare table name for to_sql()
    if "." in staging_table:
        schema, bare = staging_table.split(".", 1)
    else:
        schema, bare = None, staging_table

    prepared.to_sql(
        bare,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=100,
    )

    # Step 2 – compute unique_row_id and filename (mirrors Kestra SQL task)
    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE {staging_table}
            SET
                unique_row_id = md5(
                    COALESCE(numerodocumentoempresa::text, '') ||
                    COALESCE(empresa,           '') ||
                    COALESCE(tipo_de_contrato,  '') ||
                    COALESCE(fecha_registro::text, '') ||
                    COALESCE(cargo,             '')
                ),
                filename = :filename
            WHERE unique_row_id IS NULL
        """), {"filename": filename})

    # Step 3 – deduplicate staging before MERGE reads it
    with engine.begin() as conn:
        conn.execute(text(f"""
            DELETE FROM {staging_table}
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM   {staging_table}
                GROUP BY unique_row_id
            )
        """))

    # Return post-dedup row count
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {staging_table}"))
        return result.scalar()


def merge_staging_to_main(
    engine: Engine,
    table: str,
    staging_table: str,
) -> None:
    """
    Merge new rows from staging into the main table using unique_row_id
    as the deduplication key.  Rows already present in the main table
    are not updated (insert-only MERGE).

    Args:
        engine:        SQLAlchemy engine.
        table:         Main table name.
        staging_table: Staging table name.
    """
    with engine.begin() as conn:
        conn.execute(text(MERGE_SQL.format(
            target=table,
            source=staging_table,
        )))