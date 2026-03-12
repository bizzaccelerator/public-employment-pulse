"""
test_integration_vacantes.py
============================
Integration tests for the vacantes pipeline.

These tests spin up real PostgreSQL tables, load synthetic data through
the exact same code path used in production (db_operations_vacantes.py),
and assert correctness of every stage:

  Layer 1 – prepare_dataframe()   : column renaming, type coercions
  Layer 2 – validate_columns()    : schema contract enforcement
  Layer 3 – load_to_staging()     : SQL write + unique_row_id + dedup
  Layer 4 – merge_staging_to_main(): MERGE correctness (insert-only)

WHY PYTEST HERE (vs the lightweight runner in integration_test_vacantes.py)
---------------------------------------------------------------------------
The lightweight custom runner is kept for the Kestra task that runs AFTER
real data has been loaded in production.  This file uses pytest because it
manages its own DB state (fixtures handle setup/teardown), so it can run
locally or in CI without a live Kestra execution.

REQUIREMENTS
------------
  pip install pytest pandas numpy sqlalchemy psycopg2-binary pyarrow

  Environment variables (or .env):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

  The DB user must have CREATE TABLE / DROP TABLE privileges on the
  target schema (default: public).
"""

from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from code_used.snippets_support.tests.db_operations_vacantes import (
    COLUMN_MAPPING,
    EXPECTED_DB_COLUMNS,
    create_tables,
    drop_tables,
    load_to_staging,
    make_engine,
    merge_staging_to_main,
    prepare_dataframe,
    validate_columns,
)

# ---------------------------------------------------------------------------
# Test table names (isolated from production tables)
# ---------------------------------------------------------------------------
TEST_TABLE         = "public.vacantes_test"
TEST_STAGING_TABLE = "public.vacantes_staging_test"
TEST_FILENAME      = "vacantes_2025_1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    """Single SQLAlchemy engine shared across all tests in this module."""
    return make_engine()


@pytest.fixture(scope="module")
def tables(engine):
    """
    Create test tables once before any test runs; drop them after all tests
    in the module complete.  Scoped to 'module' so the full test suite
    shares one setup/teardown cycle.
    """
    drop_tables(engine, TEST_TABLE, TEST_STAGING_TABLE)
    create_tables(engine, TEST_TABLE, TEST_STAGING_TABLE)
    yield
    drop_tables(engine, TEST_TABLE, TEST_STAGING_TABLE)


@pytest.fixture(autouse=True)
def clean_staging(engine, tables):
    """
    Truncate staging before each individual test so tests are independent.
    Main table is NOT truncated — merge tests depend on its accumulated state.
    """
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {TEST_STAGING_TABLE} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def sample_df():
    """
    Minimal realistic DataFrame as it arrives from vacantes.run_pipeline()
    — using parquet column names (pre-rename), matching COLUMN_MAPPING keys.
    Contains 3 rows to allow testing of dedup and merge logic.
    """
    return pd.DataFrame({
        "código_proceso":        ["V001", "V002", "V003"],
        "nombre_vacante":        ["Conductor", "Asesor Comercial", "Técnico de Sistemas"],
        "cargo":                 ["Conductor", "Asesor", "Técnico"],
        "#_postulados":          [3, 1, 5],
        "empresa":               ["Acme S.A.", "Beta Ltda.", "Gamma Corp"],
        "tipodocumentoempresa":  ["NIT", "NIT", "NIT"],
        "numerodocumentoempresa": [900111222, 900333444, 800555666],
        "fecha_registro":        [
            pd.Timestamp("2025-01-15"),
            pd.Timestamp("2025-01-20"),
            pd.Timestamp("2025-01-28"),
        ],
        "fecha_vencimiento":     [
            pd.Timestamp("2025-02-28"),
            pd.Timestamp("2025-02-28"),
            pd.Timestamp("2025-02-28"),
        ],
        "estado_actual":         ["activa", "activa", "activa"],
        "tipo_de_vacante":       ["privada", "privada", "pública"],
        "puestos_de_trabajo":    [1, 2, 1],
        "tipo_de_contrato":      ["término fijo", "indefinido", "obra labor"],
        "agente_aprobó":         ["agente1", "agente2", "agente3"],
        "punto_atención":        ["Centro", "Norte", "Sur"],
        "país":                  ["Colombia", "Colombia", "Colombia"],
        "mes":                   [1, 1, 1],
        "año":                   [2025, 2025, 2025],
    })


# ===========================================================================
# Layer 1 – prepare_dataframe()
# ===========================================================================

class TestPrepareDataframe:

    def test_columns_renamed_via_mapping(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        for src, dst in COLUMN_MAPPING.items():
            if src in sample_df.columns:
                assert dst in result.columns, (
                    f"Expected renamed column '{dst}' (from '{src}') not found"
                )

    def test_source_column_names_removed_after_rename(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        # Only assert on columns where the name actually changes.
        # Identity mappings (src == dst, e.g. 'nombre_vacante' → 'nombre_vacante')
        # are valid and will naturally appear in result.columns — that is correct
        # behaviour, not a rename failure.
        for src, dst in COLUMN_MAPPING.items():
            if src == dst:
                continue
            if src in sample_df.columns:
                assert src not in result.columns, (
                    f"Source column '{src}' should have been renamed to '{dst}' "
                    f"but is still present"
                )

    def test_fecha_registro_is_datetime(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert pd.api.types.is_datetime64_any_dtype(result["fecha_registro"]), (
            "fecha_registro must be datetime dtype after prepare_dataframe"
        )

    def test_fecha_vencimiento_is_datetime(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert pd.api.types.is_datetime64_any_dtype(result["fecha_vencimiento"])

    def test_n_postulados_is_numeric(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert pd.api.types.is_numeric_dtype(result["n_postulados"])

    def test_numerodocumentoempresa_is_numeric(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert pd.api.types.is_numeric_dtype(result["numerodocumentoempresa"])

    def test_mes_and_anio_are_numeric(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert pd.api.types.is_numeric_dtype(result["mes"])
        assert pd.api.types.is_numeric_dtype(result["anio"])

    def test_no_rows_lost(self, sample_df):
        result = prepare_dataframe(sample_df.copy())
        assert len(result) == len(sample_df)

    def test_numpy_nan_replaced_with_none(self):
        df = pd.DataFrame({
            "código_proceso":        ["V001"],
            "nombre_vacante":        [None],
            "cargo":                 [np.nan],
            "#_postulados":          [np.nan],
            "empresa":               ["Acme"],
            "tipodocumentoempresa":  ["NIT"],
            "numerodocumentoempresa": [np.nan],
            "fecha_registro":        [pd.NaT],
            "fecha_vencimiento":     [pd.NaT],
            "estado_actual":         [None],
            "tipo_de_vacante":       [None],
            "puestos_de_trabajo":    [np.nan],
            "tipo_de_contrato":      [None],
            "agente_aprobó":         [None],
            "punto_atención":        [None],
            "país":                  [None],
            "mes":                   [1],
            "año":                   [2025],
        })
        result = prepare_dataframe(df)
        # cargo (numeric after coerce) and empresa (string) are the safe checks
        assert result["empresa"].iloc[0] == "Acme"

    def test_list_column_converted_to_string(self):
        """Defensive: if a column ever arrives as a list, it must be stringified."""
        df = pd.DataFrame({
            "código_proceso":        ["V001"],
            "nombre_vacante":        ["Conductor"],
            "cargo":                 [["tag1", "tag2"]],   # list value
            "#_postulados":          [1],
            "empresa":               ["Acme"],
            "tipodocumentoempresa":  ["NIT"],
            "numerodocumentoempresa": [900111222],
            "fecha_registro":        [pd.Timestamp("2025-01-15")],
            "fecha_vencimiento":     [pd.Timestamp("2025-02-28")],
            "estado_actual":         ["activa"],
            "tipo_de_vacante":       ["privada"],
            "puestos_de_trabajo":    [1],
            "tipo_de_contrato":      ["indefinido"],
            "agente_aprobó":         ["agente1"],
            "punto_atención":        ["Centro"],
            "país":                  ["Colombia"],
            "mes":                   [1],
            "año":                   [2025],
        })
        result = prepare_dataframe(df)
        cargo_val = result["cargo"].iloc[0]
        assert isinstance(cargo_val, str), (
            f"List column should have been stringified, got {type(cargo_val)}"
        )


# ===========================================================================
# Layer 2 – validate_columns()
# ===========================================================================

class TestValidateColumns:

    def test_no_missing_columns_on_full_sample(self, sample_df):
        prepared = prepare_dataframe(sample_df.copy())
        missing  = validate_columns(prepared)
        assert missing == [], (
            f"All expected DB columns should be present, missing: {missing}"
        )

    def test_detects_missing_column(self, sample_df):
        prepared = prepare_dataframe(sample_df.copy())
        prepared = prepared.drop(columns=["empresa"])
        missing  = validate_columns(prepared)
        assert "empresa" in missing

    def test_returns_sorted_list(self, sample_df):
        prepared = prepare_dataframe(sample_df.copy())
        prepared = prepared.drop(columns=["empresa", "cargo"])
        missing  = validate_columns(prepared)
        assert missing == sorted(missing)

    def test_empty_list_when_all_present(self, sample_df):
        prepared = prepare_dataframe(sample_df.copy())
        assert validate_columns(prepared) == []


# ===========================================================================
# Layer 3 – load_to_staging()
# ===========================================================================

class TestLoadToStaging:

    def test_rows_loaded_to_staging(self, engine, tables, clean_staging, sample_df):
        count = load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        assert count == len(sample_df), (
            f"Expected {len(sample_df)} rows in staging, got {count}"
        )

    def test_unique_row_id_populated(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            nulls = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE unique_row_id IS NULL OR unique_row_id = ''"
            )).scalar()
        assert nulls == 0, f"Found {nulls} rows with missing unique_row_id"

    def test_unique_row_id_is_32_chars(self, engine, tables, clean_staging, sample_df):
        """MD5 hex digest is always exactly 32 characters."""
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            bad = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE LENGTH(unique_row_id) <> 32"
            )).scalar()
        assert bad == 0, f"Found {bad} unique_row_id values that are not 32 chars"

    def test_filename_populated(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            nulls = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE filename IS NULL OR filename = ''"
            )).scalar()
        assert nulls == 0, f"Found {nulls} rows with missing filename"

    def test_filename_value_correct(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            wrong = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE filename <> :fn"
            ), {"fn": TEST_FILENAME}).scalar()
        assert wrong == 0, f"Found {wrong} rows with incorrect filename"

    def test_deduplication_on_identical_keys(self, engine, tables, clean_staging, sample_df):
        """
        Loading the same DataFrame twice must result in only one copy per
        unique_row_id after deduplication inside load_to_staging().
        """
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        # Load a second time to create duplicates before dedup runs
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            dupes = conn.execute(text(f"""
                SELECT COUNT(*) FROM (
                    SELECT unique_row_id
                    FROM   {TEST_STAGING_TABLE}
                    GROUP  BY unique_row_id
                    HAVING COUNT(*) > 1
                ) AS d
            """)).scalar()
        assert dupes == 0, (
            f"Found {dupes} duplicate unique_row_id(s) after deduplication"
        )

    def test_no_negative_n_postulados(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            bad = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} WHERE n_postulados < 0"
            )).scalar()
        assert bad == 0, f"Found {bad} rows with negative n_postulados"

    def test_puestos_de_trabajo_positive(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            bad = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE puestos_de_trabajo IS NOT NULL AND puestos_de_trabajo <= 0"
            )).scalar()
        assert bad == 0, f"Found {bad} rows with zero or negative puestos_de_trabajo"

    def test_fecha_registro_in_valid_range(self, engine, tables, clean_staging, sample_df):
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            bad = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE} "
                f"WHERE fecha_registro < '2020-01-01' OR fecha_registro > NOW()"
            )).scalar()
        assert bad == 0, f"Found {bad} rows with fecha_registro outside [2020-01-01, now]"

    def test_returns_post_dedup_count(self, engine, tables, clean_staging, sample_df):
        count = load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        with engine.connect() as conn:
            actual = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_STAGING_TABLE}"
            )).scalar()
        assert count == actual, (
            f"load_to_staging returned {count} but table has {actual} rows"
        )


# ===========================================================================
# Layer 4 – merge_staging_to_main()
# ===========================================================================

class TestMergeStagingToMain:

    def _load_and_merge(self, engine, sample_df):
        """Helper: load sample data to staging then merge to main."""
        load_to_staging(sample_df.copy(), engine, TEST_STAGING_TABLE, TEST_FILENAME)
        merge_staging_to_main(engine, TEST_TABLE, TEST_STAGING_TABLE)

    def test_rows_appear_in_main_after_merge(self, engine, tables, clean_staging, sample_df):
        self._load_and_merge(engine, sample_df)
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TEST_TABLE}")).scalar()
        assert count == len(sample_df), (
            f"Expected {len(sample_df)} rows in main table after merge, got {count}"
        )

    def test_merge_is_idempotent(self, engine, tables, clean_staging, sample_df):
        """
        Running the full load+merge cycle twice must not insert duplicate rows
        into the main table — MERGE must skip rows already present.
        """
        self._load_and_merge(engine, sample_df)

        # Truncate staging and re-load the same data
        with engine.begin() as conn:
            conn.execute(text(
                f"TRUNCATE TABLE {TEST_STAGING_TABLE} RESTART IDENTITY CASCADE"
            ))
        self._load_and_merge(engine, sample_df)

        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TEST_TABLE}")).scalar()
        assert count == len(sample_df), (
            f"Idempotency failure: expected {len(sample_df)} rows but got {count} "
            f"after second merge (duplicates were inserted)"
        )

    def test_new_rows_added_on_second_merge(self, engine, tables, clean_staging, sample_df):
        """A genuinely new row (different identity fields) must be inserted."""
        self._load_and_merge(engine, sample_df)

        # Build a new row that is distinct from all three in sample_df
        new_row = pd.DataFrame({
            "código_proceso":        ["V999"],
            "nombre_vacante":        ["Gerente"],
            "cargo":                 ["Gerente"],
            "#_postulados":          [10],
            "empresa":               ["Nueva Empresa S.A."],
            "tipodocumentoempresa":  ["NIT"],
            "numerodocumentoempresa": [999888777],
            "fecha_registro":        [pd.Timestamp("2025-01-25")],
            "fecha_vencimiento":     [pd.Timestamp("2025-03-31")],
            "estado_actual":         ["activa"],
            "tipo_de_vacante":       ["privada"],
            "puestos_de_trabajo":    [1],
            "tipo_de_contrato":      ["indefinido"],
            "agente_aprobó":         ["agente4"],
            "punto_atención":        ["Occidente"],
            "país":                  ["Colombia"],
            "mes":                   [1],
            "año":                   [2025],
        })

        with engine.begin() as conn:
            conn.execute(text(
                f"TRUNCATE TABLE {TEST_STAGING_TABLE} RESTART IDENTITY CASCADE"
            ))
        load_to_staging(new_row, engine, TEST_STAGING_TABLE, TEST_FILENAME)
        merge_staging_to_main(engine, TEST_TABLE, TEST_STAGING_TABLE)

        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TEST_TABLE}")).scalar()
        assert count == len(sample_df) + 1, (
            f"Expected {len(sample_df) + 1} rows after inserting a new record, "
            f"got {count}"
        )

    def test_unique_row_id_present_in_main(self, engine, tables, clean_staging, sample_df):
        self._load_and_merge(engine, sample_df)
        with engine.connect() as conn:
            nulls = conn.execute(text(
                f"SELECT COUNT(*) FROM {TEST_TABLE} "
                f"WHERE unique_row_id IS NULL OR unique_row_id = ''"
            )).scalar()
        assert nulls == 0, f"Found {nulls} rows in main table with missing unique_row_id"

    def test_no_duplicates_in_main_after_merge(self, engine, tables, clean_staging, sample_df):
        self._load_and_merge(engine, sample_df)
        with engine.connect() as conn:
            dupes = conn.execute(text(f"""
                SELECT COUNT(*) FROM (
                    SELECT unique_row_id
                    FROM   {TEST_TABLE}
                    GROUP  BY unique_row_id
                    HAVING COUNT(*) > 1
                ) AS d
            """)).scalar()
        assert dupes == 0, (
            f"Found {dupes} duplicate unique_row_id(s) in main table after merge"
        )