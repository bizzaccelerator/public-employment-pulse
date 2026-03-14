"""
test_integration_formacion.py
==============================
Integration tests for the formacion ETL pipeline.

WHAT THESE TESTS COVER (that unit tests cannot)
------------------------------------------------
  - run_pipeline() produces a DataFrame with the correct columns and row
    count when given real (fixture) Excel files from a mocked GCS source.
  - prepare_dataframe() maps every parquet column to the correct DB column
    — column mapping drift is caught here, not silently in production.
  - load_to_staging() writes the correct number of rows to PostgreSQL.
  - unique_row_id generation is deterministic and correct.
  - The MERGE operation inserts new rows into the main table.
  - Running the same data twice does NOT produce duplicate rows (idempotency).
  - Duplicate rows in the fixture are collapsed to a single DB row.
  - Both Excel files are combined and only common columns survive.
  - Classification results (vca, discapacidad, grupos_etnicos, migrante,
    vvg, reincorporados) survive the full round-trip Excel → Python → PG.

REQUIREMENTS
------------
  A running PostgreSQL instance reachable via environment variables:
    DB_HOST      (default: localhost)
    DB_PORT      (default: 5432)
    DB_NAME      (default: postgres)
    DB_USER      (default: postgres)
    DB_PASSWORD  (default: postgres)

  In GitHub Actions this is provided by the services.postgres container.
  Locally, run:
    docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15

GCS MOCKING STRATEGY
--------------------
  run_pipeline() calls ingest_from_gcs() which requires a live GCS
  filesystem.  In integration tests we bypass GCS entirely by patching
  ingest_from_gcs() with a local implementation (ingest_from_local_dir)
  that reads from a tmp directory — the same two-file fixture written by
  fixture_formacion.write_fixture_excels().

  This means:
    - No GCS credentials required in CI.
    - The fixture data is deterministic and version-controlled.
    - The full transformation chain (normalise → rename → clean → flags)
      still runs on real Excel files, not synthetic in-memory DataFrames.

ISOLATION STRATEGY
------------------
  Each test class gets its own uniquely-named pair of tables created in
  setup and destroyed in teardown.  Tests within a class share the tables;
  each test that writes data truncates the staging table first.
  This avoids cross-test contamination without full table recreation for
  every individual test.
"""

import os
import io
import glob as glob_mod
import hashlib
import pytest
import pandas as pd
import numpy as np
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Self-contained path resolution — no conftest.py required
# ---------------------------------------------------------------------------
# Resolves formacion and formacion_db_operations by their absolute paths
# relative to this file, so the test can be run from any working directory
# without PYTHONPATH exports, package __init__ files, or a conftest.py.
#
# Expected layout (adjust _WORKLOAD_DIR if yours differs):
#   <project>/
#     workload/
#       formacion.py
#     tests/
#       formacion_db_operations.py
#       test_integration_formacion.py   ← this file
# ---------------------------------------------------------------------------
import sys as _sys
_TESTS_DIR    = os.path.dirname(os.path.abspath(__file__))
_WORKLOAD_DIR = os.path.join(os.path.dirname(_TESTS_DIR), "workload")

for _p in (_TESTS_DIR, _WORKLOAD_DIR):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from code_used.snippets_support.workload.formacion import (
    resolve_sheet,
    normalize_column_names,
    RENAME_DICT,
    DATETIME_COLUMNS,
    cast_datetime_columns,
    clean_edad,
    lowercase_string_columns,
    clean_genero,
    add_population_flags,
    GENERO_MAPPING,
)
from code_used.snippets_support.tests.db_operations_formacion import (
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
# ===========================================================================
# Fixture data — inlined here because this is pure test infrastructure
# ===========================================================================
#
# Two Excel files are written to a temp directory once per session.
# They exercise every pipeline branch without requiring GCS access.
#
# FILE A — “INSCRITOS CURSO ATENCION AL CLIENTE POR MEDIOS TECNOLOGICOS.xlsx”
#   Sheet : "Matriculados ATENCION MEDIOS DI"  (matched by SHEET_MAP)
#   Row 0 : Jan 2025 | NARP              → grupos_etnicos
#   Row 1 : Jan 2025 | Discapacidad física → discapacidad
#   Row 2 : Jan 2025 | Conflicto armado  → vca
#   Row 3 : Jan 2025 | Permiso especial  → migrante
#   Row 4 : Feb 2025 | Víctima violencia → vvg
#   Row 5 : duplicate of Row 0           → idempotency
#   Extra column only in this file: "Indique el curso al que desea inscribirse"
#
# FILE B — “INSCRITOS CURSO BISUTERIA GRUPO 2.xlsx”
#   Sheet : "Hoja1"                            (matched by SHEET_MAP)
#   Row 0 : Jan 2025 | no flags
#   Row 1 : Jan 2025 | Reincorporación   → reincorporados
#   Row 2 : Feb 2025 | VVG keyword       → vvg
#   Extra column only in this file: "Localidad"
#
# The file-only columns verify the common-columns intersection logic.


def _make_row(
    tdoc, ndoc, nombres, apellidos, celular,
    email, edad, genero, fecha, formacion, discap, poblacion,
) -> dict:
    return {
        "Tipo de documento":                tdoc,
        "Numero de documento":              ndoc,
        "Nombres":                          nombres,
        "Apellidos":                        apellidos,
        "Celular":                          celular,
        "Correo electrónico @":             email,
        "Edad":                             edad,
        "Género":                           genero,
        "Fecha de registro":                fecha,
        "Último nivel de estudio aprobado": formacion,
        "¿Tiene alguna discapacidad?":      discap,
        "Tipo de población":                poblacion,
    }


_FILE_A_ROWS = [
    _make_row("CC",                              "111111", "Ana",    "Gómez",
              "3001111111", "ana@mail.com",   25, "Femenino",
              "15/01/2025", "Bachillerato",   "No aplica",
              "NARP (negro, afrocolombiano, raizal o palenquero)"),
    _make_row("CC",                              "222222", "Luis",   "Pérez",
              "3002222222", "luis@mail.com",  30, "Masculino",
              "20/01/2025", "Técnico",        "Discapacidad física",
              "Ninguna"),
    _make_row("CC",                              "333333", "Rosa",   "Ruiz",
              "3003333333", "rosa@mail.com",  45, "Femenino",
              "22/01/2025", "Universitario",  "No aplica",
              "Conflicto armado"),
    _make_row("Permiso especial de permanencia", "444444", "Pedro",  "Silva",
              "3004444444", "pedro@mail.com", 28, "Masculino",
              "25/01/2025", "Bachillerato",   "No aplica",
              "Ninguna"),
    _make_row("CC",                              "555555", "Laura",  "Torres",
              "3005555555", "laura@mail.com", 22, "Femenino",
              "10/02/2025", "Técnico",        "No aplica",
              "Víctima de violencia"),
    # Row 5 — exact duplicate of Row 0 (same identity key fields)
    _make_row("CC",                              "111111", "Ana",    "Gómez",
              "3001111111", "ana@mail.com",   25, "Femenino",
              "15/01/2025", "Bachillerato",   "No aplica",
              "NARP (negro, afrocolombiano, raizal o palenquero)"),
]

_FILE_B_ROWS = [
    _make_row("CC", "666666", "Carlos", "Mendoza",
              "3006666666", "carlos@mail.com", 35, "Masculino",
              "18/01/2025", "Técnico",        "No aplica", "Ninguna"),
    _make_row("CC", "777777", "Diana",  "Castro",
              "3007777777", "diana@mail.com",  29, "Femenino",
              "21/01/2025", "Bachillerato",    "No aplica",
              "Proceso de reincorporación FARC"),
    _make_row("CC", "888888", "Jorge",  "Vargas",
              "3008888888", "jorge@mail.com",  40, "Masculino",
              "12/02/2025", "Universitario",   "No aplica",
              "VVG registrada"),
]


def _write_fixture_files(dir_path: str) -> None:
    """Write both fixture Excel files into *dir_path*."""
    # --- File A ---
    df_a = pd.DataFrame(_FILE_A_ROWS)
    df_a["Indique el curso al que desea inscribirse"] = (
        ["Atención al cliente por medios tecnológicos"] * len(df_a)
    )
    buf_a = io.BytesIO()
    with pd.ExcelWriter(buf_a, engine="openpyxl") as w:
        # startrow=2 → header lands on sheet row 3 so skiprows=2 hits it
        df_a.to_excel(w, sheet_name="Matriculados ATENCION MEDIOS DI",
                      index=False, startrow=2)
    with open(os.path.join(
        dir_path,
        "INSCRITOS CURSO ATENCION AL CLIENTE POR MEDIOS TECNOLOGICOS.xlsx",
    ), "wb") as f:
        f.write(buf_a.getvalue())

    # --- File B ---
    df_b = pd.DataFrame(_FILE_B_ROWS)
    df_b["Localidad"] = ["Norte", "Centro", "Sur"]
    buf_b = io.BytesIO()
    with pd.ExcelWriter(buf_b, engine="openpyxl") as w:
        df_b.to_excel(w, sheet_name="Hoja1", index=False, startrow=2)
    with open(os.path.join(
        dir_path,
        "INSCRITOS CURSO BISUTERIA GRUPO 2.xlsx",
    ), "wb") as f:
        f.write(buf_b.getvalue())


# ===========================================================================
# Local ingestion helper (GCS bypass)
# ===========================================================================

def ingest_from_local_dir(
    dir_path: str,
    rename_dict: dict,
    skiprows: int = 2,
) -> pd.DataFrame:
    """
    Read every .xlsx file in *dir_path*, apply the same normalise + rename
    + common-columns-only logic as ingest_from_gcs(), without touching GCS.

    Used exclusively by integration test fixtures to replace the real GCS
    call with local file I/O so CI requires no GCS credentials.
    """
    paths = sorted(glob_mod.glob(os.path.join(dir_path, "*.xlsx")))
    if not paths:
        raise FileNotFoundError(f"No .xlsx files found in {dir_path}")

    dataframes, column_sets = [], []

    for path in paths:
        filename = os.path.basename(path)
        with open(path, "rb") as f:
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

        dataframes.append(df)
        column_sets.append(set(df.columns))

    common_columns = list(column_sets[0].intersection(*column_sets[1:]))
    if not common_columns:
        raise ValueError("No common columns found across fixture files.")

    return pd.concat(
        [df[common_columns] for df in dataframes],
        ignore_index=True,
    )


def run_pipeline_local(dir_path: str, month: int, year: int) -> pd.DataFrame:
    """
    Execute the full formacion transformation pipeline using local fixture
    files instead of GCS.  Identical to run_pipeline() except the ingestion
    step reads from *dir_path*.
    """
    df = ingest_from_local_dir(dir_path, RENAME_DICT)
    df = cast_datetime_columns(df, DATETIME_COLUMNS)
    df = clean_edad(df)
    df = lowercase_string_columns(df)
    df = clean_genero(df, GENERO_MAPPING)
    df = add_population_flags(df)
    df["mes"]  = month
    df["anio"] = year
    return df


# ===========================================================================
# Session-scoped fixtures
# ===========================================================================

@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory):
    """
    Write both fixture Excel files once per test session into a temp
    directory.  All integration tests share these files.
    """
    d = str(tmp_path_factory.mktemp("formacion_data"))
    _write_fixture_files(d)
    return d


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
# Table-scoped fixture (unique table names per test)
# ===========================================================================

@pytest.fixture
def tables(engine, request):
    """
    Per-test fixture: creates uniquely-named main + staging tables, yields
    their names, then drops them on teardown.

    Using the test node id as suffix guarantees no name collisions even
    when tests run in parallel.
    """
    suffix  = hashlib.md5(request.node.nodeid.encode()).hexdigest()[:8]
    table   = f"public.formacion_{suffix}"
    staging = f"public.formacion_{suffix}_staging"

    create_tables(engine, table, staging)
    yield table, staging
    drop_tables(engine, table, staging)


# ===========================================================================
# INTEGRATION-01: run_pipeline_local() output shape
# ===========================================================================

class TestPipelineOutput:
    """
    Verify run_pipeline_local() produces the correct DataFrame before any
    DB interaction.  These are integration tests (not unit tests) because
    they operate on real Excel files on disk, not synthetic in-memory fixtures.
    """

    def test_jan_2025_returns_correct_row_count(self, fixture_dir):
        """
        The pipeline ingests all rows from both files regardless of month
        and stamps every row with the requested mes/anio.
        File A: 6 rows (including 1 duplicate). File B: 3 rows. Total: 9.
        The pipeline does not filter by month — that is the caller's job.
        Deduplication happens in the DB MERGE, not here.
        """
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        assert len(df) == 9, (
            f"Expected 9 rows (6 from File A + 3 from File B), got {len(df)}"
        )

    def test_feb_2025_returns_correct_row_count(self, fixture_dir):
        """
        The pipeline ingests all rows from both files regardless of month.
        Running with month=2 still returns all 9 fixture rows — every row
        is stamped mes=2. Row count is identical to the January run.
        """
        df = run_pipeline_local(fixture_dir, month=2, year=2025)
        assert len(df) == 9, (
            f"Expected 9 rows regardless of month parameter, got {len(df)}"
        )

    def test_combined_output_contains_rows_from_both_files(self, fixture_dir):
        """
        The combined DataFrame must contain número_documento values
        from both File A (111111–555555) and File B (666666–888888).
        """
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        docs = set(df["numero_de_documento"].astype(str).tolist())
        assert "111111" in docs, "File A row not found in combined output"
        assert "666666" in docs, "File B row not found in combined output"

    def test_file_only_columns_excluded_from_output(self, fixture_dir):
        """
        'curso_inscrito' exists only in File A; 'localidad' only in File B.
        Neither should survive the common-columns-only intersection.
        """
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        assert "curso_inscrito" not in df.columns, (
            "'curso_inscrito' (File-A-only) should be dropped from combined output"
        )
        assert "localidad" not in df.columns, (
            "'localidad' (File-B-only) should be dropped from combined output"
        )

    def test_all_classification_columns_present(self, fixture_dir):
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        for col in ["grupos_etnicos", "vca", "discapacidad",
                    "migrante", "vvg", "reincorporados"]:
            assert col in df.columns, f"Missing classification column: {col}"

    def test_mes_and_anio_stamped(self, fixture_dir):
        df = run_pipeline_local(fixture_dir, month=3, year=2025)
        assert (df["mes"]  == 3).all(),    "mes column not stamped correctly"
        assert (df["anio"] == 2025).all(), "anio column not stamped correctly"

    def test_grupos_etnicos_classified(self, fixture_dir):
        """Row A-0 has NARP population → grupos_etnicos = 'Grupos etnicos'."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "111111"]
        assert len(row) >= 1, "Row 111111 not found"
        assert row.iloc[0]["grupos_etnicos"] == "Grupos etnicos", (
            f"Expected 'Grupos etnicos', got {row.iloc[0]['grupos_etnicos']!r}"
        )

    def test_discapacidad_fisica_classified(self, fixture_dir):
        """Row A-1 has 'Discapacidad física' → discapacidad = 'Física'."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "222222"]
        assert len(row) == 1, "Row 222222 not found"
        assert row.iloc[0]["discapacidad"] == "Física"

    def test_vca_classified_via_poblacion(self, fixture_dir):
        """Row A-2 has 'Conflicto armado' in tipo_de_población → vca = 'vca'."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "333333"]
        assert len(row) == 1, "Row 333333 not found"
        assert row.iloc[0]["vca"] == "vca"

    def test_migrante_classified_via_tipo_documento(self, fixture_dir):
        """Row A-3 has 'Permiso especial de permanencia' → migrante."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "444444"]
        assert len(row) == 1, "Row 444444 not found"
        assert row.iloc[0]["migrante"] == "Migrante o Retornado"

    def test_vvg_classified_via_poblacion(self, fixture_dir):
        """Row A-4 has 'Víctima de violencia' → vvg = 'vvg'."""
        df = run_pipeline_local(fixture_dir, month=2, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "555555"]
        assert len(row) == 1, "Row 555555 not found"
        assert row.iloc[0]["vvg"] == "vvg"

    def test_reincorporado_classified(self, fixture_dir):
        """Row B-1 has 'Proceso de reincorporación' → reincorporados."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "777777"]
        assert len(row) == 1, "Row 777777 not found"
        assert row.iloc[0]["reincorporados"] == "reincorporados"

    def test_vvg_classified_via_keyword_in_poblacion(self, fixture_dir):
        """Row B-2 has 'VVG registrada' in tipo_de_población → vvg = 'vvg'."""
        df = run_pipeline_local(fixture_dir, month=2, year=2025)
        row = df[df["numero_de_documento"].astype(str) == "888888"]
        assert len(row) == 1, "Row 888888 not found"
        assert row.iloc[0]["vvg"] == "vvg"

    def test_genero_normalised_to_single_char(self, fixture_dir):
        """After clean_genero(), gender values must be 'm', 'f', or 'i'."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        valid = {"m", "f", "i"}
        non_null = df["género"].dropna()
        unexpected = set(non_null.unique()) - valid
        assert not unexpected, (
            f"Unexpected gender values after normalisation: {unexpected}"
        )

    def test_edad_is_integer_type(self, fixture_dir):
        """clean_edad() must produce a nullable Int64 column."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        assert str(df["edad"].dtype) == "Int64", (
            f"edad should be Int64, got {df['edad'].dtype}"
        )

    def test_rango_de_edad_present_and_non_null_for_valid_ages(self, fixture_dir):
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        assert "rango_de_edad" in df.columns
        valid_ages = df[df["edad"].notna()]
        assert valid_ages["rango_de_edad"].notna().all(), (
            "Some rows with a valid edad are missing rango_de_edad"
        )


# ===========================================================================
# INTEGRATION-02: Column mapping and data preparation
# ===========================================================================

class TestColumnMapping:
    """
    Verify that prepare_dataframe() correctly maps every parquet column to
    its expected database column name.

    This catches the silent failure mode where a source column is renamed
    upstream and the mapping silently produces NULLs for an entire month.
    """

    def test_all_expected_columns_present_after_preparation(self, fixture_dir):
        """
        validate_columns() checks the full DB schema against whatever columns
        the pipeline produced. The fixture only includes a subset of raw Excel
        headers (12 shared columns), so optional columns like anexo_cedula,
        autorizacion_datos, barrio, etc. will be absent — that is expected.

        This test verifies that every column the fixture DOES produce is
        correctly mapped to its DB name with no drift. It also confirms that
        the mandatory identity and classification columns are all present.
        """
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())

        # Columns the fixture is guaranteed to produce after mapping
        mandatory = {
            "tipo_de_documento", "numero_de_documento", "nombres", "apellidos",
            "celular", "email", "edad", "rango_de_edad", "genero",
            "formacion", "tipo_discapacidad",
            "discapacidad", "grupos_etnicos", "vca", "migrante", "vvg",
            "reincorporados", "mes", "anio",
        }
        missing_mandatory = sorted(mandatory - set(prepared.columns))
        assert missing_mandatory == [], (
            f"Mandatory DB columns missing after mapping: {missing_mandatory}\n"
            f"Check COLUMN_MAPPING in formacion_db_operations.py."
        )

    def test_genero_accent_stripped_after_mapping(self, fixture_dir):
        """'género' (with accent) must map to 'genero' (without accent)."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        assert "genero"  in prepared.columns, "'genero' missing after mapping"
        assert "género" not in prepared.columns, "'género' still present after mapping"

    def test_date_columns_are_datetime_type(self, fixture_dir):
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in ["fecha_de_nacimiento", "fecha_de_registro"]:
            if col in prepared.columns and prepared[col].notna().any():
                assert pd.api.types.is_datetime64_any_dtype(prepared[col]), (
                    f"{col} should be datetime, got {prepared[col].dtype}"
                )

    def test_numeric_columns_are_numeric_type(self, fixture_dir):
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in ["mes", "anio"]:
            if col in prepared.columns:
                assert pd.api.types.is_numeric_dtype(prepared[col]), (
                    f"{col} should be numeric, got {prepared[col].dtype}"
                )

    def test_no_pd_na_remains_in_object_columns(self, fixture_dir):
        """
        SQLAlchemy requires Python None for NULL insertion.
        pd.NA in an object column causes insertion type errors.
        """
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in prepared.select_dtypes(include="object").columns:
            has_pd_na = prepared[col].apply(lambda x: x is pd.NA).any()
            assert not has_pd_na, (
                f"Column '{col}' contains pd.NA — should be None for SQL NULL"
            )

    def test_no_numpy_nan_in_object_columns(self, fixture_dir):
        """numpy NaN in a non-float column causes silent SQL insertion errors."""
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        prepared = prepare_dataframe(df.copy())
        for col in prepared.select_dtypes(include="object").columns:
            has_numpy_nan = prepared[col].apply(
                lambda x: isinstance(x, float) and np.isnan(x)
            ).any()
            assert not has_numpy_nan, (
                f"Column '{col}' contains numpy NaN — should be None"
            )


# ===========================================================================
# INTEGRATION-03: Database write operations
# ===========================================================================

class TestDatabaseLoad:
    """Verify that data moves correctly from Python into PostgreSQL."""

    def test_load_to_staging_inserts_correct_row_count(
        self, fixture_dir, engine, tables
    ):
        """
        The pipeline loads all 9 fixture rows (6 from File A + 3 from File B).
        File A row 5 is a duplicate of row 0 (same identity key fields),
        so staging deduplication removes 1 row → 8 unique rows remain.
        """
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        rows_loaded = load_to_staging(
            df, engine, staging, filename="fixture_2025_1"
        )
        assert rows_loaded == 8, (
            f"Expected 8 unique rows in staging after dedup, got {rows_loaded}"
        )

    def test_staging_table_row_count_matches_python_unique_rows(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            db_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {staging}")
            ).scalar()

        # Dedup key mirrors the SQL in load_to_staging (includes mes)
        unique_df = df.drop_duplicates(
            subset=["tipo_de_documento", "numero_de_documento",
                    "nombres", "apellidos", "fecha_de_registro", "mes"]
        )
        assert db_count == len(unique_df), (
            f"DB staging has {db_count} rows, expected {len(unique_df)} unique rows"
        )

    def test_unique_row_id_populated_after_load(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            null_count = conn.execute(text(
                f"SELECT COUNT(*) FROM {staging} WHERE unique_row_id IS NULL"
            )).scalar()

        assert null_count == 0, (
            f"{null_count} rows have NULL unique_row_id after load"
        )

    def test_unique_row_id_is_32_char_md5(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            bad_count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {staging}
                WHERE length(unique_row_id) != 32
            """)).scalar()

        assert bad_count == 0, (
            f"{bad_count} unique_row_id values are not 32-char MD5 hashes"
        )

    def test_filename_column_populated(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            filenames = [row[0] for row in conn.execute(
                text(f"SELECT DISTINCT filename FROM {staging}")
            )]

        assert filenames == ["fixture_2025_1"]

    def test_vca_value_survives_roundtrip(
        self, fixture_dir, engine, tables
    ):
        """VCA label must survive Python → PostgreSQL without alteration."""
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT vca, discapacidad, grupos_etnicos
                FROM {staging}
                WHERE numero_de_documento = '333333'
            """)).fetchone()

        assert row is not None, "Row 333333 not found in staging"
        assert row[0] == "vca",   f"vca: expected 'vca', got {row[0]!r}"
        assert row[1] is None,    f"discapacidad: expected None, got {row[1]!r}"

    def test_grupos_etnicos_value_survives_roundtrip(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT grupos_etnicos
                FROM {staging}
                WHERE numero_de_documento = '111111'
                LIMIT 1
            """)).fetchone()

        assert row is not None, "Row 111111 not found in staging"
        assert row[0] == "Grupos etnicos", (
            f"Expected 'Grupos etnicos', got {row[0]!r}"
        )

    def test_discapacidad_value_survives_roundtrip(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")

        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT discapacidad
                FROM {staging}
                WHERE numero_de_documento = '222222'
            """)).fetchone()

        assert row is not None, "Row 222222 not found in staging"
        assert row[0] == "Física", f"Expected 'Física', got {row[0]!r}"


# ===========================================================================
# INTEGRATION-04: MERGE deduplication (idempotency)
# ===========================================================================

class TestMergeDeduplication:
    """
    The most critical integration property: running the pipeline twice
    for the same month must not produce duplicate rows in the main table.
    """

    def test_merge_inserts_new_rows(
        self, fixture_dir, engine, tables
    ):
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        assert count > 0, "No rows inserted into main table after MERGE"

    def test_merge_is_idempotent(
        self, fixture_dir, engine, tables
    ):
        """
        Load and merge the same data twice.
        The main table must contain the same row count after both runs.
        """
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)

        # First load + merge
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            first_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        # Truncate staging and re-run with the same data
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))

        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            second_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()

        assert first_count == second_count, (
            f"MERGE is not idempotent: first run = {first_count} rows, "
            f"second run = {second_count} rows — duplicates were created."
        )

    def test_duplicate_row_in_fixture_not_double_inserted(
        self, fixture_dir, engine, tables
    ):
        """
        File A contains Row 5 which is an exact duplicate of Row 0
        (same tipo_de_documento, numero_de_documento, nombres, apellidos,
        fecha_de_registro).  After MERGE, numero_de_documento 111111 must
        appear exactly ONCE in the main table.
        """
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE numero_de_documento = '111111'
            """)).scalar()

        assert count == 1, (
            f"Duplicate row inserted: numero_de_documento 111111 "
            f"appears {count} times in main table (expected 1)"
        )

    def test_different_months_coexist_in_main_table(
        self, fixture_dir, engine, tables
    ):
        """
        Jan 2025 and Feb 2025 rows must both exist in the main table after
        two separate pipeline runs without overwriting each other.
        """
        table, staging = tables

        # Load January
        df_jan = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df_jan, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {staging}"))

        # Load February
        df_feb = run_pipeline_local(fixture_dir, month=2, year=2025)
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

    def test_second_file_rows_reach_main_table(
        self, fixture_dir, engine, tables
    ):
        """
        Rows that originated in File B (numero_de_documento 666666, 777777)
        must appear in the main table after a full load + merge cycle.
        This verifies the two-file concat path end-to-end.
        """
        table, staging = tables
        df = run_pipeline_local(fixture_dir, month=1, year=2025)
        load_to_staging(df, engine, staging, filename="fixture_2025_1")
        merge_staging_to_main(engine, table, staging)

        with engine.connect() as conn:
            count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE numero_de_documento IN ('666666', '777777')
            """)).scalar()

        assert count == 2, (
            f"Expected 2 File-B rows in main table, got {count}"
        )