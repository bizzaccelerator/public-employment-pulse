import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from registro_hv import (
    clean_string_columns,
    filter_valid_records,
    filter_by_year,
    replace_string_nan,
    normalise_gender,
    parse_dates,
    parse_date_columns,
    classify_ethnic_groups,
    classify_vca,
    classify_disability,
    classify_migrants,
    classify_vvg,
    classify_reintegrated,
    run_all_classifications,
    filter_by_month,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def base_df():
    """
    Minimal DataFrame with four rows that covers the main validation cases:
      - row 0: fully valid
      - row 1: fully valid, lowercase gender
      - row 2: null tipo_documento  → should be removed by filter_valid_records
      - row 3: null número_documento → should be removed by filter_valid_records
    """
    return pd.DataFrame({
        "tipo_documento":    ["CC", "CC", None, "PA"],
        "número_documento":  ["111", "222", "333", None],
        "celular":           [" 3001234 ", "3009876", "3005555", "3007777"],
        "teléfono":          ["111 ", "222", "333", "444"],
        "título_homologado": ["T1 ", "T2", "T3", "T4"],
        "ciudad_de_residencia": [" Neiva", "Bogotá", "Med", "Cali"],
        "email":             ["a@a.com ", "b@b.com", "c@c.com", "d@d.com"],
        "programa_de_gobierno": ["P1", "conflicto armado", "nan", "nan"],
        "fecha_actualización":   ["", "", "", ""],
        "%_hoja_vida":       ["80%", "60%", "90%", "70%"],
        "fecha_cambio_prestador": ["", "", "", ""],
        "vereda/localidad/centro_poblado": ["C", "N", "S", "E"],
        "género":            ["F", "m", "M", "f"],
        "año":               [2025, 2025, 2025, 2025],
        "condiciones_especiales": [
            "afrodescendiente", "discapacidad física", "", ""
        ],
    })


@pytest.fixture
def classify_df():
    """
    Factory fixture: returns a callable that builds a one-row DataFrame
    for classification tests.

    Usage inside a test:
        def test_something(classify_df):
            df = classify_df(cond="migrante")
            ...
    """
    def _make(cond="", prog="", tdoc="CC"):
        return pd.DataFrame({
            "condiciones_especiales": [cond],
            "programa_de_gobierno":   [prog],
            "tipo_documento":         [tdoc],
        })
    return _make


@pytest.fixture
def date_df():
    """
    Five rows covering every date format and null variant.
    Columns include the minimum set required by parse_date_columns().
    """
    return pd.DataFrame({
        "tipo_documento":      ["CC"] * 5,
        "número_documento":    ["1", "2", "3", "4", "5"],
        # Row 0: Excel serial | Row 1: slash | Row 2: dash | Row 3: empty | Row 4: NaN
        "fecha_registro":       ["45679", "15/01/2025", "15-01-2025", "",     np.nan],
        "fecha_actualización":  ["",      "",           "",           "",     ""],
        "fecha_cambio_prestador": ["",    "",           "",           "",     ""],
        "condiciones_especiales": [""] * 5,
        "programa_de_gobierno":   [""] * 5,
        "año":                  [2025] * 5,
        "mes":                  [1] * 5,
    })


# ===========================================================================
# CLEANING
# ===========================================================================

class TestCleanStringColumns:

    def test_strips_celular(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["celular"].iloc[0] == "3001234"

    def test_strips_ciudad_de_residencia(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["ciudad_de_residencia"].iloc[0] == "Neiva"

    def test_strips_email(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["email"].iloc[0] == "a@a.com"

    def test_strips_titulo_homologado(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["título_homologado"].iloc[0] == "T1"

    def test_strips_telefono(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["teléfono"].iloc[0] == "111"

    def test_does_not_drop_rows(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert len(result) == len(base_df)

    def test_missing_column_does_not_raise(self, base_df):
        df = base_df.drop(columns=["celular"])
        clean_string_columns(df)   # must not raise


class TestFilterValidRecords:

    def test_removes_null_tipo_documento(self, base_df):
        valid, _ = filter_valid_records(base_df.copy())
        assert 2 not in valid.index

    def test_removes_null_numero_documento(self, base_df):
        valid, _ = filter_valid_records(base_df.copy())
        assert 3 not in valid.index

    def test_invalid_df_contains_removed_rows(self, base_df):
        _, invalid = filter_valid_records(base_df.copy())
        assert set(invalid.index) == {2, 3}

    def test_partition_is_exhaustive(self, base_df):
        valid, invalid = filter_valid_records(base_df.copy())
        assert len(valid) + len(invalid) == len(base_df)

    def test_all_valid_when_no_nulls(self):
        df = pd.DataFrame({
            "tipo_documento":   ["CC", "CC"],
            "número_documento": ["111", "222"],
        })
        valid, invalid = filter_valid_records(df)
        assert len(valid) == 2 and len(invalid) == 0

    def test_all_invalid_when_all_nulls(self):
        df = pd.DataFrame({
            "tipo_documento":   [None, None],
            "número_documento": [None, None],
        })
        valid, invalid = filter_valid_records(df)
        assert len(valid) == 0 and len(invalid) == 2


class TestFilterByYear:

    def test_keeps_matching_year(self, base_df):
        result = filter_by_year(base_df.copy(), 2025)
        assert all(result["año"] == 2025)

    def test_drops_non_matching_year(self):
        df = pd.DataFrame({"año": [2024, 2025, 2025]})
        assert len(filter_by_year(df, 2025)) == 2

    def test_returns_empty_for_no_match(self, base_df):
        assert len(filter_by_year(base_df.copy(), 1999)) == 0

    def test_does_not_mutate_original(self, base_df):
        original_len = len(base_df)
        filter_by_year(base_df, 2025)
        assert len(base_df) == original_len


class TestReplaceStringNan:

    def test_replaces_literal_nan_string(self, base_df):
        result = replace_string_nan(base_df.copy())
        assert pd.isna(result["programa_de_gobierno"].iloc[2])
        assert pd.isna(result["programa_de_gobierno"].iloc[3])

    def test_does_not_replace_real_values(self, base_df):
        result = replace_string_nan(base_df.copy())
        assert result["programa_de_gobierno"].iloc[0] == "P1"

    def test_works_across_all_columns(self):
        df = pd.DataFrame({"a": ["nan", "real"], "b": ["nan", "nan"]})
        result = replace_string_nan(df)
        assert pd.isna(result["a"].iloc[0])
        assert pd.isna(result["b"].iloc[1])


class TestNormaliseGender:

    def test_lowercase_m_becomes_uppercase(self, base_df):
        result = normalise_gender(base_df.copy())
        assert result["género"].iloc[1] == "M"

    def test_lowercase_f_becomes_uppercase(self, base_df):
        result = normalise_gender(base_df.copy())
        assert result["género"].iloc[3] == "F"

    def test_already_uppercase_unchanged(self, base_df):
        result = normalise_gender(base_df.copy())
        assert result["género"].iloc[0] == "F"
        assert result["género"].iloc[2] == "M"

    def test_missing_column_does_not_raise(self, base_df):
        df = base_df.drop(columns=["género"])
        normalise_gender(df)   # must not raise


# ===========================================================================
# DATE PARSING
# ===========================================================================

class TestParseDates:

    def test_excel_serial_number(self):
        # Serial 45679 → base_date(1899-12-30) + 45679 days = 2025-01-22
        assert parse_dates("45679") == datetime(2025, 1, 22)

    def test_excel_serial_as_float_string(self):
        assert parse_dates("45679.0") == datetime(2025, 1, 22)

    def test_slash_format_date_only(self):
        assert parse_dates("15/01/2025") == pd.Timestamp("2025-01-15")

    def test_slash_format_with_pm(self):
        assert parse_dates("15/01/2025 02:30:00 p. m.") == pd.Timestamp("2025-01-15 14:30:00")

    def test_slash_format_with_am(self):
        assert parse_dates("15/01/2025 08:00:00 a. m.") == pd.Timestamp("2025-01-15 08:00:00")

    def test_dash_format_dd_mm_yyyy(self):
        assert parse_dates("15-01-2025") == pd.Timestamp("2025-01-15")

    def test_none_returns_nat(self):
        assert pd.isna(parse_dates(None))

    def test_nan_returns_nat(self):
        assert pd.isna(parse_dates(np.nan))

    def test_empty_string_returns_nat(self):
        assert pd.isna(parse_dates(""))

    def test_whitespace_only_returns_nat(self):
        assert pd.isna(parse_dates("   "))

    def test_garbage_string_returns_nat(self):
        assert pd.isna(parse_dates("not-a-date"))

    def test_iso_format_not_supported(self):
        """
        ISO format (YYYY-MM-DD) does not match any of the three parsing
        cases. This test documents the known limitation so any accidental
        change is immediately visible.
        """
        assert pd.isna(parse_dates("2025-01-15"))


class TestParseDateColumns:

    def test_slash_date_parsed_correctly(self, date_df):
        result = parse_date_columns(date_df.copy())
        assert pd.notna(result["fecha_registro"].iloc[1])

    def test_empty_string_becomes_nat(self, date_df):
        result = parse_date_columns(date_df.copy())
        assert pd.isna(result["fecha_registro"].iloc[3])

    def test_nan_becomes_nat(self, date_df):
        result = parse_date_columns(date_df.copy())
        assert pd.isna(result["fecha_registro"].iloc[4])

    def test_fecha_accion_is_max_of_three_columns(self, date_df):
        df = date_df.copy()
        df["fecha_registro"]         = ["15/01/2025", "", "", "", ""]
        df["fecha_actualización"]    = ["20/03/2025", "", "", "", ""]
        df["fecha_cambio_prestador"] = ["10/02/2025", "", "", "", ""]
        result = parse_date_columns(df)
        assert result["fecha_accion"].iloc[0] == pd.Timestamp("2025-03-20")

    def test_fecha_accion_floored_to_midnight(self, date_df):
        df = date_df.copy()
        df["fecha_registro"] = ["15/01/2025 02:30:00 p. m.", "", "", "", ""]
        result = parse_date_columns(df)
        non_nat = result["fecha_accion"].dropna()
        assert (non_nat.dt.hour == 0).all()
        assert (non_nat.dt.minute == 0).all()

    def test_mes_derived_from_fecha_accion(self, date_df):
        df = date_df.copy()
        df["fecha_registro"] = ["15/03/2025", "", "", "", ""]
        df["mes"] = 99   # deliberately wrong — must be overwritten
        result = parse_date_columns(df)
        assert int(result["mes"].iloc[0]) == 3

    def test_original_mes_not_preserved(self, date_df):
        df = date_df.copy()
        df["mes"] = 99
        result = parse_date_columns(df)
        non_nat = result[result["fecha_accion"].notna()]
        assert (non_nat["mes"] != 99).all()


# ===========================================================================
# CLASSIFICATION
# ===========================================================================

class TestClassifyEthnicGroups:

    @pytest.mark.parametrize("text,expected", [
        ("afrodescendiente",            "Afrodescendiente"),
        ("comunidad negra del pacífico", "Afrodescendiente"),
        ("mulato mestizo",              "Afrodescendiente"),
        ("palenquero de san basilio",   "Afrodescendiente"),
        ("raizal isleño",               "Raizal y/o Isleño"),
        ("gitano nómada",               "Gitano"),
    ])
    def test_single_group_detected(self, classify_df, text, expected):
        result = classify_ethnic_groups(classify_df(cond=text))
        groups = result["grupos_etnicos"].iloc[0]
        assert isinstance(groups, list) and expected in groups

    def test_multiple_groups_in_one_record(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond="afrodescendiente raizal"))
        groups = result["grupos_etnicos"].iloc[0]
        assert "Afrodescendiente" in groups and "Raizal y/o Isleño" in groups

    def test_no_match_returns_nan(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond="sin condición"))
        assert pd.isna(result["grupos_etnicos"].iloc[0])

    def test_empty_string_returns_nan(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond=""))
        assert pd.isna(result["grupos_etnicos"].iloc[0])

    def test_case_insensitive(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond="AFRODESCENDIENTE"))
        groups = result["grupos_etnicos"].iloc[0]
        assert "Afrodescendiente" in groups


class TestClassifyVca:

    def test_flagged_via_programa_de_gobierno(self, classify_df):
        result = classify_vca(classify_df(prog="conflicto armado"))
        assert result["vca"].iloc[0] == "VCA"

    def test_flagged_via_condiciones_vca(self, classify_df):
        result = classify_vca(classify_df(cond="vca registrado"))
        assert result["vca"].iloc[0] == "VCA"

    def test_flagged_via_condiciones_dotted(self, classify_df):
        result = classify_vca(classify_df(cond="v.c.a."))
        assert result["vca"].iloc[0] == "VCA"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_vca(classify_df(cond="empleo general", prog="empleo"))
        assert pd.isna(result["vca"].iloc[0])


class TestClassifyDisability:

    @pytest.mark.parametrize("text,expected_label", [
        ("discapacidad cognitiva",    "Cognitiva o Intelectual"),
        ("discapacidad intelectual",  "Cognitiva o Intelectual"),
        ("discapacidad física",       "Física"),
        ("discapacidad visual",       "Visual"),
        ("discapacidad auditiva",     "Auditiva"),
        ("discapacidad múltiple",     "Múltiple"),
        ("sordoceguera severa",       "Sordoceguera"),
        ("trastorno psicosocial",     "Psicosocial"),
        ("en capacidad reducida",     "Discapacidad"),
    ])
    def test_disability_type_detected(self, classify_df, text, expected_label):
        result = classify_disability(classify_df(cond=text))
        assert result["discapacidad"].iloc[0] == expected_label

    def test_first_pattern_wins_over_catchall(self, classify_df):
        """
        'discapacidad física' matches both [ií]sic → 'Física' AND
        'capacidad' → 'Discapacidad'.  The specific label must win.
        """
        result = classify_disability(classify_df(cond="discapacidad física"))
        assert result["discapacidad"].iloc[0] == "Física", (
            "Specific disability type should take priority over catch-all 'Discapacidad'"
        )

    def test_cognitiva_wins_over_catchall(self, classify_df):
        result = classify_disability(classify_df(cond="cognitivo con capacidad"))
        assert result["discapacidad"].iloc[0] == "Cognitiva o Intelectual"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_disability(classify_df(cond="sin condición"))
        assert pd.isna(result["discapacidad"].iloc[0])


class TestClassifyMigrants:

    def test_flagged_via_condiciones_migr(self, classify_df):
        result = classify_migrants(classify_df(cond="migrante venezolano"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_condiciones_retor(self, classify_df):
        result = classify_migrants(classify_df(cond="retornado de venezuela"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipo_documento_permiso(self, classify_df):
        result = classify_migrants(classify_df(tdoc="Permiso especial de permanencia"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipo_documento_extranjeria(self, classify_df):
        result = classify_migrants(classify_df(tdoc="Cédula extranjería"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_migrants(classify_df(cond="residente local", tdoc="CC"))
        assert pd.isna(result["migrante"].iloc[0])


class TestClassifyVvg:

    def test_flagged_via_viole(self, classify_df):
        result = classify_vvg(classify_df(cond="víctima de violencia intrafamiliar"))
        assert result["vvg"].iloc[0] == "vvg"

    def test_flagged_via_vvg_text(self, classify_df):
        result = classify_vvg(classify_df(cond="vvg registrada"))
        assert result["vvg"].iloc[0] == "vvg"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_vvg(classify_df(cond="situación económica difícil"))
        assert pd.isna(result["vvg"].iloc[0])


class TestClassifyReintegrated:

    def test_flagged_via_rein(self, classify_df):
        result = classify_reintegrated(classify_df(cond="proceso de reincorporación FARC"))
        assert result["reincorporados"].iloc[0] == "reincorporados"

    def test_flagged_via_reinsercion(self, classify_df):
        result = classify_reintegrated(classify_df(cond="reinsertado AUC"))
        assert result["reincorporados"].iloc[0] == "reincorporados"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_reintegrated(classify_df(cond="sin antecedentes"))
        assert pd.isna(result["reincorporados"].iloc[0])


class TestRunAllClassifications:

    def test_all_classification_columns_present(self, classify_df):
        result = run_all_classifications(classify_df(cond="afrodescendiente").copy())
        expected = {"grupos_etnicos", "vca", "discapacidad", "migrante", "vvg", "reincorporados"}
        assert expected.issubset(set(result.columns))

    def test_no_rows_lost(self):
        df = pd.DataFrame({
            "condiciones_especiales": ["a", "b", "c"],
            "programa_de_gobierno":   ["", "", ""],
            "tipo_documento":         ["CC", "CC", "CC"],
        })
        result = run_all_classifications(df.copy())
        assert len(result) == 3


# ===========================================================================
# MONTH FILTER
# ===========================================================================

class TestFilterByMonth:

    def test_keeps_only_target_month_and_year(self):
        df = pd.DataFrame({
            "fecha_accion": pd.to_datetime([
                "2025-01-15", "2025-02-20", "2025-01-10", "2024-01-05"
            ])
        })
        result = filter_by_month(df, month=1, year=2025)
        assert len(result) == 2
        assert all(result["fecha_accion"].dt.month == 1)
        assert all(result["fecha_accion"].dt.year == 2025)

    def test_excludes_same_month_different_year(self):
        df = pd.DataFrame({
            "fecha_accion": pd.to_datetime(["2024-01-15", "2025-01-15"])
        })
        result = filter_by_month(df, month=1, year=2025)
        assert len(result) == 1

    def test_returns_empty_dataframe_when_no_match(self):
        df = pd.DataFrame({
            "fecha_accion": pd.to_datetime(["2025-01-15"])
        })
        result = filter_by_month(df, month=6, year=2025)
        assert len(result) == 0

    def test_does_not_mutate_original(self):
        df = pd.DataFrame({
            "fecha_accion": pd.to_datetime(["2025-01-15", "2025-02-20"])
        })
        original_len = len(df)
        filter_by_month(df, month=1, year=2025)
        assert len(df) == original_len