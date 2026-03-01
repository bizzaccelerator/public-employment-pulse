"""
db_operations.py
================
Database operations extracted from the Kestra inline Python script
in the 'load_data_to_staging' task.

WHY THIS FILE EXISTS
--------------------
In the original pipeline the column mapping, type coercions, and
staging table load lived inside a Kestra `script:` block — inline YAML
text that cannot be imported or tested independently.

Extracting them here achieves two things:
  1. The Kestra task can now call these functions instead of duplicating
     the logic inline (update the task's script: block to import and
     call load_to_staging() directly).
  2. Integration tests can call the same functions against a real test
     database without going through Kestra at all.

COLUMN MAPPING CONTRACT
-----------------------
The mapping below is the single source of truth between the parquet
column names produced by registro_hv.py and the PostgreSQL column names
declared in the CREATE TABLE statement.  Any drift between these two
is caught by the integration tests.
"""

import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Column mapping: parquet name  →  database column name
# ---------------------------------------------------------------------------

COLUMN_MAPPING: dict[str, str] = {
    "no._":                                    "no",
    "programa_/_aliado\n(si_aplica)":          "programa_aliado",
    "barrio_donde_vive":                       "barrio_donde_vive",
    "tipo_documento":                          "tipo_documento",
    "número_documento":                        "numero_documento",
    "tipo_registro":                           "tipo_registro",
    "nombres":                                 "nombres",
    "apellidos":                               "apellidos",
    "celular":                                 "celular",
    "teléfono":                                "telefono",
    "canal_de_registro":                       "canal_de_registro",
    "edad":                                    "edad",
    "rango_edad":                              "rango_edad",
    "género":                                  "genero",
    "nivel_de_estudio":                        "nivel_de_estudio",
    "título_homologado":                       "titulo_homologado",
    "ciudad_de_residencia":                    "ciudad_de_residencia",
    "email":                                   "email",
    "fecha_registro":                          "fecha_registro",
    "programa_de_gobierno":                    "programa_de_gobierno",
    "condiciones_especiales":                  "condiciones_especiales",
    "detalle_discapacidades":                  "detalle_discapacidades",
    "situación_laboral":                       "situacion_laboral",
    "agente_registra":                         "agente_registra",
    "fecha_actualización":                     "fecha_actualizacion",
    "%_hoja_vida":                             "porcentaje_hoja_vida",
    "prestador_anterior":                      "prestador_anterior",
    "fecha_cambio_prestador":                  "fecha_cambio_prestador",
    "vereda/localidad/centro_poblado":         "vereda_localidad_centro_poblado",
    "pertenece_a":                             "pertenece_a",
    "sise_offline":                            "sise_offline",
    "mes":                                     "mes",
    "año":                                     "anio",
    "punto_atención":                          "punto_atencion",
    "fecha_accion":                            "fecha_accion",
    "grupos_etnicos":                          "grupos_etnicos",
    "vca":                                     "vca",
    "discapacidad":                            "discapacidad",
    "migrante":                                "migrante",
    "vvg":                                     "vvg",
    "reincorporados":                          "reincorporados",
}

# All DB column names the staging table expects (excluding auto-generated ones)
EXPECTED_DB_COLUMNS: set[str] = set(COLUMN_MAPPING.values())

# Date columns that require explicit casting
DATE_COLUMNS: list[str] = [
    "fecha_registro", "fecha_actualizacion",
    "fecha_cambio_prestador", "fecha_accion",
]

# Numeric columns
NUMERIC_COLUMNS: list[str] = ["edad", "anio", "no", "mes"]


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
    h = host     or os.getenv("DB_HOST",     "localhost")
    p = port     or os.getenv("DB_PORT",     "5432")
    d = db       or os.getenv("DB_NAME",     "postgres")
    u = user     or os.getenv("DB_USER",     "postgres")
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
      2. Coerce numero_documento to nullable Int64.
      3. Parse date columns to datetime.
      4. Coerce numeric columns to float (nullable).
      5. Stringify any list/array columns (grupos_etnicos arrives as a list).
      6. Replace numpy NaN with None for proper SQL NULL insertion.

    Args:
        df: DataFrame as produced by registro_hv.run_pipeline().

    Returns:
        DataFrame ready to be written to the staging table.
    """
    df = df.rename(columns=COLUMN_MAPPING)

    # --- numero_documento ---
    # After the clean_string_columns fix in registro_hv.py, this column
    # arrives as clean strings like "111111". pd.to_numeric handles both
    # "111111" and legacy "111111.0" safely, converting to Int64 (nullable).
    if "numero_documento" in df.columns:
        df["numero_documento"] = (
            pd.to_numeric(df["numero_documento"], errors="coerce")
            .astype("Int64")
        )

    # --- date columns ---
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="mixed", dayfirst=True, errors="coerce")

    # --- numeric columns ---
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- list columns → string (grupos_etnicos) ---
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
        List of missing column names (empty if all present).
    """
    present = set(df.columns)
    return sorted(EXPECTED_DB_COLUMNS - present)


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id                               SERIAL PRIMARY KEY,
    no                               INTEGER,
    programa_aliado                  VARCHAR(255),
    barrio_donde_vive                VARCHAR(255),
    tipo_documento                   VARCHAR(50),
    numero_documento                 BIGINT,
    tipo_registro                    VARCHAR(50),
    nombres                          VARCHAR(255),
    apellidos                        VARCHAR(255),
    celular                          VARCHAR(50),
    telefono                         VARCHAR(50),
    canal_de_registro                VARCHAR(100),
    edad                             INTEGER,
    rango_edad                       VARCHAR(50),
    genero                           VARCHAR(50),
    nivel_de_estudio                 VARCHAR(200),
    titulo_homologado                VARCHAR(255),
    ciudad_de_residencia             VARCHAR(200),
    email                            VARCHAR(255),
    fecha_registro                   TIMESTAMP,
    programa_de_gobierno             VARCHAR(255),
    condiciones_especiales           TEXT,
    detalle_discapacidades           TEXT,
    situacion_laboral                VARCHAR(200),
    agente_registra                  VARCHAR(255),
    fecha_actualizacion              TIMESTAMP,
    porcentaje_hoja_vida             VARCHAR(20),
    prestador_anterior               VARCHAR(255),
    fecha_cambio_prestador           TIMESTAMP,
    vereda_localidad_centro_poblado  VARCHAR(255),
    pertenece_a                      VARCHAR(100),
    sise_offline                     VARCHAR(50),
    mes                              INTEGER,
    anio                             INTEGER,
    punto_atencion                   VARCHAR(255),
    fecha_accion                     TIMESTAMP,
    grupos_etnicos                   VARCHAR(100),
    vca                              VARCHAR(100),
    discapacidad                     VARCHAR(100),
    migrante                         VARCHAR(100),
    vvg                              VARCHAR(100),
    reincorporados                   VARCHAR(100),
    unique_row_id                    VARCHAR(32),
    filename                         VARCHAR(255),
    created_at                       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

MERGE_SQL = """
MERGE INTO {target} AS T
USING {source} AS S
ON T.unique_row_id = S.unique_row_id
WHEN NOT MATCHED THEN
  INSERT (
    unique_row_id, filename, programa_aliado, barrio_donde_vive,
    tipo_documento, numero_documento, tipo_registro, nombres, apellidos,
    celular, telefono, canal_de_registro, edad, rango_edad, genero,
    nivel_de_estudio, titulo_homologado, ciudad_de_residencia, email,
    fecha_registro, programa_de_gobierno, condiciones_especiales,
    detalle_discapacidades, situacion_laboral, agente_registra,
    fecha_actualizacion, porcentaje_hoja_vida, prestador_anterior,
    fecha_cambio_prestador, vereda_localidad_centro_poblado, pertenece_a,
    sise_offline, mes, anio, punto_atencion, fecha_accion,
    grupos_etnicos, vca, discapacidad, migrante, vvg, reincorporados,
    created_at
  )
  VALUES (
    S.unique_row_id, S.filename, S.programa_aliado, S.barrio_donde_vive,
    S.tipo_documento, S.numero_documento, S.tipo_registro, S.nombres, S.apellidos,
    S.celular, S.telefono, S.canal_de_registro, S.edad, S.rango_edad, S.genero,
    S.nivel_de_estudio, S.titulo_homologado, S.ciudad_de_residencia, S.email,
    S.fecha_registro, S.programa_de_gobierno, S.condiciones_especiales,
    S.detalle_discapacidades, S.situacion_laboral, S.agente_registra,
    S.fecha_actualizacion, S.porcentaje_hoja_vida, S.prestador_anterior,
    S.fecha_cambio_prestador, S.vereda_localidad_centro_poblado, S.pertenece_a,
    S.sise_offline, S.mes, S.anio, S.punto_atencion, S.fecha_accion,
    S.grupos_etnicos, S.vca, S.discapacidad, S.migrante, S.vvg,
    S.reincorporados, S.created_at
  );
"""


def create_tables(engine: Engine, table: str, staging_table: str) -> None:
    """
    Create the main and staging tables if they do not already exist.

    Args:
        engine:        SQLAlchemy engine.
        table:         Fully-qualified main table name  (e.g. 'public.registro_hv').
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

    Also computes and sets unique_row_id and filename in SQL after loading,
    mirroring the Kestra 'data_table_add_unique_id_and_filename' task.

    Args:
        df:            Monthly DataFrame from run_pipeline().
        engine:        SQLAlchemy engine.
        staging_table: Target staging table name.
        filename:      Value written to the 'filename' column.

    Returns:
        Number of rows loaded.
    """
    prepared = prepare_dataframe(df.copy())

    # Keep only columns that exist in the DB schema
    db_cols = [c for c in prepared.columns if c in EXPECTED_DB_COLUMNS]
    prepared = prepared[db_cols]

    prepared.to_sql(
        staging_table.split(".")[-1],   # table name without schema prefix
        engine,
        schema=staging_table.split(".")[0] if "." in staging_table else None,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )

    # Step 1: compute unique_row_id and filename (mirrors Kestra task)
    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE {staging_table}
            SET
                unique_row_id = md5(
                    COALESCE(tipo_documento, '') ||
                    COALESCE(tipo_registro,  '') ||
                    COALESCE(nombres,        '') ||
                    COALESCE(fecha_registro::text, '') ||
                    COALESCE(celular,        '')
                ),
                filename = :filename
            WHERE unique_row_id IS NULL
        """), {"filename": filename})

    # Step 2: deduplicate staging before MERGE reads it.
    #
    # WHY THIS IS NECESSARY
    # ---------------------
    # PostgreSQL MERGE evaluates all source rows against the target snapshot
    # taken at the START of the statement. If two staging rows share the same
    # unique_row_id and the target table is empty, BOTH appear as NOT MATCHED
    # simultaneously and BOTH get inserted, defeating deduplication.
    #
    # This can happen in production when:
    #   - The same record appears twice in the monthly Excel extract
    #   - A person registers and updates their CV in the same month,
    #     producing identical identity-field values on two rows
    #
    # Fix: keep only the last-loaded row per unique_row_id (MAX(id))
    # before the MERGE executes.
    with engine.begin() as conn:
        conn.execute(text(f"""
            DELETE FROM {staging_table}
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM {staging_table}
                GROUP BY unique_row_id
            )
        """))

    # Return the post-dedup count — the number of rows that will actually
    # be offered to the MERGE, not the raw input count.
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