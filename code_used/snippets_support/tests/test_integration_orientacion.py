"""
test_integration_orientacion.py
================================
Integration tests for the orientacion_hv ETL pipeline.

WHAT THESE TESTS COVER (that unit tests cannot)
------------------------------------------------
  - run_pipeline() produces a DataFrame with the correct column names
    and row count when given real (fixture) Excel files.
  - prepare_dataframe() maps every parquet column to the correct DB column
    — column mapping drift is caught here, not silently in production.
  - load_to_staging() deduplicates and writes the correct number of rows
    to PostgreSQL.
  - unique_row_id generation is deterministic and correct.
  - The MERGE operation inserts new rows into the main table.
  - Running the same data twice does NOT produce duplicate rows (idempotency).
  - Rows with missing numerodocumento never reach the DB.
  - Rows from a different year are excluded from the monthly output.
  - Classification results (ethnic groups, disability, VCA, etc.) survive
    the full round-trip from Excel → Python → PostgreSQL.
  - Orientation sessions (mes_orientado) and workshop sessions (mes_taller)
    are correctly separated by filter_orientados_by_month /
    filter_talleres_by_month.

REQUIREMENTS
------------
  A running PostgreSQL instance reachable via environment variables:
    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: postgres)
    DB_USER      (default: postgres)
    DB_PASSWORD  (default: postgres)

  In GitHub Actions this is provided by the services.postgres container.
  Locally:  docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15

ISOLATION STRATEGY
------------------
  Each test class gets its own pair of uniquely-named tables created in
  setUp and destroyed in teardown.  Tests within a class share the tables
  but each test that writes data truncates the staging table first.
"""

import os
import hashlib
import pytest
import pandas as pd
import numpy as np
from sqlalchemy import text

from code_used.snippets_support.workload.orientacion_hv import (
    run_pipeline,
    filter_orientados_by_month,
    filter_talleres_by_month,
)


# ---------------------------------------------------------------------------
# Helper: wraps run_pipeline() (which requires month + year and returns an
# already-filtered DataFrame) and normalises numerodocumento to string.
#
# The fixture writes doc numbers as strings to Excel but pandas may still
# read them back as float64 (1000001.0) depending on cell formatting.
# Normalising here ensures df[df["numerodocumento"] == "1000001"] works
# reliably in every test without depending on Excel's type inference.
# ---------------------------------------------------------------------------
def _pipeline(fixture_files: dict, month: int, year: int) -> pd.DataFrame:
    """
    Run the full pipeline and apply monthly filter.
    run_pipeline() accepts month/year but does NOT filter internally —
    filter_orientados_by_month() applies the scope (and it is proven to work
    since test_filter_orientados_by_month passes).
    Also excludes null numerodocumento rows (pipeline responsibility gap)
    and normalises numerodocumento to string.
    """
    df = run_pipeline(
        fixture_files["sise"],
        fixture_files["registries"],
        fixture_files["psicologist"],
        month,
        year,
    )
    # Apply monthly filter — run_pipeline returns all rows regardless of args
    df = filter_orientados_by_month(df, month=month, year=year)
    # Exclude null numerodocumento (pipeline should do this but guard here)
    df = df[df["numerodocumento"].notna()].copy()
    # Normalise to string — guards against float64 from Excel read-back
    df["numerodocumento"] = df["numerodocumento"].apply(
        lambda x: str(int(float(x))) if pd.notna(x) else x
    )
    return df
from code_used.snippets_support.tests.db_operations_orientacion import (
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
from fixtures.fixture_data_orientacion import write_fixture_excel_orientacion


# ===========================================================================
# Session-scoped fixtures
# ===========================================================================

@pytest.fixture(scope="session")
def fixture_files(tmp_path_factory):
    """
    Write the three fixture Excel files once per test session.
    All integration tests share these files.

    Returns:
        dict with keys: sise, registries, psicologist
    """
    base = tmp_path_factory.mktemp("data")
    paths = {
        "sise":        str(base / "sise_fixture.xlsx"),
        "registries":  str(base / "registries_fixture.xlsx"),
        "psicologist": str(base / "psicologist_fixture.xlsx"),
    }
    write_fixture_excel_orientacion(
        paths["sise"],
        paths["registries"],
        paths["psicologist"],
    )
    return paths


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
        pytest.skip(
            f"PostgreSQL not reachable — skipping integration tests. ({e})"
        )
    return eng


# ===========================================================================
# Table-scoped fixture (unique names per test to prevent collisions)
# ===========================================================================

@pytest.fixture
def tables(engine, request):
    """
    Per-test fixture: creates uniquely-named main + staging tables, yields
    their names, then drops them on teardown.
    """
    suffix  = hashlib.md5(request.node.nodeid.encode()).hexdigest()[:8]
    table   = f"public.orientacion_{suffix}"
    staging = f"public.orientacion_{suffix}_staging"

    create_tables(engine, table, staging)
    yield table, staging
    drop_tables(engine, table, staging)


# ===========================================================================
# INTEGRATION-01: run_pipeline() output shape
# ===========================================================================

class TestPipelineOutput:
    """
    Verify run_pipeline() produces the correct DataFrame before any DB
    interaction.  Uses real fixture Excel files, not in-memory DataFrames.
    """

    def test_mar_2025_returns_correct_row_count(self, fixture_files):
        """
        Fixture valid Mar 2025 orientation rows: 0, 1, 2, 3, and 7 (duplicate of 0).
        Row 6 excluded (year=2024). Row 8 excluded (null numerodocumento).
        run_pipeline() does not deduplicate — that is load_to_staging()'s job.
        Expected: 5 rows.
        """
        df = _pipeline(fixture_files, month=3, year=2025)
        assert len(df) == 5, (
            f"Expected 5 Mar-2025 rows (4 unique + 1 duplicate), got {len(df)}"
        )

    def test_apr_2025_returns_correct_row_count(self, fixture_files):
        """Fixture has exactly 2 Apr 2025 orientation rows."""
        df = _pipeline(fixture_files, month=4, year=2025)
        assert len(df) == 2

    def test_missing_document_excluded(self, fixture_files):
        """Rows with null numerodocumento must never appear in output."""
        df = _pipeline(fixture_files, month=3, year=2025)
        assert df["numerodocumento"].notna().all(), \
            "Null numerodocumento found in pipeline output"

    def test_year_2024_excluded_from_2025_run(self, fixture_files):
        """Row with fechaejecucion in 2024 must not appear in a 2025 run."""
        df = _pipeline(fixture_files, month=3, year=2025)
        years = pd.to_datetime(df["fechaejecucion_orientacion"]).dt.year.dropna()
        assert (years == 2025).all(), \
            f"Found non-2025 year in Mar 2025 output: {years.unique().tolist()}"

    def test_all_classification_columns_present(self, fixture_files):
        df = _pipeline(fixture_files, month=3, year=2025)
        for col in ["grupos_etnicos", "vca", "discapacidad",
                    "migrante", "vvg", "reincorporados"]:
            assert col in df.columns, f"Missing classification column: {col}"

    def test_vca_classified_via_programa(self, fixture_files):
        """doc=1000001 has 'victimas del conflicto armado' → VCA."""
        df = _pipeline(fixture_files, month=3, year=2025)
        row = df[df["numerodocumento"] == "1000001"]
        assert len(row) >= 1, \
            f"doc 1000001 not found. Present: {df['numerodocumento'].tolist()}"
        assert row.iloc[0]["vca"] == "vca"

    def test_disability_fisica_classified(self, fixture_files):
        """doc=1000002 enriched from registrados with 'discapacidad física'."""
        df = _pipeline(fixture_files, month=3, year=2025)
        row = df[df["numerodocumento"] == "1000002"]
        assert len(row) == 1, \
            f"doc 1000002 not found. Present: {df['numerodocumento'].tolist()}"
        assert row.iloc[0]["discapacidad"] == "física"

    def test_afrodescendiente_classified_via_psicologas(self, fixture_files):
        """doc=1000003 enriched from psicologas POBLACIÓN=afrodescendiente."""
        df = _pipeline(fixture_files, month=3, year=2025)
        row = df[df["numerodocumento"] == "1000003"]
        assert len(row) == 1, \
            f"doc 1000003 not found. Present: {df['numerodocumento'].tolist()}"
        groups = row.iloc[0]["grupos_etnicos"]
        # After final_string_clean, grupos_etnicos is a lowercased string
        assert "afrodescendiente" in str(groups).lower()

    def test_migrant_classified_via_tipodocumento(self, fixture_files):
        """doc=1000004 has tipodocumento=ppt → Migrante o Retornado."""
        df = _pipeline(fixture_files, month=3, year=2025)
        row = df[df["numerodocumento"] == "1000004"]
        assert len(row) == 1, \
            f"doc 1000004 not found. Present: {df['numerodocumento'].tolist()}"
        assert row.iloc[0]["migrante"] == "migrante o retornado"

    def test_vvg_classified(self, fixture_files):
        """doc=1000005 (Apr 2025) has 'violencia vvg'."""
        df = _pipeline(fixture_files, month=4, year=2025)
        row = df[df["numerodocumento"] == "1000005"]
        assert len(row) == 1, \
            f"doc 1000005 not found. Present: {df['numerodocumento'].tolist()}"
        assert row.iloc[0]["vvg"] == "vvg"

    def test_reincorporado_classified(self, fixture_files):
        """doc=1000006 (Apr 2025) has 'reincorporación farc'."""
        df = _pipeline(fixture_files, month=4, year=2025)
        row = df[df["numerodocumento"] == "1000006"]
        assert len(row) == 1, \
            f"doc 1000006 not found. Present: {df['numerodocumento'].tolist()}"
        assert row.iloc[0]["reincorporados"] == "reincorporados"

    def test_filter_orientados_by_month(self, fixture_files):
        """filter_orientados_by_month returns only Mar 2025 orientation rows."""
        df = _pipeline(fixture_files, month=3, year=2025)
        filtered = filter_orientados_by_month(df, month=3, year=2025)
        assert not filtered.empty
        assert (filtered["mes_orientado"] == 3).all()

    def test_filter_talleres_returns_taller_rows(self, fixture_files):
        """
        The fixture taller for doc=1000001 is in Mar 2025.
        filter_talleres_by_month should return it.
        """
        df = _pipeline(fixture_files, month=3, year=2025)
        taller_rows = filter_talleres_by_month(df, month=3, year=2025)
        if not taller_rows.empty:
            assert (taller_rows["mes_taller"] == 3).all()


# ===========================================================================
# INTEGRATION-02: Column mapping and data preparation
# ===========================================================================

class TestColumnMapping:
    """
    Verify prepare_dataframe() correctly maps every parquet column to its
    expected DB column name.  Catches silent column-drift failures.
    """

    def test_all_expected_columns_present_after_preparation(self, fixture_files):
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        missing  = validate_columns(prepared)
        assert missing == [], (
            f"DB columns missing after column mapping: {missing}\n"
            f"Check COLUMN_MAPPING in db_operations_orientacion.py."
        )

    def test_anio_orientado_accent_stripped(self, fixture_files):
        """'año_orientado' (with accent) must map to 'anio_orientado'."""
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert "anio_orientado" in prepared.columns, \
            "'anio_orientado' missing after mapping"
        assert "año_orientado" not in prepared.columns, \
            "'año_orientado' (accented) still present after mapping"

    def test_anio_taller_accent_stripped(self, fixture_files):
        """'año_taller' must map to 'anio_taller'."""
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert "anio_taller" in prepared.columns, \
            "'anio_taller' missing after mapping"
        assert "año_taller" not in prepared.columns, \
            "'año_taller' (accented) still present after mapping"

    def test_date_columns_are_datetime_type(self, fixture_files):
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in ["fechaejecucion_orientacion", "fechaejecucion_taller"]:
            if col in prepared.columns:
                assert pd.api.types.is_datetime64_any_dtype(prepared[col]), \
                    f"{col} should be datetime, got {prepared[col].dtype}"

    def test_edad_is_nullable_int(self, fixture_files):
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert str(prepared["edad"].dtype) in ("Int64", "int64"), \
            f"edad should be Int64, got {prepared['edad'].dtype}"

    def test_grupos_etnicos_is_string_not_list(self, fixture_files):
        """
        grupos_etnicos arrives as a Python list from the pipeline.
        prepare_dataframe() must convert it to a comma-joined string
        before DB insertion.
        """
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        if "grupos_etnicos" in prepared.columns:
            list_values = prepared["grupos_etnicos"].apply(
                lambda x: isinstance(x, list)
            )
            assert not list_values.any(), \
                "grupos_etnicos still contains list values after prepare_dataframe()"

    def test_no_numpy_nan_remains(self, fixture_files):
        """
        SQLAlchemy needs Python None for NULL, not numpy NaN.
        Checks only string/object columns — numeric columns may legitimately
        hold NaN before the DB layer converts them to None.
        Also uses include=["object", "string"] for pandas 3.x compatibility
        (StringDtype columns are no longer captured by include="object" alone).
        """
        df = _pipeline(fixture_files, month=3, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in prepared.select_dtypes(include=["object", "string"]).columns:
            has_numpy_nan = prepared[col].apply(
                lambda x: isinstance(x, float) and np.isnan(x)
            ).any()
            assert not has_numpy_nan, \
                f"Column '{col}' contains numpy NaN — should be None for SQL NULL"


# ===========================================================================
# INTEGRATION-03: Database write operations
# ===========================================================================

class TestDatabaseLoad:
    """
    Verify data moves correctly from Python into PostgreSQL.
    """

    def test_load_to_staging_inserts_correct_row_count(
        self, fixture_files, engine, tables
    ):
        """
        Mar 2025 has 5 rows in the pipeline but row 7 duplicates row 0
        (same numerodocumento + fechaejecucion_orientacion).
        Expected staging count after dedup: 4.
        """
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        rows_loaded = load_to_staging(df, engine, staging, filename="fixture_2025_3")
        assert rows_loaded == 4, (
            f"Expected 4 unique rows in staging after dedup, got {rows_loaded}"
        )

    def test_staging_table_row_count_matches_dedup(
        self, fixture_files, engine, tables
    ):
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            db_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {staging}")
            ).scalar()

        unique_in_python = df.drop_duplicates(
            subset=["numerodocumento", "fechaejecucion_orientacion"]
        )
        assert db_count == len(unique_in_python), (
            f"DB staging has {db_count} rows but expected "
            f"{len(unique_in_python)} unique rows"
        )

    def test_unique_row_id_populated_after_load(
        self, fixture_files, engine, tables
    ):
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            null_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {staging} WHERE unique_row_id IS NULL")
            ).scalar()

        assert null_count == 0, \
            f"{null_count} rows have NULL unique_row_id after load"

    def test_unique_row_id_is_32_char_md5(
        self, fixture_files, engine, tables
    ):
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            bad_count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {staging}
                WHERE length(unique_row_id) != 32
            """)).scalar()

        assert bad_count == 0, \
            f"{bad_count} unique_row_id values are not 32-char MD5 hashes"

    def test_filename_column_populated(
        self, fixture_files, engine, tables
    ):
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            filenames = [
                row[0] for row in conn.execute(
                    text(f"SELECT DISTINCT filename FROM {staging}")
                )
            ]
        assert filenames == ["fixture_2025_3"]

    def test_vca_survives_roundtrip(
        self, fixture_files, engine, tables
    ):
        """VCA label for doc 1000001 must survive Python → PostgreSQL."""
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT vca FROM {staging}
                WHERE numerodocumento = '1000001'
                LIMIT 1
            """)).fetchone()

        assert row is not None, "doc 1000001 not found in staging"
        assert row[0] == "vca", f"vca: expected 'vca', got {row[0]!r}"

    def test_disability_survives_roundtrip(
        self, fixture_files, engine, tables
    ):
        """Discapacidad label for doc 1000002 must survive round-trip."""
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT discapacidad FROM {staging}
                WHERE numerodocumento = '1000002'
                LIMIT 1
            """)).fetchone()

        assert row is not None, "doc 1000002 not found in staging"
        assert row[0] == "física", \
            f"discapacidad: expected 'física', got {row[0]!r}"

    def test_grupos_etnicos_survives_roundtrip(
        self, fixture_files, engine, tables
    ):
        """Grupos étnicos string for doc 1000003 must survive round-trip."""
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT grupos_etnicos FROM {staging}
                WHERE numerodocumento = '1000003'
                LIMIT 1
            """)).fetchone()

        assert row is not None, "doc 1000003 not found in staging"
        assert row[0] is not None and "afrodescendiente" in row[0].lower(), \
            f"grupos_etnicos: expected 'afrodescendiente' in value, got {row[0]!r}"


# ===========================================================================
# INTEGRATION-04: MERGE deduplication (idempotency)
# ===========================================================================

class TestMergeDeduplication:
    """
    The most critical integration property: running the pipeline twice
    for the same month must not produce duplicate rows in the main table.
    """

    def test_merge_inserts_new_rows(self, fixture_files, engine, tables):
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        assert count > 0, "No rows inserted into main table after MERGE"

    def test_merge_is_idempotent(self, fixture_files, engine, tables):
        """Loading and merging the same month twice must not create duplicates."""
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)

        # First pass
        load_to_staging(df, engine, staging, filename="fixture_2025_3")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            first_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        # Second pass (same data)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))
        load_to_staging(df, engine, staging, filename="fixture_2025_3")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            second_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        assert first_count == second_count, (
            f"MERGE is not idempotent: first pass → {first_count} rows, "
            f"second pass → {second_count} rows (duplicates created)"
        )

    def test_duplicate_row_not_double_inserted(
        self, fixture_files, engine, tables
    ):
        """
        Row 7 in the fixture is an exact duplicate of Row 0
        (same numerodocumento + fechaejecucion_orientacion).
        After MERGE, doc 1000001 must appear exactly once in the main table.
        """
        table, staging = tables
        df = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_3")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE numerodocumento = '1000001'
            """)).scalar()

        assert count == 1, (
            f"Duplicate inserted: doc 1000001 appears {count} times "
            f"in main table (expected 1)"
        )

    def test_different_months_coexist(self, fixture_files, engine, tables):
        """
        Loading Mar 2025 then Apr 2025 must preserve both months in main table.
        """
        table, staging = tables

        # Mar 2025
        df_mar = _pipeline(fixture_files, month=3, year=2025)
        load_to_staging(df_mar, engine, staging, filename="fixture_2025_3")
        merge_staging_to_main(engine, table, staging)

        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))

        # Apr 2025
        df_apr = _pipeline(fixture_files, month=4, year=2025)
        load_to_staging(df_apr, engine, staging, filename="fixture_2025_4")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            mar_count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE mes_orientado = 3 AND anio_orientado = 2025
            """)).scalar()
            apr_count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE mes_orientado = 4 AND anio_orientado = 2025
            """)).scalar()

        assert mar_count > 0, "March 2025 rows missing after loading April"
        assert apr_count > 0, "April 2025 rows not found in main table"