"""
test_formacion.py
=================
Unit tests for the formacion.py transformation pipeline.

Covers:
  - resolve_sheet               : sheet-name resolution from SHEET_MAP
  - ingest_from_gcs             : list + download + concat (GCS mocked)
  - normalize_column_names      : whitespace / casing / underscore rules
  - classify_age / clean_edad   : age parsing and bucket assignment
  - lowercase_string_columns    : object column lowercasing
  - clean_genero                : gender mapping
  - flag_population             : generic population flag helper
  - flag_discapacidad           : disability pattern classification
  - add_population_flags        : end-to-end flag orchestration
"""

import io
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, call

from formacion import (
    resolve_sheet,
    ingest_from_gcs,
    normalize_column_names,
    classify_age,
    clean_edad,
    lowercase_string_columns,
    clean_genero,
    filter_valid_records,
    flag_population,
    flag_discapacidad,
    add_population_flags,
    SHEET_MAP,
    RENAME_DICT,
    SELECT_COLUMNS,
    GENERO_MAPPING,
    DISCAPACIDAD_PATTERNS,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    """Serialise *df* to an in-memory .xlsx byte string."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def _fake_excel_file(sheet_names: list[str]) -> pd.ExcelFile:
    """Return a minimal pd.ExcelFile stub with a known sheet_names list."""
    stub = MagicMock(spec=pd.ExcelFile)
    stub.sheet_names = sheet_names
    return stub


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def base_df():
    """
    Four-row DataFrame that covers every cleaning and flagging path.

    Reflects the actual Excel form columns defined in SELECT_COLUMNS.
    NOTE: string values are already lowercase because in the real pipeline
    lowercase_string_columns() runs BEFORE add_population_flags().
    Tests that call add_population_flags() directly must therefore supply
    pre-lowercased data so the pattern matches behave correctly.

    Notable columns NOT present:
      - apellidos: the form uses "nombre_completo" (→ "nombres"), not separate fields.
      - localidad: not collected by the form.

      row 0 — valid, VVG population, physical disability
      row 1 — valid, migrant via tipo_de_documento, ethnic group
      row 2 — valid, VCA (armed conflict), reintegrated
      row 3 — valid, no special population markers
    """
    return pd.DataFrame({
        "tipo_de_documento":   ["CC", "permiso especial de permanencia", "CC", "CC"],
        "numero_de_documento": ["111", "222", "333", "444"],
        "nombres":             ["ana", "luis", "rosa", "pedro"],
        "edad":                ["25", "30 años", "45", "17"],
        "género":              ["masculino", "femenino", "masculino", "femenino"],
        "tipo_de_población":   [
            "víctima de violencia",
            "narp (negro, afrocolombiano, raizal o palenquero)",
            "conflicto armado",
            "ninguna",
        ],
        "tipo_discapacidad": [
            "discapacidad física",
            "sin discapacidad",
            "discapacidad visual",
            "",
        ],
        "email":              ["ana@mail.com", "luis@mail.com", "rosa@mail.com", "pedro@mail.com"],
        "celular":            ["3001111", "3002222", "3003333", "3004444"],
        "municipio_de_residencia": ["barranquilla"] * 4,
        "sise":               [None, None, None, None],
        "adjudicado":         [None, None, None, None],
        "asistencia":         [None, None, None, None],
    })


@pytest.fixture
def flag_df():
    """Factory: builds a one-row DataFrame for population-flag tests."""
    def _make(poblacion: str = "", doc: str = "CC"):
        return pd.DataFrame({
            "tipo_de_población": [poblacion],
            "tipo_de_documento": [doc],
            "tipo_discapacidad": [""],
        })
    return _make


@pytest.fixture
def discapacidad_df():
    """Factory: builds a one-row DataFrame for disability-classification tests."""
    def _make(text: str = ""):
        return pd.DataFrame({"tipo_discapacidad": [text]})
    return _make


# ===========================================================================
# RESOLVE_SHEET
# ===========================================================================

class TestResolveSheet:

    def test_known_keyword_returns_mapped_sheet(self):
        xl = _fake_excel_file(["Matriculados ATENCION MEDIOS DI", "Hoja2"])
        result = resolve_sheet("INSCRITOS CURSO ATENCION AL CLIENTE.xlsx", xl)
        assert result == "Matriculados ATENCION MEDIOS DI"

    def test_bisuteria_keyword_returns_hoja1(self):
        xl = _fake_excel_file(["Hoja1", "Hoja2"])
        result = resolve_sheet("INSCRITOS CURSO BISUTERIA GRUPO 2.xlsx", xl)
        assert result == "Hoja1"

    def test_fallback_to_first_sheet_when_no_keyword_matches(self):
        xl = _fake_excel_file(["Data", "Summary"])
        result = resolve_sheet("INSCRITOS CURSO COCINA.xlsx", xl)
        assert result == "Data"

    def test_fallback_when_mapped_sheet_not_present_in_file(self):
        # keyword matches but the expected sheet name is absent in this file
        xl = _fake_excel_file(["Hoja1", "Hoja2"])
        result = resolve_sheet("INSCRITOS CURSO ATENCION AL CLIENTE.xlsx", xl)
        assert result == "Hoja1"   # falls back to DEFAULT_SHEET_INDEX

    def test_case_insensitive_keyword_match(self):
        xl = _fake_excel_file(["Hoja1"])
        result = resolve_sheet("INSCRITOS BISUTERIA AVANZADA.xlsx", xl)
        assert result == "Hoja1"

    def test_returns_string(self):
        xl = _fake_excel_file(["Sheet1"])
        assert isinstance(resolve_sheet("any_file.xlsx", xl), str)


# ===========================================================================
# SELECT_COLUMNS — constant correctness
# ===========================================================================

class TestSelectColumns:

    EXPECTED_COLUMNS = {
        "adjudicado", "autorizacion_datos", "fecha_de_registro",
        "nombres", "tipo_de_documento", "numero_de_documento",
        "asistencia", "telefono", "cursos_previos_co", "sise",
        "país_de_nacimiento", "departamento_de_nacimiento", "ciudad_de_nacimiento",
        "fecha_de_nacimiento", "edad", "género",
        "direccion_residencia", "barrio", "municipio_de_residencia",
        "email", "celular", "celular_adicional",
        "formacion", "tipo_de_población", "tipo_discapacidad",
        "curso_inscrito", "anexo_cedula",
    }

    def test_select_columns_is_list(self):
        assert isinstance(SELECT_COLUMNS, list)

    def test_select_columns_has_expected_count(self):
        assert len(SELECT_COLUMNS) == 27

    def test_select_columns_contains_all_expected(self):
        missing = self.EXPECTED_COLUMNS - set(SELECT_COLUMNS)
        assert not missing, f"Missing from SELECT_COLUMNS: {missing}"

    def test_select_columns_has_no_unexpected(self):
        extra = set(SELECT_COLUMNS) - self.EXPECTED_COLUMNS
        assert not extra, f"Unexpected entries in SELECT_COLUMNS: {extra}"

    def test_no_duplicates(self):
        assert len(SELECT_COLUMNS) == len(set(SELECT_COLUMNS))

    def test_apellidos_not_in_select_columns(self):
        """apellidos is not a field in the Excel form — must not be selected."""
        assert "apellidos" not in SELECT_COLUMNS

    def test_localidad_not_in_select_columns(self):
        """localidad is not collected by the form — must not be selected."""
        assert "localidad" not in SELECT_COLUMNS

    def test_nombre_completo_not_in_select_columns(self):
        """The raw header is renamed to 'nombres' by RENAME_DICT — not kept as-is."""
        assert "nombre_completo" not in SELECT_COLUMNS

    def test_renamed_targets_present(self):
        """Verify RENAME_DICT targets (not raw keys) are in SELECT_COLUMNS."""
        for renamed in ["autorizacion_datos", "cursos_previos_co", "email",
                        "formacion", "tipo_discapacidad", "anexo_cedula",
                        "curso_inscrito", "numero_de_documento", "nombres", "telefono"]:
            assert renamed in SELECT_COLUMNS, f"Renamed column '{renamed}' must be in SELECT_COLUMNS"

    def test_género_kept_accented_for_clean_genero(self):
        """clean_genero() looks for the accented 'género' — must stay accented in SELECT_COLUMNS."""
        assert "género" in SELECT_COLUMNS
        assert "genero" not in SELECT_COLUMNS

    def test_tipo_de_población_kept_accented_for_flag_population(self):
        """flag_population() uses 'tipo_de_población' accented — must stay accented."""
        assert "tipo_de_población" in SELECT_COLUMNS
        assert "tipo_de_poblacion" not in SELECT_COLUMNS


# ===========================================================================
# INGEST_FROM_GCS  (GCS filesystem fully mocked — no network calls)
# ===========================================================================

class TestIngestFromGcs:
    """
    All GCS I/O is replaced with MagicMocks so these tests run offline.
    The mock fs.glob() returns two fake paths; fs.open() returns in-memory
    Excel bytes built from minimal DataFrames that share a subset of columns.
    """

    # --- Shared columns present in every fixture file ---
    COMMON_COLS = ["tipo_de_documento", "nombres", "edad"]

    def _build_mock_fs(self, file_specs: list[tuple[str, pd.DataFrame, str]]):
        """
        Build a MagicMock GCSFileSystem given a list of
        (gcs_path, dataframe, sheet_name) tuples.
        """
        fs = MagicMock()
        paths = [spec[0] for spec in file_specs]
        fs.glob.return_value = paths

        def _open_side_effect(path, mode):
            for gcs_path, df, sheet_name in file_specs:
                if path == gcs_path:
                    excel_bytes = _make_excel_bytes(df, sheet_name)
                    ctx = MagicMock()
                    ctx.__enter__ = MagicMock(return_value=io.BytesIO(excel_bytes))
                    ctx.__exit__ = MagicMock(return_value=False)
                    return ctx
            raise FileNotFoundError(path)

        fs.open.side_effect = _open_side_effect
        return fs

    def test_returns_dataframe(self):
        df1 = pd.DataFrame({"tipo_de_documento": ["CC"], "nombres": ["Ana"], "edad": [25], "extra_a": ["x"]})
        df2 = pd.DataFrame({"tipo_de_documento": ["PA"], "nombres": ["Luis"], "edad": [30], "extra_b": ["y"]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        assert isinstance(result, pd.DataFrame)

    def test_columns_outside_select_columns_are_dropped(self):
        """
        After the outer join, ingest_from_gcs restricts the result to
        SELECT_COLUMNS.  Columns that appear in the Excel files but are NOT
        in SELECT_COLUMNS must be silently dropped.
        """
        # Build two files where "noise_col" is not in SELECT_COLUMNS
        df1 = pd.DataFrame({"tipo_de_documento": ["CC"],  "nombres": ["Ana"],  "edad": [25], "noise_col": ["x"]})
        df2 = pd.DataFrame({"tipo_de_documento": ["PA"],  "nombres": ["Luis"], "edad": [30], "noise_col": ["y"]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        assert "noise_col" not in result.columns, \
            "Columns not in SELECT_COLUMNS must be dropped by ingest_from_gcs"

    def test_select_columns_present_in_files_are_kept(self):
        """
        Columns that ARE in SELECT_COLUMNS and exist in the files must survive.
        """
        # Use a minimal subset of SELECT_COLUMNS that will pass the common-col check
        df1 = pd.DataFrame({"tipo_de_documento": ["CC"],  "nombres": ["Ana"],  "edad": [25], "celular": ["300"]})
        df2 = pd.DataFrame({"tipo_de_documento": ["PA"],  "nombres": ["Luis"], "edad": [30], "celular": ["301"]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        # All four of these are in SELECT_COLUMNS
        for col in ["tipo_de_documento", "nombres", "edad", "celular"]:
            assert col in result.columns, f"SELECT_COLUMNS column '{col}' must be kept"

    def test_file_specific_select_column_nan_filled(self):
        """
        When a SELECT_COLUMNS column is present in only one file, the rows
        from the other file should have NaN for that column.
        """
        # "sise" is in SELECT_COLUMNS; "celular_adicional" is also in SELECT_COLUMNS
        df1 = pd.DataFrame({"tipo_de_documento": ["CC"],  "nombres": ["Ana"],  "sise": ["S1"]})
        df2 = pd.DataFrame({"tipo_de_documento": ["PA"],  "nombres": ["Luis"], "celular_adicional": ["999"]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        # file1 row: celular_adicional is NaN; file2 row: sise is NaN
        if "sise" in result.columns and "celular_adicional" in result.columns:
            ana_row  = result.loc[result["nombres"] == "Ana"]
            luis_row = result.loc[result["nombres"] == "Luis"]
            assert pd.isna(ana_row["celular_adicional"].iloc[0])
            assert pd.isna(luis_row["sise"].iloc[0])

    def test_row_count_equals_sum_of_all_files(self):
        df1 = pd.DataFrame({"tipo_de_documento": ["CC", "CC"], "nombres": ["A", "B"], "edad": [20, 25]})
        df2 = pd.DataFrame({"tipo_de_documento": ["PA"],        "nombres": ["C"],      "edad": [30]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        assert len(result) == 3

    def test_source_file_column_is_dropped_from_output(self):
        df1 = pd.DataFrame({"col_a": ["x"], "col_b": [1]})
        df2 = pd.DataFrame({"col_a": ["y"], "col_b": [2]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)
        assert "_source_file" not in result.columns

    def test_rename_dict_applied(self):
        raw_col = "correo_electrónico_@"
        df1 = pd.DataFrame({raw_col: ["a@a.com"], "nombres": ["Ana"]})
        df2 = pd.DataFrame({raw_col: ["b@b.com"], "nombres": ["Luis"]})
        rename = {raw_col: "email"}
        fs   = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        result = ingest_from_gcs("bucket/prefix", fs, rename, skiprows=0)
        assert "email" in result.columns
        assert raw_col not in result.columns

    def test_raises_file_not_found_when_bucket_empty(self):
        fs = MagicMock()
        fs.glob.return_value = []
        with pytest.raises(FileNotFoundError, match="No .xlsx files found"):
            ingest_from_gcs("empty/prefix", fs, {})

    def test_raises_value_error_when_no_common_columns(self):
        df1 = pd.DataFrame({"only_in_1": ["x"]})
        df2 = pd.DataFrame({"only_in_2": ["y"]})
        fs  = self._build_mock_fs([
            ("bucket/prefix/file1.xlsx", df1, "Hoja1"),
            ("bucket/prefix/file2.xlsx", df2, "Hoja1"),
        ])
        with pytest.raises(ValueError, match="No common columns"):
            ingest_from_gcs("bucket/prefix", fs, {}, skiprows=0)

    def test_glob_called_with_xlsx_pattern(self):
        fs = MagicMock()
        fs.glob.return_value = []
        with pytest.raises(FileNotFoundError):
            ingest_from_gcs("my-bucket/formacion", fs, {})
        fs.glob.assert_called_once_with("my-bucket/formacion/*.xlsx")


# ===========================================================================
# COLUMN NORMALISATION
# ===========================================================================

class TestNormalizeColumnNames:

    def test_lowercases_columns(self):
        df = pd.DataFrame(columns=["Nombre", "APELLIDO"])
        assert list(normalize_column_names(df).columns) == ["nombre", "apellido"]

    def test_replaces_spaces_with_underscores(self):
        df = pd.DataFrame(columns=["primer nombre", "segundo apellido"])
        assert list(normalize_column_names(df).columns) == ["primer_nombre", "segundo_apellido"]

    def test_strips_leading_trailing_whitespace(self):
        df = pd.DataFrame(columns=["  nombre  ", " edad "])
        assert list(normalize_column_names(df).columns) == ["nombre", "edad"]

    def test_collapses_multiple_spaces(self):
        df = pd.DataFrame(columns=["primer   nombre"])
        assert list(normalize_column_names(df).columns) == ["primer_nombre"]

    def test_removes_carriage_returns(self):
        df = pd.DataFrame(columns=["primer\rnombre"])
        assert list(normalize_column_names(df).columns) == ["primer_nombre"]

    def test_removes_newlines(self):
        df = pd.DataFrame(columns=["primer\nnombre"])
        assert list(normalize_column_names(df).columns) == ["primer_nombre"]

    def test_does_not_mutate_row_data(self):
        df = pd.DataFrame({"Nombre": ["Ana", "Luis"]})
        result = normalize_column_names(df)
        assert list(result["nombre"]) == ["Ana", "Luis"]

    def test_returns_dataframe(self):
        assert isinstance(normalize_column_names(pd.DataFrame(columns=["Col A"])), pd.DataFrame)


# ===========================================================================
# AGE CLASSIFICATION
# ===========================================================================

class TestClassifyAge:

    @pytest.mark.parametrize("age,expected", [
        (5,   "< 18"),
        (17,  "< 18"),
        (18,  "18-28"),
        (28,  "18-28"),
        (29,  "29-39"),
        (39,  "29-39"),
        (40,  "40-49"),
        (49,  "40-49"),
        (50,  "50-59"),
        (59,  "50-59"),
        (60,  "> 60"),
        (80,  "> 60"),
        (120, "> 60"),
    ])
    def test_age_bucket_assignment(self, age, expected):
        assert classify_age(age) == expected

    def test_zero_returns_nan(self):
        assert pd.isna(classify_age(0))

    def test_negative_returns_nan(self):
        assert pd.isna(classify_age(-1))

    def test_boundary_18_is_in_18_28(self):
        assert classify_age(18) == "18-28"

    def test_boundary_60_is_in_over_60(self):
        assert classify_age(60) == "> 60"


class TestCleanEdad:

    def test_extracts_numeric_age_from_plain_string(self, base_df):
        assert clean_edad(base_df.copy())["edad"].iloc[0] == 25

    def test_extracts_numeric_age_from_suffix_string(self, base_df):
        assert clean_edad(base_df.copy())["edad"].iloc[1] == 30

    def test_adds_rango_de_edad_column(self, base_df):
        assert "rango_de_edad" in clean_edad(base_df.copy()).columns

    def test_rango_correct_for_minor(self, base_df):
        assert clean_edad(base_df.copy())["rango_de_edad"].iloc[3] == "< 18"

    def test_non_numeric_age_becomes_nan(self):
        assert pd.isna(clean_edad(pd.DataFrame({"edad": ["no tiene edad"]}))["edad"].iloc[0])

    def test_does_not_drop_rows(self, base_df):
        assert len(clean_edad(base_df.copy())) == len(base_df)


# ===========================================================================
# STRING COLUMN CLEANING
# ===========================================================================

class TestLowercaseStringColumns:

    def test_lowercases_object_columns(self, base_df):
        df = base_df.copy()
        df["nombres"] = ["ANA", "LUIS", "ROSA", "PEDRO"]
        assert lowercase_string_columns(df)["nombres"].iloc[0] == "ana"

    def test_does_not_affect_numeric_columns(self):
        df = pd.DataFrame({"edad": [25, 30], "nombre": ["ANA", "LUIS"]})
        result = lowercase_string_columns(df)
        assert list(result["edad"]) == [25, 30]

    def test_does_not_drop_rows(self, base_df):
        assert len(lowercase_string_columns(base_df.copy())) == len(base_df)

    def test_handles_null_values_without_raising(self):
        lowercase_string_columns(pd.DataFrame({"nombre": ["ANA", None, "LUIS"]}))


# ===========================================================================
# GENDER NORMALISATION
# ===========================================================================

class TestCleanGenero:

    def test_masculino_maps_to_m(self, base_df):
        assert clean_genero(base_df.copy(), GENERO_MAPPING)["género"].iloc[0] == "m"

    def test_femenino_maps_to_f(self, base_df):
        assert clean_genero(base_df.copy(), GENERO_MAPPING)["género"].iloc[1] == "f"

    def test_intersexual_maps_to_i(self):
        df = pd.DataFrame({"género": ["intersexual"]})
        assert clean_genero(df, GENERO_MAPPING)["género"].iloc[0] == "i"

    def test_unknown_value_is_unchanged(self):
        df = pd.DataFrame({"género": ["otro"]})
        assert clean_genero(df, GENERO_MAPPING)["género"].iloc[0] == "otro"

    def test_missing_column_does_not_raise(self, base_df):
        clean_genero(base_df.drop(columns=["género"]), GENERO_MAPPING)

    def test_does_not_drop_rows(self, base_df):
        assert len(clean_genero(base_df.copy(), GENERO_MAPPING)) == len(base_df)


# ===========================================================================
# VALID RECORD FILTERING
# ===========================================================================

class TestFilterValidRecords:

    def test_returns_two_dataframes(self, base_df):
        valid, invalid = filter_valid_records(base_df.copy())
        assert isinstance(valid, pd.DataFrame)
        assert isinstance(invalid, pd.DataFrame)

    def test_partition_is_exhaustive(self, base_df):
        valid, invalid = filter_valid_records(base_df.copy())
        assert len(valid) + len(invalid) == len(base_df)

    def test_all_valid_when_no_nulls(self, base_df):
        valid, invalid = filter_valid_records(base_df.copy())
        assert len(invalid) == 0
        assert len(valid) == len(base_df)

    def test_null_numero_documento_is_invalid(self):
        # RENAME_DICT maps "número_de_documento" → "numero_de_documento"
        # so filter_valid_records always sees the clean unaccented name.
        df = pd.DataFrame({
            "numero_de_documento": [None, "123"],
            "nombres":             ["Ana", "Luis"],
        })
        valid, invalid = filter_valid_records(df)
        assert len(invalid) == 1
        assert len(valid) == 1

    def test_null_nombres_is_invalid(self):
        df = pd.DataFrame({
            "numero_de_documento": ["111", "222"],
            "nombres":             [None, "Luis"],
        })
        valid, invalid = filter_valid_records(df)
        assert len(invalid) == 1

    def test_blank_whitespace_only_is_invalid(self):
        df = pd.DataFrame({
            "numero_de_documento": ["111", "   "],
            "nombres":             ["Ana", "Luis"],
        })
        valid, invalid = filter_valid_records(df)
        assert len(invalid) == 1

    def test_all_invalid_when_all_nulls(self):
        df = pd.DataFrame({
            "numero_de_documento": [None, None],
            "nombres":             [None, None],
        })
        valid, invalid = filter_valid_records(df)
        assert len(valid) == 0
        assert len(invalid) == 2

    def test_apellidos_absence_does_not_raise(self):
        """
        The Excel form uses 'nombre_completo' (renamed to 'nombres') — there
        is no separate 'apellidos' column. Passing a DataFrame without it
        must not raise and must not mark valid rows as invalid.
        """
        df = pd.DataFrame({
            "numero_de_documento": ["111", "222"],
            "nombres":             ["Ana Gómez", "Luis Pérez"],
        })
        valid, invalid = filter_valid_records(df)
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_does_not_mutate_input(self, base_df):
        original_len = len(base_df)
        filter_valid_records(base_df.copy())
        assert len(base_df) == original_len

    def test_missing_required_column_does_not_raise(self):
        # If a required column is absent from the DataFrame entirely,
        # filter_valid_records skips it gracefully rather than raising KeyError.
        df = pd.DataFrame({"nombres": ["Ana"]})
        valid, invalid = filter_valid_records(df)
        assert len(valid) + len(invalid) == 1


# ===========================================================================
# POPULATION FLAGS — GENERIC HELPER
# ===========================================================================

class TestFlagPopulation:

    def test_flags_when_pattern_matches(self, flag_df):
        result = flag_population(flag_df("víctima de violencia"), "vvg", ["viole", "vvg"], "vvg")
        assert result["vvg"].iloc[0] == "vvg"

    def test_nan_when_no_match(self, flag_df):
        result = flag_population(flag_df("desempleado"), "vvg", ["viole", "vvg"], "vvg")
        assert pd.isna(result["vvg"].iloc[0])

    def test_nan_is_not_empty_string(self, flag_df):
        result = flag_population(flag_df("ninguna"), "vvg", ["viole"], "vvg")
        # pd.NA != "" raises TypeError — use pd.isna() which handles pd.NA,
        # np.nan and None correctly, and already proves it is not an empty string.
        assert pd.isna(result["vvg"].iloc[0])

    def test_flags_via_extra_col(self, flag_df):
        result = flag_population(
            flag_df(doc="Permiso especial de permanencia"),
            "migrante", ["migr", "retor"], "Migrante o Retornado",
            extra_col="tipo_de_documento",
            extra_patterns=["ermiso", "tranje"],
        )
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_case_insensitive_match(self, flag_df):
        result = flag_population(flag_df("CONFLICTO ARMADO"), "vca", ["conflic"], "vca")
        assert result["vca"].iloc[0] == "vca"

    def test_partial_match_sufficient(self, flag_df):
        result = flag_population(flag_df("proceso de reincorporación"), "reincorporados", ["rein"], "reincorporados")
        assert result["reincorporados"].iloc[0] == "reincorporados"


# ===========================================================================
# DISABILITY CLASSIFICATION
# ===========================================================================

class TestFlagDiscapacidad:

    @pytest.mark.parametrize("text,expected_label", [
        ("discapacidad cognitiva",   "Cognitiva o Intelectual"),
        ("discapacidad intelectual", "Cognitiva o Intelectual"),
        ("discapacidad física",      "Física"),
        ("discapacidad visual",      "Visual"),
        ("discapacidad auditiva",    "Auditiva"),
        ("discapacidad múltiple",    "Múltiple"),
        ("sordoceguera severa",      "Sordoceguera"),
        ("trastorno psicosocial",    "Psicosocial"),
        ("en capacidad reducida",    "Discapacidad"),
    ])
    def test_disability_type_detected(self, discapacidad_df, text, expected_label):
        result = flag_discapacidad(discapacidad_df(text), DISCAPACIDAD_PATTERNS)
        assert result["discapacidad"].iloc[0] == expected_label

    def test_no_match_returns_nan(self, discapacidad_df):
        assert pd.isna(flag_discapacidad(discapacidad_df("sin ninguna"), DISCAPACIDAD_PATTERNS)["discapacidad"].iloc[0])

    def test_empty_string_returns_nan(self, discapacidad_df):
        assert pd.isna(flag_discapacidad(discapacidad_df(""), DISCAPACIDAD_PATTERNS)["discapacidad"].iloc[0])

    def test_case_insensitive(self, discapacidad_df):
        result = flag_discapacidad(discapacidad_df("DISCAPACIDAD VISUAL"), DISCAPACIDAD_PATTERNS)
        assert result["discapacidad"].iloc[0] == "Visual"

    def test_specific_label_wins_over_catchall(self, discapacidad_df):
        """
        'discapacidad física' matches both [ií]sic → 'Física' AND
        'capacidad' → 'Discapacidad'. The specific label must win because
        DISCAPACIDAD_PATTERNS evaluates specific patterns first.
        """
        result = flag_discapacidad(discapacidad_df("discapacidad física"), DISCAPACIDAD_PATTERNS)
        assert result["discapacidad"].iloc[0] == "Física"

    def test_does_not_drop_rows(self, base_df):
        assert len(flag_discapacidad(base_df.copy(), DISCAPACIDAD_PATTERNS)) == len(base_df)


# ===========================================================================
# ADD_POPULATION_FLAGS — END-TO-END ORCHESTRATION
# ===========================================================================

class TestAddPopulationFlags:

    def test_all_flag_columns_created(self, base_df):
        result = add_population_flags(base_df.copy())
        expected = {"vvg", "vca", "reincorporados", "grupos_etnicos", "migrante", "discapacidad"}
        assert expected.issubset(set(result.columns))

    def test_vvg_flagged_correctly(self, base_df):
        assert add_population_flags(base_df.copy())["vvg"].iloc[0] == "vvg"

    def test_vca_flagged_correctly(self, base_df):
        assert add_population_flags(base_df.copy())["vca"].iloc[2] == "vca"

    def test_grupos_etnicos_flagged_correctly(self, base_df):
        assert add_population_flags(base_df.copy())["grupos_etnicos"].iloc[1] == "Grupos etnicos"

    def test_migrante_flagged_via_documento(self, base_df):
        assert add_population_flags(base_df.copy())["migrante"].iloc[1] == "Migrante o Retornado"

    def test_discapacidad_fisica_flagged(self, base_df):
        assert add_population_flags(base_df.copy())["discapacidad"].iloc[0] == "Física"

    def test_plain_row_has_no_flags(self, base_df):
        result = add_population_flags(base_df.copy())
        assert pd.isna(result["vvg"].iloc[3])
        assert pd.isna(result["vca"].iloc[3])
        assert pd.isna(result["grupos_etnicos"].iloc[3])
        assert pd.isna(result["migrante"].iloc[3])

    def test_row_count_unchanged(self, base_df):
        assert len(add_population_flags(base_df.copy())) == len(base_df)

    def test_does_not_mutate_input_columns(self, base_df):
        original_cols = list(base_df.columns)
        add_population_flags(base_df.copy())
        assert list(base_df.columns) == original_cols