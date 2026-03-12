"""
test_vacantes.py
----------------
Unit tests for every public function in vacantes.py.

Run locally:
    pytest test_vacantes.py -v

Run inside Kestra (via run_tests_vacantes.py):
    python run_tests_vacantes.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from datetime import datetime

from code_used.snippets_support.workload.vacantes import (
    normalise_column_names,
    drop_columns,
    select_columns,
    clean_string_columns,
    _parse_single_date,
    parse_date_columns,
    filter_by_period,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def base_df():
    """
    Minimal DataFrame with five rows that covers the main validation cases:
      - row 0: fully valid, jan 2025
      - row 1: fully valid, jan 2025, strings need stripping
      - row 2: fully valid, feb 2025  → filtered out by filter_by_period(1, 2025)
      - row 3: null empresa           → present, no mandatory-key filtering in vacantes
      - row 4: null cargo             → present, no mandatory-key filtering in vacantes
    """
    return pd.DataFrame({
        "código_proceso":       ["P001",    " P002 ",  "P003",   "P004",   "P005"],
        "nombre_vacante":       ["Conductor","Asesor ","Técnico","Obrero", "Analista"],
        "cargo":                ["Conductor","Asesor", "Técnico","Obrero",  None],
        "empresa":              ["Acme S.A."," Beta ",  "Gamma",  None,    "Delta"],
        "#_postulados":         [3,           1,         5,        2,        0],
        "tipodocumentoempresa": ["NIT",       "NIT",    "NIT",    "CC",     "NIT"],
        "numerodocumentoempresa": [900111222, 900333444, 800555666, None, 900777888],
        "fecha_registro":       [
            "15/01/2025", "20/01/2025", "10/02/2025", "05/01/2025", "28/01/2025"
        ],
        "fecha_vencimiento": [
            "28/02/2025", "28/02/2025", "31/03/2025", "28/02/2025", "28/02/2025"
        ],
        "estado_actual":    ["activa", "activa", "vencida", "activa", "activa"],
        "tipo_de_vacante":  ["privada", "privada", "pública", "privada", "privada"],
        "puestos_de_trabajo": [1, 2, 1, None, 3],
        "tipo_de_contrato": ["término fijo", "indefinido", "obra labor", "indefinido", "término fijo"],
        "agente_aprobó":    ["agente1", " agente2 ", "agente3", None, "agente5"],
        "punto_atención":   ["Centro",   "Norte",    "Sur",     "Este",  "Oeste"],
        "país":             ["Colombia"] * 5,
        "mes":              [1, 1, 2, 1, 1],
        "año":              [2025, 2025, 2025, 2025, 2025],
        "empre_reg":        ["X"] * 5,          # column that must be dropped
    })


@pytest.fixture
def date_df():
    """
    Five rows covering every date-input format and null variant.
    Only the columns relevant to parse_date_columns() are needed.
    """
    return pd.DataFrame({
        "fecha_registro": [
            "45679",             # Excel serial  → 2025-01-22
            "15/01/2025",        # slash, date only
            "15/01/2025 02:30:00 p. m.",  # slash + PM time
            "15-01-2025",        # dash DD-MM-YYYY
            "",                  # empty string → NaT
        ],
        "fecha_vencimiento": ["", "", "", "", np.nan],
    })


# ===========================================================================
# COLUMN NORMALISATION
# ===========================================================================

class TestNormaliseColumnNames:

    def test_spaces_replaced_with_underscores(self):
        # normalise_column_names lowercases AND replaces spaces, so the
        # expected result is 'first_name', not 'First_Name'.
        df = pd.DataFrame({"First Name": [1], "Last Name": [2]})
        result = normalise_column_names(df)
        assert "first_name" in result.columns
        assert "last_name" in result.columns

    def test_names_are_lowercased(self):
        df = pd.DataFrame({"CARGO": [1], "Empresa": [2]})
        result = normalise_column_names(df)
        assert "cargo" in result.columns
        assert "empresa" in result.columns

    def test_no_rows_lost(self, base_df):
        result = normalise_column_names(base_df.copy())
        assert len(result) == len(base_df)

    def test_already_clean_columns_unchanged(self):
        df = pd.DataFrame({"mes": [1], "año": [2025]})
        result = normalise_column_names(df)
        assert list(result.columns) == ["mes", "año"]


class TestDropColumns:

    def test_drops_existing_column(self, base_df):
        result = drop_columns(base_df.copy(), ["empre_reg"])
        assert "empre_reg" not in result.columns

    def test_silently_ignores_missing_column(self, base_df):
        # Should not raise even if column doesn't exist
        result = drop_columns(base_df.copy(), ["columna_inexistente"])
        assert len(result.columns) == len(base_df.columns)

    def test_drops_multiple_columns(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        result = drop_columns(df, ["a", "b"])
        assert list(result.columns) == ["c"]

    def test_no_rows_lost(self, base_df):
        result = drop_columns(base_df.copy(), ["empre_reg"])
        assert len(result) == len(base_df)


class TestSelectColumns:

    def test_returns_only_requested_columns(self, base_df):
        cols = ["código_proceso", "cargo", "mes"]
        result = select_columns(base_df.copy(), cols)
        assert list(result.columns) == cols

    def test_silently_skips_missing_columns(self, base_df):
        cols = ["código_proceso", "columna_que_no_existe"]
        result = select_columns(base_df.copy(), cols)
        assert "columna_que_no_existe" not in result.columns
        assert "código_proceso" in result.columns

    def test_no_rows_lost(self, base_df):
        result = select_columns(base_df.copy(), ["código_proceso", "mes"])
        assert len(result) == len(base_df)

    def test_empty_col_list_returns_empty_dataframe(self, base_df):
        result = select_columns(base_df.copy(), [])
        assert result.empty or list(result.columns) == []


# ===========================================================================
# STRING CLEANING
# ===========================================================================

class TestCleanStringColumns:

    def test_strips_leading_and_trailing_whitespace(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["nombre_vacante"].iloc[1] == "asesor"

    def test_strips_empresa_whitespace(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["empresa"].iloc[1] == "beta"

    def test_strips_agente_aprobó_whitespace(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert result["agente_aprobó"].iloc[1] == "agente2"

    def test_lowercases_all_strings(self, base_df):
        df = base_df.copy()
        df["cargo"] = ["CONDUCTOR", "ASESOR", "TÉCNICO", "OBRERO", None]
        result = clean_string_columns(df)
        assert result["cargo"].iloc[0] == "conductor"

    def test_empty_string_becomes_na(self):
        # On plain string-dtype Series (pandas >= 2) .replace() inserts
        # np.nan, not pd.NA.  pd.isna() handles both correctly and is the
        # right assertion here — it also returns False for the string '<na>',
        # which would indicate the old .astype(str) bug if it crept back.
        df = pd.DataFrame({"cargo": ["", "válido"]})
        result = clean_string_columns(df)
        assert pd.isna(result["cargo"].iloc[0])

    def test_literal_nan_string_becomes_na(self):
        # Same reasoning as test_empty_string_becomes_na.
        df = pd.DataFrame({"cargo": ["nan", "válido"]})
        result = clean_string_columns(df)
        assert pd.isna(result["cargo"].iloc[0])

    def test_does_not_drop_rows(self, base_df):
        result = clean_string_columns(base_df.copy())
        assert len(result) == len(base_df)

    def test_non_object_columns_untouched(self, base_df):
        result = clean_string_columns(base_df.copy())
        # Numeric columns must retain their dtype
        assert pd.api.types.is_numeric_dtype(result["mes"])
        assert pd.api.types.is_numeric_dtype(result["año"])

    def test_missing_column_does_not_raise(self, base_df):
        df = base_df.drop(columns=["empresa"])
        clean_string_columns(df)   # must not raise


# ===========================================================================
# DATE PARSING
# ===========================================================================

class TestParseSingleDate:

    def test_excel_serial_number(self):
        # Serial 45679 → 1899-12-30 + 45679 days = 2025-01-22
        assert _parse_single_date("45679") == datetime(2025, 1, 22)

    def test_excel_serial_as_float_string(self):
        assert _parse_single_date("45679.0") == datetime(2025, 1, 22)

    def test_slash_format_date_only(self):
        assert _parse_single_date("15/01/2025") == pd.Timestamp("2025-01-15")

    def test_slash_format_with_pm(self):
        result = _parse_single_date("15/01/2025 02:30:00 p. m.")
        assert result == pd.Timestamp("2025-01-15 14:30:00")

    def test_slash_format_with_am(self):
        result = _parse_single_date("15/01/2025 08:00:00 a. m.")
        assert result == pd.Timestamp("2025-01-15 08:00:00")

    def test_slash_format_dotted_pm_variant(self):
        result = _parse_single_date("15/01/2025 02:30:00 p.m.")
        assert result == pd.Timestamp("2025-01-15 14:30:00")

    def test_dash_format_dd_mm_yyyy(self):
        assert _parse_single_date("15-01-2025") == pd.Timestamp("2025-01-15")

    def test_none_returns_nat(self):
        assert pd.isna(_parse_single_date(None))

    def test_nan_float_returns_nat(self):
        assert pd.isna(_parse_single_date(np.nan))

    def test_empty_string_returns_nat(self):
        assert pd.isna(_parse_single_date(""))

    def test_whitespace_only_returns_nat(self):
        assert pd.isna(_parse_single_date("   "))

    def test_garbage_string_returns_nat(self):
        assert pd.isna(_parse_single_date("not-a-date"))

    def test_iso_format_not_supported(self):
        """
        YYYY-MM-DD does not match any of the three parsing cases.
        Documents the known limitation so any accidental change is visible.
        """
        assert pd.isna(_parse_single_date("2025-01-15"))

    def test_zero_serial_returns_nat(self):
        # Serial 0 is not a valid date for our purposes
        assert pd.isna(_parse_single_date("0"))


class TestParseDateColumns:

    def test_excel_serial_parsed(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert result["fecha_registro"].iloc[0] == pd.Timestamp("2025-01-22")

    def test_slash_date_parsed(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert result["fecha_registro"].iloc[1] == pd.Timestamp("2025-01-15")

    def test_slash_date_with_time_floored_to_day(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        ts = result["fecha_registro"].iloc[2]
        assert ts == pd.Timestamp("2025-01-15")
        assert ts.hour == 0 and ts.minute == 0

    def test_dash_date_parsed(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert result["fecha_registro"].iloc[3] == pd.Timestamp("2025-01-15")

    def test_empty_string_becomes_nat(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert pd.isna(result["fecha_registro"].iloc[4])

    def test_nan_vencimiento_becomes_nat(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert pd.isna(result["fecha_vencimiento"].iloc[4])

    def test_all_dates_floored_to_midnight(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro"])
        non_nat = result["fecha_registro"].dropna()
        assert (non_nat.dt.hour == 0).all()
        assert (non_nat.dt.minute == 0).all()

    def test_missing_column_silently_skipped(self, date_df):
        # parse_date_columns must not raise if a column is absent
        parse_date_columns(date_df.copy(), ["fecha_registro", "columna_inexistente"])

    def test_no_rows_lost(self, date_df):
        result = parse_date_columns(date_df.copy(), ["fecha_registro", "fecha_vencimiento"])
        assert len(result) == len(date_df)


# ===========================================================================
# FILTERING
# ===========================================================================

class TestFilterByPeriod:

    def test_keeps_only_target_month_and_year(self, base_df):
        result = filter_by_period(base_df.copy(), month=1, year=2025)
        assert all(result["mes"] == 1)
        assert all(result["año"] == 2025)

    def test_excludes_different_month(self, base_df):
        # row 2 has mes=2 → must be excluded
        result = filter_by_period(base_df.copy(), month=1, year=2025)
        assert 2 not in result.index

    def test_excludes_different_year(self):
        df = pd.DataFrame({
            "mes": [1, 1],
            "año": [2024, 2025],
            "cargo": ["A", "B"],
        })
        result = filter_by_period(df, month=1, year=2025)
        assert len(result) == 1
        assert result["año"].iloc[0] == 2025

    def test_returns_empty_dataframe_when_no_match(self, base_df):
        result = filter_by_period(base_df.copy(), month=6, year=2025)
        assert len(result) == 0

    def test_does_not_mutate_original(self, base_df):
        original_len = len(base_df)
        filter_by_period(base_df, month=1, year=2025)
        assert len(base_df) == original_len

    def test_returns_copy_not_view(self, base_df):
        result = filter_by_period(base_df.copy(), month=1, year=2025)
        result["cargo"] = "MODIFIED"
        # Original base_df must be unaffected
        assert "MODIFIED" not in base_df["cargo"].values

    def test_all_rows_returned_when_all_match(self):
        df = pd.DataFrame({
            "mes": [3, 3, 3],
            "año": [2026, 2026, 2026],
        })
        result = filter_by_period(df, month=3, year=2026)
        assert len(result) == 3