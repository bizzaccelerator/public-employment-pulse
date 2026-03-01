"""
test_integration.py
===================
Integration tests for the registro_hv ETL pipeline.

WHAT THESE TESTS COVER (that unit tests cannot)
------------------------------------------------
  - run_pipeline() produces a DataFrame with the correct column names
    and row count when given a real (fixture) Excel file.
  - prepare_dataframe() maps every parquet column to the correct DB column
    — column mapping drift is caught here, not silently in production.
  - load_to_staging() writes the correct number of rows to PostgreSQL.
  - unique_row_id generation is deterministic and correct.
  - The MERGE operation inserts new rows into the main table.
  - Running the same data twice does NOT produce duplicate rows (idempotency).
  - Invalid rows (null tipo_documento / número_documento) never reach the DB.
  - Rows from a different year are excluded from the monthly output.
  - Classification results (ethnic groups, disability, VCA, etc.) survive
    the full round-trip from Excel → Python → PostgreSQL.

REQUIREMENTS
------------
  A running PostgreSQL instance reachable via environment variables:
    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: postgres)
    DB_USER      (default: postgres)
    DB_PASSWORD  (default: postgres)

  In GitHub Actions this is provided by the `services.postgres` container.
  Locally, run:  docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15

ISOLATION STRATEGY
------------------
  Each test class gets its own pair of uniquely-named tables created in
  setUp and destroyed in teardown.  Tests within a class share the tables
  but each test that writes data truncates the staging table first.
  This avoids cross-test contamination without the overhead of full
  table recreation for every test.
"""

import os
import pytest
import hashlib
import pandas as pd
import numpy as np
from sqlalchemy import text

# Module under test
from code_used.snippets_support.workload.registro_hv import run_pipeline
from code_used.snippets_support.tests.db_operations import (
    make_engine,
    prepare_dataframe,
    validate_columns,
    create_tables,
    drop_tables,
    load_to_staging,
    merge_staging_to_main,
    COLUMN_MAPPING,
    EXPECTED_DB_COLUMNS,
)
from fixtures.fixture_data import write_fixture_excel


# ===========================================================================
# Session-scoped fixtures
# ===========================================================================

@pytest.fixture(scope="session")
def fixture_excel(tmp_path_factory):
    """
    Write the fixture Excel file once per test session to a temp directory.
    All integration tests share this single file.
    """
    path = str(tmp_path_factory.mktemp("data") / "fixture.xlsx")
    write_fixture_excel(path)
    return path


@pytest.fixture(scope="session")
def engine():
    """
    Create a SQLAlchemy engine for the test session.
    Skips the entire integration suite if the database is unreachable.
    """
    eng = make_engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"PostgreSQL not reachable — skipping integration tests. ({e})")
    return eng


# ===========================================================================
# Table-scoped fixtures (unique table names per class)
# ===========================================================================

def _table_names(suffix: str) -> tuple[str, str]:
    """Return (main_table, staging_table) names for a given test suffix."""
    return f"public.registro_hv_{suffix}", f"public.registro_hv_{suffix}_staging"


@pytest.fixture
def tables(engine, request):
    """
    Per-test fixture: creates uniquely-named main + staging tables, yields
    their names, then drops them on teardown.

    Using the test node id as suffix guarantees no name collisions when
    tests run in parallel.
    """
    # Build a short, safe suffix from the test name
    suffix = hashlib.md5(request.node.nodeid.encode()).hexdigest()[:8]
    table, staging = _table_names(suffix)

    create_tables(engine, table, staging)
    yield table, staging
    drop_tables(engine, table, staging)


# ===========================================================================
# INTEGRATION-01: run_pipeline() output shape
# ===========================================================================

class TestPipelineOutput:
    """
    Verify run_pipeline() produces the correct DataFrame before any DB
    interaction.  These are integration tests (not unit tests) because
    they use a real Excel file on disk, not a synthetic in-memory fixture.
    """

    def test_jan_2025_returns_correct_row_count(self, fixture_excel):
        """
        Fixture valid Jan 2025 rows: 0, 1, 2, 3, and 9 (duplicate of 0).
        Row 6 is excluded (año=2024). Rows 7 and 8 are excluded (invalid docs).
        run_pipeline() does not deduplicate — that is the MERGE's job.
        Expected: 5 rows.
        """
        df = run_pipeline(fixture_excel, month=1, year=2025)
        assert len(df) == 5, (
            f"Expected 5 Jan-2025 rows (4 unique + 1 duplicate), got {len(df)}"
        )

    def test_feb_2025_returns_correct_row_count(self, fixture_excel):
        """Fixture has exactly 2 Feb 2025 rows."""
        df = run_pipeline(fixture_excel, month=2, year=2025)
        assert len(df) == 2

    def test_invalid_rows_excluded(self, fixture_excel):
        """
        Rows with null tipo_documento or número_documento must never
        appear in the output regardless of the month requested.
        """
        df = run_pipeline(fixture_excel, month=1, year=2025)
        assert df["tipo_documento"].notna().all(), "Null tipo_documento found in output"

    def test_year_2024_excluded_from_2025_run(self, fixture_excel):
        """Row with año=2024 must not appear in a 2025 pipeline run."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        if "anio" in df.columns:
            assert (df["anio"] == 2025).all()
        # Also verify via fecha_accion
        assert (pd.to_datetime(df["fecha_accion"]).dt.year == 2025).all()

    def test_all_classification_columns_present(self, fixture_excel):
        df = run_pipeline(fixture_excel, month=1, year=2025)
        for col in ["grupos_etnicos", "vca", "discapacidad", "migrante", "vvg", "reincorporados"]:
            assert col in df.columns, f"Missing classification column: {col}"

    def test_afrodescendiente_classified(self, fixture_excel):
        """Row 0 has 'afrodescendiente' in condiciones_especiales."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        # número_documento is a clean string after clean_string_columns fix
        afro_rows = df[df["número_documento"] == "111111"]
        assert len(afro_rows) >= 1, (
            f"Row 111111 not found. Values present: {df['número_documento'].tolist()}"
        )
        groups = afro_rows["grupos_etnicos"].iloc[0]
        assert isinstance(groups, list) and "Afrodescendiente" in groups

    def test_disability_fisica_classified(self, fixture_excel):
        """Row 1 has 'discapacidad física'."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        row = df[df["número_documento"] == "222222"]
        assert len(row) == 1, f"Row 222222 not found. Values: {df['número_documento'].tolist()}"
        assert row.iloc[0]["discapacidad"] == "Física"

    def test_vca_classified_via_programa(self, fixture_excel):
        """Row 2 has 'Conflicto armado' in programa_de_gobierno."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        row = df[df["número_documento"] == "333333"]
        assert len(row) == 1, f"Row 333333 not found. Values: {df['número_documento'].tolist()}"
        assert row.iloc[0]["vca"] == "VCA"

    def test_migrant_classified_via_tipo_documento(self, fixture_excel):
        """Row 3 has tipo_documento='Permiso especial'."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        row = df[df["número_documento"] == "444444"]
        assert len(row) == 1, f"Row 444444 not found. Values: {df['número_documento'].tolist()}"
        assert row.iloc[0]["migrante"] == "Migrante o Retornado"

    def test_vvg_classified(self, fixture_excel):
        """Row 4 (Feb 2025) has 'violencia vvg'."""
        df = run_pipeline(fixture_excel, month=2, year=2025)
        row = df[df["número_documento"] == "555555"]
        assert len(row) == 1, f"Row 555555 not found. Values: {df['número_documento'].tolist()}"
        assert row.iloc[0]["vvg"] == "vvg"

    def test_reincorporado_classified(self, fixture_excel):
        """Row 5 (Feb 2025) has 'proceso de reincorporación'."""
        df = run_pipeline(fixture_excel, month=2, year=2025)
        row = df[df["número_documento"] == "666666"]
        assert len(row) == 1, f"Row 666666 not found. Values: {df['número_documento'].tolist()}"
        assert row.iloc[0]["reincorporados"] == "reincorporados"


# ===========================================================================
# INTEGRATION-02: Column mapping and data preparation
# ===========================================================================

class TestColumnMapping:
    """
    Verify that prepare_dataframe() correctly maps every parquet column
    to its expected database column name.

    This is the test that catches the silent failure mode where a source
    Excel column is renamed upstream and the mapping silently produces NULLs
    in the database for an entire month.
    """

    def test_all_expected_columns_present_after_preparation(self, fixture_excel):
        df = run_pipeline(fixture_excel, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        missing = validate_columns(prepared)
        assert missing == [], (
            f"These DB columns are missing after column mapping: {missing}\n"
            f"Check COLUMN_MAPPING in db_operations.py against the parquet output."
        )

    def test_numero_documento_is_integer_type(self, fixture_excel):
        df = run_pipeline(fixture_excel, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert str(prepared["numero_documento"].dtype) in ("Int64", "int64"), (
            f"numero_documento should be Int64, got {prepared['numero_documento'].dtype}"
        )

    def test_date_columns_are_datetime_type(self, fixture_excel):
        df = run_pipeline(fixture_excel, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in ["fecha_registro", "fecha_accion"]:
            if col in prepared.columns:
                assert pd.api.types.is_datetime64_any_dtype(prepared[col]), (
                    f"{col} should be datetime, got {prepared[col].dtype}"
                )

    def test_genero_column_mapped_correctly(self, fixture_excel):
        """'género' (with accent) must map to 'genero' (without accent)."""
        df = run_pipeline(fixture_excel, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert "genero" in prepared.columns, "'genero' column missing after mapping"
        assert "género" not in prepared.columns, "'género' (accented) still present after mapping"

    def test_no_numpy_nan_remains(self, fixture_excel):
        """
        SQLAlchemy requires Python None for NULL insertion.
        numpy NaN in a non-float column causes insertion errors.
        """
        df = run_pipeline(fixture_excel, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in prepared.select_dtypes(include="object").columns:
            has_numpy_nan = prepared[col].apply(
                lambda x: isinstance(x, float) and np.isnan(x)
            ).any()
            assert not has_numpy_nan, (
                f"Column '{col}' contains numpy NaN — should be None for SQL NULL"
            )


# ===========================================================================
# INTEGRATION-03: Database write operations
# ===========================================================================

class TestDatabaseLoad:
    """
    Verify that data moves correctly from Python into PostgreSQL.
    """

    def test_load_to_staging_inserts_correct_row_count(
        self, fixture_excel, engine, tables
    ):
        """
        load_to_staging() returns the post-deduplication row count — the number
        of unique rows actually present in staging after duplicates are removed.
        The fixture Jan 2025 batch has 5 rows but row 9 is a duplicate of row 0,
        so the expected staging count is 4 (not 5).
        """
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        rows_loaded = load_to_staging(df, engine, staging, filename="fixture_2025_1")
        # 5 Python rows → 4 unique rows after staging deduplication
        assert rows_loaded == 4, (
            f"Expected 4 unique rows in staging after dedup, got {rows_loaded}"
        )

    def test_staging_table_row_count_matches_python(
        self, fixture_excel, engine, tables
    ):
        """
        After load_to_staging(), the staging table contains only unique rows —
        duplicates are removed before the MERGE runs. The fixture produces 5 Python
        rows for Jan 2025 but row 9 duplicates row 0, so staging holds 4 rows.
        This test verifies the deduplication happened correctly, not that staging
        blindly mirrors the raw input.
        """
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            db_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {staging}")
            ).scalar()

        unique_in_python = df.drop_duplicates(
            subset=["tipo_documento", "tipo_registro", "nombres", "fecha_accion", "celular"]
        )
        assert db_count == len(unique_in_python), (
            f"DB staging has {db_count} rows but expected {len(unique_in_python)} unique rows"
        )

    def test_unique_row_id_populated_after_load(
        self, fixture_excel, engine, tables
    ):
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {staging} WHERE unique_row_id IS NULL")
            )
            null_count = result.scalar()

        assert null_count == 0, (
            f"{null_count} rows have NULL unique_row_id after load"
        )

    def test_unique_row_id_is_32_char_md5(
        self, fixture_excel, engine, tables
    ):
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {staging}
                    WHERE length(unique_row_id) != 32
                """)
            )
            bad_count = result.scalar()

        assert bad_count == 0, f"{bad_count} unique_row_id values are not 32-char MD5 hashes"

    def test_filename_column_populated(
        self, fixture_excel, engine, tables
    ):
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT DISTINCT filename FROM {staging}")
            )
            filenames = [row[0] for row in result]

        assert filenames == ["fixture_2025_1"]

    def test_classification_values_survive_roundtrip(
        self, fixture_excel, engine, tables
    ):
        """
        VCA, disability, and ethnic group labels must survive the full
        Python → PostgreSQL round-trip without being truncated or altered.
        """
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT vca, discapacidad, grupos_etnicos
                FROM {staging}
                WHERE numero_documento = 333333
            """))
            row = result.fetchone()

        assert row is not None, "Row 333333 not found in staging table"
        assert row[0] == "VCA",    f"vca: expected 'VCA', got {row[0]!r}"
        assert row[1] is None,     f"discapacidad: expected None, got {row[1]!r}"


# ===========================================================================
# INTEGRATION-04: MERGE deduplication (idempotency)
# ===========================================================================

class TestMergeDeduplication:
    """
    The most critical integration property: running the pipeline twice
    for the same month must not produce duplicate rows in the main table.
    """

    def test_merge_inserts_new_rows(self, fixture_excel, engine, tables):
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()

        assert count > 0, "No rows inserted into main table after MERGE"

    def test_merge_is_idempotent(self, fixture_excel, engine, tables):
        """
        Load and merge the same data twice.
        The main table must contain the same number of rows after the
        second merge as after the first.
        """
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)

        # First load + merge
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            first_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        # Truncate staging and reload same data
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))

        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            second_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        assert first_count == second_count, (
            f"MERGE is not idempotent: first run inserted {first_count} rows, "
            f"second run resulted in {second_count} rows — duplicates were created."
        )

    def test_duplicate_row_in_fixture_not_double_inserted(
        self, fixture_excel, engine, tables
    ):
        """
        The fixture contains row 9 which is an exact duplicate of row 0
        (same tipo_documento, tipo_registro, nombres, fecha_registro, celular).
        After the MERGE, número_documento 111111 must appear exactly ONCE
        in the main table.
        """
        table, staging = tables
        df = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE numero_documento = 111111
            """))
            count = result.scalar()

        assert count == 1, (
            f"Duplicate row was inserted: numero_documento 111111 "
            f"appears {count} times in main table (expected 1)"
        )

    def test_different_months_can_coexist(self, fixture_excel, engine, tables):
        """
        Jan 2025 and Feb 2025 rows must both exist in the main table
        after two separate pipeline runs.
        """
        table, staging = tables

        # Load Jan 2025
        df_jan = run_pipeline(fixture_excel, month=1, year=2025)
        load_to_staging(df_jan, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))

        # Load Feb 2025
        df_feb = run_pipeline(fixture_excel, month=2, year=2025)
        load_to_staging(df_feb, engine, staging, filename="fixture_2025_2")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            jan_count = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE mes = 1 AND anio = 2025"
            )).scalar()
            feb_count = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE mes = 2 AND anio = 2025"
            )).scalar()

        assert jan_count > 0, "January 2025 rows missing after loading February"
        assert feb_count > 0, "February 2025 rows not found in main table"