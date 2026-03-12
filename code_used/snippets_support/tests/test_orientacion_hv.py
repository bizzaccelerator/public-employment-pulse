"""
test_orientacion_hv.py

Unit tests for orientacion_hv.py.

Covers every public function in the module, using only the API that actually
exists in the current orientacion_hv.py.  Key differences from the previous
test file that this replaces:

  - merge_all()                 → does not exist; tests now cover enrich_events()
  - filter_orientados_by_month()→ does not exist; replaced by filter_orientacion_by_month()
  - filter_talleres_by_month()  → does not exist; replaced by filter_taller_by_month()
  - filter_export()             → does not exist; replaced by filter_by_month()
  - clean_orientados() does NOT produce mes_orientado / año_orientado — those
    are built by build_orientacion_events().
  - clean_talleres() does NOT groupby; every raw row stays as its own event row.
  - classify_vca() assigns "VCA" (uppercase); after final_string_clean → "vca".
  - classify_migrants() assigns "Migrante o Retornado"; after final_string_clean
    → "migrante o retornado".
  - build_taller_events() renames fechaejecucion_taller → fechaejecucion_orientacion
    (unified column name) and assigns tipo_evento = 'taller'.

Run with:
    pytest test_orientacion_hv.py -v
"""

import pytest
import pandas as pd
import numpy as np

from code_used.snippets_support.workload.orientacion_hv import (
    clean_orientados,
    clean_talleres,
    clean_registrados,
    clean_psicologas,
    build_orientacion_events,
    build_taller_events,
    enrich_events,
    derive_age_range,
    classify_ethnic_groups,
    classify_vca,
    classify_disability,
    classify_migrants,
    classify_vvg,
    classify_reintegrated,
    run_all_classifications,
    final_string_clean,
    filter_by_month,
    filter_orientacion_by_month,
    filter_taller_by_month,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def classify_df():
    """
    Factory fixture: returns a callable that builds a minimal one-row
    DataFrame suitable for every classification function.

        df = classify_df(cond="migrante venezolano", tdoc="cc")

    All classifiers require at minimum:
        condiciones_especiales, programa_de_gobierno, tipodocumento
    """
    def _make(cond="", prog="", tdoc="cc"):
        return pd.DataFrame({
            "condiciones_especiales": [cond],
            "programa_de_gobierno":   [prog],
            "tipodocumento":          [tdoc],
        })
    return _make


@pytest.fixture
def raw_orientados():
    """
    Minimal raw orientados DataFrame as it arrives from load_orientados()
    (column names already lowercase, no date parsing yet).

    Row 0 — complete record, March 2025.
    Row 1 — partial record (NaT fechaevaluacion), March 2025.
    """
    return pd.DataFrame({
        "numerodocumento":         ["1000001", "1000002"],
        "fechaagendamiento":       ["2025-03-01", "2025-03-05"],
        "fechaejecucion":          ["2025-03-02", "2025-03-06"],
        "fechaevaluacion":         ["2025-03-03", pd.NaT],
        "usuarionombre":           ["Orientadora1", "Orientadora2"],
        "tipodocumento":           ["cc", "ce"],
        "correoelectronico":       ["a@test.com", "b@test.com"],
        "primernombre":            ["Ana", "Luis"],
        "segundonombre":           [None, None],
        "primerapellido":          ["Gomez", "Reyes"],
        "segundoapellido":         ["Rios", None],
        "sexo":                    ["F", "M"],
        "ciudad":                  ["Bogota", "Medellin"],
        "departamento":            ["Cundinamarca", "Antioquia"],
        "area":                    ["urbano", "rural"],
        "tipo":                    ["orientacion", "orientacion"],
        "subtipo":                 ["individual", "grupal"],
        "nombreportafolio":        ["portafolio_a", None],
        "nombreconvocatoria":      ["conv_1", None],
        "aprobacion":              ["si", "no"],
        "porcentajeasistencia":    [100.0, 80.0],
        "prestadornombre":         ["prestador_a", "prestador_b"],
        "institucionnombre":       ["inst_a", "inst_b"],
        "instituciondireccion":    ["calle 1", "calle 2"],
        "institucionmunicipio":    ["bog", "med"],
        "instituciondepartamento": ["cund", "ant"],
        "programagobiernosino":    ["si", "no"],
        "programagobierno":        ["victimas del conflicto armado", None],
        "alianzasentidadesexternas": [None, None],
        "agencianombre":           ["agencia_a", "agencia_b"],
        "numerotelefono":          ["3001234567", None],
        "indicador":               ["I1", "I1"],
        "tipodireccionamiento":    ["dir_a", "dir_b"],
    })


@pytest.fixture
def raw_talleres():
    """
    Raw talleres DataFrame as it arrives from load_talleres().
    Two rows — both for the same person (1000001) in March 2025.
    clean_talleres() does NOT aggregate; both rows are preserved.
    """
    return pd.DataFrame({
        "numerodocumento":         ["1000001", "1000001"],
        "fechaagendamiento":       ["2025-03-10", "2025-03-15"],
        "fechaejecucion":          ["2025-03-11", "2025-03-16"],
        "fechaevaluacion":         ["2025-03-12", pd.NaT],
        "usuarionombre":           ["Tallerista1", "Tallerista1"],
        "indicador":               ["I2", "I2"],
        "tipodireccionamiento":    ["taller", "taller"],
        "tipodocumento":           ["cc", "cc"],
        "correoelectronico":       ["a@test.com", "a@test.com"],
        "primernombre":            ["Ana", "Ana"],
        "segundonombre":           [None, None],
        "primerapellido":          ["Gomez", "Gomez"],
        "segundoapellido":         ["Rios", "Rios"],
        "sexo":                    ["f", "f"],
        "ciudad":                  ["bogota", "bogota"],
        "departamento":            ["cundinamarca", "cundinamarca"],
        "area":                    ["urbano", "urbano"],
        "tipo":                    ["taller", "taller"],
        "subtipo":                 ["grupal", "grupal"],
        "nombreportafolio":        ["port_b", "port_b"],
        "nombreconvocatoria":      ["conv_2", "conv_2"],
        "aprobacion":              ["si", "si"],
        "porcentajeasistencia":    [90.0, 90.0],
        "prestadornombre":         ["prestador_a", "prestador_a"],
        "institucionnombre":       ["inst_a", "inst_a"],
        "instituciondireccion":    ["calle 1", "calle 1"],
        "institucionmunicipio":    ["bog", "bog"],
        "instituciondepartamento": ["cund", "cund"],
        "programagobiernosino":    ["si", "si"],
        "programagobierno":        ["jovenes en accion", "jovenes en accion"],
        "alianzasentidadesexternas": [None, None],
        "agencianombre":           ["agencia_a", "agencia_a"],
        "numerotelefono":          ["3001234567", "3001234567"],
    })


@pytest.fixture
def raw_registrados():
    """
    Minimal registrados DataFrame with the original Excel column names
    (before clean_registrados normalises them).
    """
    return pd.DataFrame({
        "Número Documento":               ["1000001", "1000003"],
        "No. ":                           [1, 2],
        "Programa / Aliado\n(Si aplica)": [None, None],
        "Barrio donde vive":              ["barrio_x", "barrio_y"],
        "Tipo Documento":                 ["CC", "CC"],
        "TIPO_REGISTRO":                  ["Registro_nuevo", "Registro_nuevo"],
        "Nombres":                        ["Ana", "Pedro"],
        "Apellidos":                      ["Gomez Rios", "Perez"],
        "Celular":                        ["3001234567", "3009876543"],
        "Teléfono":                       [None, None],
        "Canal de Registro":              ["Agencia", "Agencia"],
        "Edad":                           [35, 62],
        "Rango_Edad":                     ["29-39", "> 60"],
        "Género":                         ["F", "M"],
        "Nivel de Estudio":               ["Técnico", "Primaria"],
        "Título Homologado":              [None, None],
        "Ciudad de Residencia":           ["Bogota", "Bogota"],
        "Email":                          ["a@test.com", "p@test.com"],
        "Fecha Registro":                 ["2025-01-10", "2025-02-15"],
        "Programa de Gobierno":           ["victimas del conflicto armado", None],
        "Condiciones Especiales":         ["discapacidad física", "adulto mayor"],
        "Detalle Discapacidades":         ["fisica", None],
        "Situación Laboral":              ["desempleado", "pensionado"],
        "Agente Registra":                ["agente1", "agente2"],
        "Fecha Actualización":            [None, None],
        "% Hoja Vida":                    [80, 60],
        "Prestador Anterior":             [None, None],
        "Fecha Cambio Prestador":         [None, None],
        "Vereda/Localidad/Centro Poblado":[None, None],
        "Pertenece A":                    [None, None],
        "SISE_OFFLINE":                   [None, None],
        "Mes":                            [1, 2],
        "Año":                            [2025, 2025],
        "Punto Atención":                 ["punto_1", "punto_1"],
    })


@pytest.fixture
def raw_psicologas():
    """
    Minimal psicologas DataFrame with the original Excel column names
    (uppercase) as they arrive before clean_psicologas() processes them.
    """
    return pd.DataFrame({
        "NUMERO.1":          ["1000001", "1000004"],
        "MES":               [3, 3],
        "NUMERO":            [1, 2],
        "FECHA":             ["2025-03-02", "2025-03-08"],
        "ORIENTADOR":        ["Orientadora1", "Orientadora3"],
        "NOMBRE":            ["Ana Gomez", "Maria Lopez"],
        "TD":                ["CC", "CC"],
        "GENERO":            ["F", "F"],
        "EDAD":              [35, 45],
        "RANGO":             ["29-39", "40-49"],
        "TELEFONO":          ["3001234567", "3007654321"],
        "BARRIO":            ["barrio_x", "barrio_z"],
        "NIVEL DE FORMACIÓN":["Técnico", "Bachiller"],
        "FORMACIÓN":         ["contabilidad", None],
        "EXPERIENCIA LABORAL":["3 años", None],
        "POBLACIÓN":         ["VCA, discapacidad física", "migrante"],
        "CORREO ELECTRONICO":["a@test.com", "m@test.com"],
        "TALLER FIS":        [None, None],
        "OBSERVACIONES":     [None, None],
        "INTÉRES CURSO FORMACIÓN":             ["si", "no"],
        "VALIDACIÓN DE BACHILLERATO (SI / NO)":["no", "si"],
        "A TENER EN CUENTA": [None, None],
    })


# ===========================================================================
# 2. CLEANING
# ===========================================================================

class TestCleanOrientados:
    """
    clean_orientados():
      - Parses fechaagendamiento / fechaejecucion / fechaevaluacion to datetime.
      - Renames them with _orientacion suffix.
      - Renames usuarionombre → orientador.
      - Lowercases string cell values.
      - Does NOT groupby; preserves one row per input row.
      - Does NOT produce mes_evento / anio_evento (those come from
        build_orientacion_events).
    """

    def test_date_columns_renamed_with_suffix(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert "fechaagendamiento_orientacion" in result.columns
        assert "fechaejecucion_orientacion"    in result.columns
        assert "fechaevaluacion_orientacion"   in result.columns

    def test_original_date_column_names_removed(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        for old in ("fechaagendamiento", "fechaejecucion", "fechaevaluacion"):
            assert old not in result.columns

    def test_date_columns_are_datetime(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        for col in ["fechaagendamiento_orientacion",
                    "fechaejecucion_orientacion",
                    "fechaevaluacion_orientacion"]:
            assert pd.api.types.is_datetime64_any_dtype(result[col]), \
                f"{col} should be datetime"

    def test_usuarionombre_renamed_to_orientador(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert "orientador"    in result.columns
        assert "usuarionombre" not in result.columns

    def test_string_values_lowercased(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        # "F" → "f", "Bogota" → "bogota"
        assert result["sexo"].iloc[0] == "f"
        assert result["ciudad"].iloc[0] == "bogota"

    def test_does_not_drop_rows(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert len(result) == len(raw_orientados)

    def test_does_not_produce_mes_evento(self, raw_orientados):
        """mes_evento is the responsibility of build_orientacion_events, not here."""
        result = clean_orientados(raw_orientados.copy())
        assert "mes_evento"  not in result.columns
        assert "anio_evento" not in result.columns

    def test_nat_fechaevaluacion_tolerated(self, raw_orientados):
        """A NaT in fechaevaluacion must not drop the row."""
        result = clean_orientados(raw_orientados.copy())
        assert len(result) == 2
        assert pd.isna(result["fechaevaluacion_orientacion"].iloc[1])


class TestCleanTalleres:
    """
    clean_talleres():
      - Parses and renames dates with _taller suffix.
      - Renames usuarionombre → tallerista.
      - Lowercases string cell values.
      - Does NOT aggregate/groupby — every input row stays as its own row.
    """

    def test_date_columns_renamed_with_taller_suffix(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert "fechaagendamiento_taller" in result.columns
        assert "fechaejecucion_taller"    in result.columns
        assert "fechaevaluacion_taller"   in result.columns

    def test_original_date_column_names_removed(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        for old in ("fechaagendamiento", "fechaejecucion", "fechaevaluacion"):
            assert old not in result.columns

    def test_date_columns_are_datetime(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        for col in ["fechaagendamiento_taller",
                    "fechaejecucion_taller",
                    "fechaevaluacion_taller"]:
            assert pd.api.types.is_datetime64_any_dtype(result[col])

    def test_usuarionombre_renamed_to_tallerista(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert "tallerista"    in result.columns
        assert "usuarionombre" not in result.columns

    def test_does_not_aggregate_rows(self, raw_talleres):
        """Two raw rows for the same person → two cleaned rows, no groupby."""
        result = clean_talleres(raw_talleres.copy())
        assert len(result) == len(raw_talleres)

    def test_string_values_lowercased(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert result["sexo"].iloc[0] == "f"


class TestCleanRegistrados:
    """
    clean_registrados():
      - Renames 'Número Documento' column to 'numerodocumento'.
      - Aggregates to one row per person (groupby).
      - Joins 'Programa de Gobierno' and 'Condiciones Especiales'
        with comma when a person has multiple rows.
    """

    def test_numerodocumento_column_present(self, raw_registrados):
        result = clean_registrados(raw_registrados.copy())
        assert "numerodocumento" in result.columns

    def test_one_row_per_document(self, raw_registrados):
        result = clean_registrados(raw_registrados.copy())
        assert result["numerodocumento"].nunique() == len(result)

    def test_programa_gobierno_joined_when_duplicate_docs(self, raw_registrados):
        extra = raw_registrados.loc[[0]].copy()
        extra["Programa de Gobierno"] = "jovenes en accion"
        combined = pd.concat([raw_registrados, extra], ignore_index=True)
        result = clean_registrados(combined)
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "Programa de Gobierno"].iloc[0])
        assert "victimas del conflicto armado" in val
        assert "jovenes en accion" in val

    def test_condiciones_especiales_joined_when_duplicate_docs(self, raw_registrados):
        extra = raw_registrados.loc[[0]].copy()
        extra["Condiciones Especiales"] = "migrante"
        combined = pd.concat([raw_registrados, extra], ignore_index=True)
        result = clean_registrados(combined)
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "Condiciones Especiales"].iloc[0])
        assert "discapacidad" in val
        assert "migrante" in val


class TestCleanPsicologas:
    """
    clean_psicologas():
      - Renames 'NUMERO.1' to 'numerodocumento'.
      - Lowercases cell values (column names remain UPPERCASE).
      - Aggregates to one row per person.
      - Joins 'POBLACIÓN' with comma when person has multiple rows.
    """

    def test_numerodocumento_column_present(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        assert "numerodocumento" in result.columns
        assert "NUMERO.1" not in result.columns

    def test_cell_values_are_lowercased(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        # Column names stay uppercase; only cell values are lowercased.
        assert result["NOMBRE"].iloc[0] == result["NOMBRE"].iloc[0].lower()

    def test_column_names_remain_uppercase(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        assert "EDAD" in result.columns
        assert "POBLACIÓN" in result.columns

    def test_one_row_per_document(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        assert result["numerodocumento"].nunique() == len(result)

    def test_poblacion_joined_when_duplicate_docs(self, raw_psicologas):
        extra = raw_psicologas.loc[[0]].copy()
        extra["POBLACIÓN"] = "reincorporado"
        combined = pd.concat([raw_psicologas, extra], ignore_index=True)
        result = clean_psicologas(combined)
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "POBLACIÓN"].iloc[0]).lower()
        assert "vca" in val or "reincorporado" in val


# ===========================================================================
# 3. BUILD EVENT ROWS
# ===========================================================================

class TestBuildOrientacionEvents:
    """
    build_orientacion_events():
      - Adds tipo_evento = 'orientacion'.
      - Derives mes_evento and anio_evento from fechaejecucion_orientacion.
      - Drops rows where fechaejecucion_orientacion is NaT.
    """

    @pytest.fixture
    def cleaned(self, raw_orientados):
        return clean_orientados(raw_orientados.copy())

    def test_tipo_evento_is_orientacion(self, cleaned):
        result = build_orientacion_events(cleaned)
        assert (result["tipo_evento"] == "orientacion").all()

    def test_mes_evento_derived_correctly(self, cleaned):
        result = build_orientacion_events(cleaned)
        assert result["mes_evento"].iloc[0] == 3

    def test_anio_evento_derived_correctly(self, cleaned):
        result = build_orientacion_events(cleaned)
        assert result["anio_evento"].iloc[0] == 2025

    def test_mes_evento_is_nullable_int64(self, cleaned):
        result = build_orientacion_events(cleaned)
        assert result["mes_evento"].dtype == pd.Int64Dtype()

    def test_anio_evento_is_nullable_int64(self, cleaned):
        result = build_orientacion_events(cleaned)
        assert result["anio_evento"].dtype == pd.Int64Dtype()

    def test_drops_rows_with_nat_fechaejecucion(self):
        df = pd.DataFrame({
            "fechaejecucion_orientacion": [pd.NaT, pd.Timestamp("2025-03-02")],
            "fechaagendamiento_orientacion": [pd.NaT, pd.Timestamp("2025-03-01")],
            "fechaevaluacion_orientacion":   [pd.NaT, pd.Timestamp("2025-03-03")],
        })
        result = build_orientacion_events(df)
        assert len(result) == 1

    def test_does_not_drop_valid_rows(self, cleaned):
        result = build_orientacion_events(cleaned)
        # Both raw rows have valid fechaejecucion; both must survive.
        assert len(result) == len(cleaned)


class TestBuildTallerEvents:
    """
    build_taller_events():
      - Renames fechaejecucion_taller → fechaejecucion_orientacion (unified col).
      - Adds tipo_evento = 'taller'.
      - Derives mes_evento and anio_evento.
      - Drops rows where fechaejecucion is NaT.
    """

    @pytest.fixture
    def cleaned(self, raw_talleres):
        return clean_talleres(raw_talleres.copy())

    def test_tipo_evento_is_taller(self, cleaned):
        result = build_taller_events(cleaned)
        assert (result["tipo_evento"] == "taller").all()

    def test_date_cols_renamed_to_orientacion_names(self, cleaned):
        result = build_taller_events(cleaned)
        assert "fechaejecucion_orientacion"    in result.columns
        assert "fechaagendamiento_orientacion" in result.columns
        assert "fechaevaluacion_orientacion"   in result.columns

    def test_taller_date_col_names_removed(self, cleaned):
        result = build_taller_events(cleaned)
        assert "fechaejecucion_taller"    not in result.columns
        assert "fechaagendamiento_taller" not in result.columns

    def test_mes_evento_derived_correctly(self, cleaned):
        result = build_taller_events(cleaned)
        assert result["mes_evento"].iloc[0] == 3

    def test_anio_evento_derived_correctly(self, cleaned):
        result = build_taller_events(cleaned)
        assert result["anio_evento"].iloc[0] == 2025

    def test_drops_rows_with_nat_fechaejecucion(self, cleaned):
        """raw_talleres row 1 has NaT fechaevaluacion but valid fechaejecucion
        — only NaT fechaejecucion triggers a drop."""
        result = build_taller_events(cleaned)
        assert len(result) == len(cleaned)  # both rows have valid fechaejecucion

    def test_drops_row_with_nat_fechaejecucion_taller(self):
        df = pd.DataFrame({
            "fechaejecucion_taller":    [pd.NaT, pd.Timestamp("2025-03-11")],
            "fechaagendamiento_taller": [pd.NaT, pd.Timestamp("2025-03-10")],
            "fechaevaluacion_taller":   [pd.NaT, pd.NaT],
        })
        result = build_taller_events(df)
        assert len(result) == 1


# ===========================================================================
# 4. ENRICHMENT
# ===========================================================================

class TestEnrichEvents:
    """
    enrich_events():
      - Left-joins events ← registrados ← psicologas on numerodocumento.
      - Appends POBLACIÓN to condiciones_especiales, then drops POBLACIÓN.
      - Lowercases all column names.
      - Coerces edad to nullable Int64.
      - Never drops event rows (left join).
    """

    @pytest.fixture
    def events(self, raw_orientados, raw_talleres):
        cleaned_o = clean_orientados(raw_orientados.copy())
        cleaned_t = clean_talleres(raw_talleres.copy())
        oe = build_orientacion_events(cleaned_o)
        te = build_taller_events(cleaned_t)
        return pd.concat([oe, te], ignore_index=True)

    @pytest.fixture
    def registrados(self, raw_registrados):
        return clean_registrados(raw_registrados.copy())

    @pytest.fixture
    def psicologas(self, raw_psicologas):
        return clean_psicologas(raw_psicologas.copy())

    def test_returns_dataframe(self, events, registrados, psicologas):
        result = enrich_events(events, registrados, psicologas)
        assert isinstance(result, pd.DataFrame)

    def test_no_unresolved_x_y_columns(self, events, registrados, psicologas):
        result = enrich_events(events, registrados, psicologas)
        bad = [c for c in result.columns if c.endswith("_x") or c.endswith("_y")]
        assert bad == [], f"Unresolved duplicate columns: {bad}"

    def test_column_names_are_lowercase(self, events, registrados, psicologas):
        result = enrich_events(events, registrados, psicologas)
        for col in result.columns:
            assert col == col.lower(), f"Column '{col}' not fully lowercase"

    def test_poblacion_column_dropped(self, events, registrados, psicologas):
        result = enrich_events(events, registrados, psicologas)
        assert "población"  not in result.columns
        assert "poblacion"  not in result.columns
        assert "POBLACIÓN"  not in result.columns

    def test_edad_is_nullable_int64(self, events, registrados, psicologas):
        result = enrich_events(events, registrados, psicologas)
        assert result["edad"].dtype == pd.Int64Dtype()

    def test_condiciones_enriched_from_psicologas_poblacion(
        self, events, registrados, psicologas
    ):
        """doc 1000001 → POBLACIÓN='VCA, discapacidad física' appended."""
        result = enrich_events(events, registrados, psicologas)
        row = result[result["numerodocumento"] == "1000001"]
        assert not row.empty
        val = str(row["condiciones_especiales"].iloc[0]).lower()
        assert "vca" in val or "discapacidad" in val

    def test_does_not_drop_event_rows(self, events, registrados, psicologas):
        """Left join — no event rows may be lost."""
        result = enrich_events(events, registrados, psicologas)
        assert len(result) == len(events)

    def test_programa_de_gobierno_column_present(
        self, events, registrados, psicologas
    ):
        result = enrich_events(events, registrados, psicologas)
        assert "programa_de_gobierno" in result.columns


# ===========================================================================
# 5. DERIVED COLUMNS
# ===========================================================================

class TestDeriveAgeRange:

    @pytest.fixture
    def df_ages(self):
        return pd.DataFrame({
            "edad": pd.array([10, 20, 35, 45, 55, 65, None], dtype="Int64")
        })

    def test_under_18(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[0] == "< 18"

    def test_18_to_28(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[1] == "18-28"

    def test_29_to_39(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[2] == "29-39"

    def test_40_to_49(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[3] == "40-49"

    def test_50_to_59(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[4] == "50-59"

    def test_over_60(self, df_ages):
        assert derive_age_range(df_ages)["rango_de_edad"].iloc[5] == "> 60"

    def test_null_edad_returns_nan(self, df_ages):
        assert pd.isna(derive_age_range(df_ages)["rango_de_edad"].iloc[6])

    def test_does_not_drop_rows(self, df_ages):
        assert len(derive_age_range(df_ages)) == len(df_ages)

    def test_boundary_18_is_in_18_28_band(self):
        df = pd.DataFrame({"edad": pd.array([18], dtype="Int64")})
        assert derive_age_range(df)["rango_de_edad"].iloc[0] == "18-28"

    def test_boundary_29_is_in_29_39_band(self):
        df = pd.DataFrame({"edad": pd.array([29], dtype="Int64")})
        assert derive_age_range(df)["rango_de_edad"].iloc[0] == "29-39"

    def test_boundary_60_is_in_over_60_band(self):
        df = pd.DataFrame({"edad": pd.array([60], dtype="Int64")})
        assert derive_age_range(df)["rango_de_edad"].iloc[0] == "> 60"


# ===========================================================================
# 6. POPULATION CLASSIFICATION
# ===========================================================================

class TestClassifyEthnicGroups:

    @pytest.mark.parametrize("text,expected", [
        ("afrodescendiente",              "Afrodescendiente"),
        ("comunidad negra del pacifico",  "Afrodescendiente"),
        ("mulato mestizo",                "Afrodescendiente"),
        ("palenquero de san basilio",     "Afrodescendiente"),
        ("raizal isleno",                 "Raizal y/o Isleño"),
        ("comunidad indigena",            "Indígenas"),
        ("gitano nomada",                 "Gitano"),
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
        result = classify_ethnic_groups(classify_df(cond="sin condicion"))
        assert pd.isna(result["grupos_etnicos"].iloc[0])

    def test_empty_string_returns_nan(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond=""))
        assert pd.isna(result["grupos_etnicos"].iloc[0])

    def test_case_insensitive(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond="AFRODESCENDIENTE"))
        assert "Afrodescendiente" in result["grupos_etnicos"].iloc[0]


class TestClassifyVca:
    """
    classify_vca() assigns the string "VCA" (uppercase).
    After final_string_clean() it becomes "vca".
    Unit tests here check the pre-final_string_clean value.
    """

    def test_flagged_via_programa_de_gobierno(self, classify_df):
        result = classify_vca(classify_df(prog="victimas del conflicto armado"))
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

    def test_keyword_armado_in_programa_sufficient(self, classify_df):
        result = classify_vca(classify_df(prog="conflicto armado interno"))
        assert result["vca"].iloc[0] == "VCA"


class TestClassifyDisability:

    @pytest.mark.parametrize("text,expected_label", [
        ("discapacidad cognitiva",   "Cognitiva o Intelectual"),
        ("discapacidad intelectual", "Cognitiva o Intelectual"),
        ("discapacidad fisica",      "Física"),
        ("discapacidad visual",      "Visual"),
        ("discapacidad auditiva",    "Auditiva"),
        ("discapacidad múltiple",    "Múltiple"),
        ("sordoceguera severa",      "Sordoceguera"),
        ("trastorno psicosocial",    "Psicosocial"),
        ("en capacidad reducida",    "Discapacidad"),
    ])
    def test_disability_type_detected(self, classify_df, text, expected_label):
        result = classify_disability(classify_df(cond=text))
        assert result["discapacidad"].iloc[0] == expected_label

    def test_specific_label_wins_over_catchall(self, classify_df):
        """Pattern order: Física ([íi]sic) is evaluated before Discapacidad
        (capacidad).  The more specific label must win."""
        result = classify_disability(classify_df(cond="discapacidad fisica"))
        assert result["discapacidad"].iloc[0] == "Física"

    def test_cognitiva_wins_over_catchall(self, classify_df):
        result = classify_disability(classify_df(cond="cognitivo con capacidad"))
        assert result["discapacidad"].iloc[0] == "Cognitiva o Intelectual"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_disability(classify_df(cond="sin condicion"))
        assert pd.isna(result["discapacidad"].iloc[0])

    def test_multiple_rows_only_first_matching_pattern_wins(self, classify_df):
        """Rows already assigned a label must not be overwritten by later patterns."""
        result = classify_disability(classify_df(cond="discapacidad intelectual y visual"))
        # First matching pattern is r"ognitiv|telect" → Cognitiva o Intelectual
        assert result["discapacidad"].iloc[0] == "Cognitiva o Intelectual"


class TestClassifyMigrants:
    """
    classify_migrants() assigns "Migrante o Retornado" (mixed case).
    After final_string_clean() → "migrante o retornado".
    """

    def test_flagged_via_condiciones_migr(self, classify_df):
        result = classify_migrants(classify_df(cond="migrante venezolano"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_condiciones_retor(self, classify_df):
        result = classify_migrants(classify_df(cond="retornado de venezuela"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipodocumento_ppt(self, classify_df):
        result = classify_migrants(classify_df(tdoc="ppt permiso"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipodocumento_ce(self, classify_df):
        result = classify_migrants(classify_df(tdoc="cedula extranjeria ce"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipodocumento_dni(self, classify_df):
        result = classify_migrants(classify_df(tdoc="dni extranjero"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_migrants(classify_df(cond="residente local", tdoc="cc"))
        assert pd.isna(result["migrante"].iloc[0])

    def test_result_column_is_object_dtype(self, classify_df):
        """Must be object dtype so string assignment works on all pandas versions."""
        result = classify_migrants(classify_df(cond="migrante"))
        assert result["migrante"].dtype == object


class TestClassifyVvg:

    def test_flagged_via_viole(self, classify_df):
        result = classify_vvg(classify_df(cond="victima de violencia intrafamiliar"))
        assert result["vvg"].iloc[0] == "vvg"

    def test_flagged_via_vvg_text(self, classify_df):
        result = classify_vvg(classify_df(cond="vvg registrada"))
        assert result["vvg"].iloc[0] == "vvg"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_vvg(classify_df(cond="situacion economica dificil"))
        assert pd.isna(result["vvg"].iloc[0])

    def test_result_column_is_object_dtype(self, classify_df):
        result = classify_vvg(classify_df(cond="violencia"))
        assert result["vvg"].dtype == object


class TestClassifyReintegrated:

    def test_flagged_via_reincorporacion(self, classify_df):
        result = classify_reintegrated(classify_df(cond="proceso de reincorporacion farc"))
        assert result["reincorporados"].iloc[0] == "reincorporados"

    def test_flagged_via_reinsercion(self, classify_df):
        result = classify_reintegrated(classify_df(cond="reinsertado auc"))
        assert result["reincorporados"].iloc[0] == "reincorporados"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_reintegrated(classify_df(cond="sin antecedentes"))
        assert pd.isna(result["reincorporados"].iloc[0])

    def test_result_column_is_object_dtype(self, classify_df):
        result = classify_reintegrated(classify_df(cond="reincorporado"))
        assert result["reincorporados"].dtype == object


class TestRunAllClassifications:

    def test_all_classification_columns_present(self, classify_df):
        result = run_all_classifications(classify_df(cond="afrodescendiente").copy())
        expected = {
            "grupos_etnicos", "vca", "discapacidad",
            "migrante", "vvg", "reincorporados",
        }
        assert expected.issubset(set(result.columns))

    def test_no_rows_lost(self):
        df = pd.DataFrame({
            "condiciones_especiales": ["afrodescendiente", "migrante", "ninguno"],
            "programa_de_gobierno":   ["", "", ""],
            "tipodocumento":          ["cc", "ppt", "cc"],
        })
        assert len(run_all_classifications(df.copy())) == 3

    def test_vca_uppercase_before_final_clean(self, classify_df):
        """classify_vca assigns 'VCA' (uppercase) — final_string_clean lowercases it."""
        result = run_all_classifications(
            classify_df(prog="victimas del conflicto armado").copy()
        )
        assert result["vca"].iloc[0] == "VCA"

    def test_migrante_mixed_case_before_final_clean(self, classify_df):
        result = run_all_classifications(classify_df(cond="migrante", tdoc="ppt").copy())
        assert result["migrante"].iloc[0] == "Migrante o Retornado"


# ===========================================================================
# 7. FINAL CLEANING
# ===========================================================================

class TestFinalStringClean:

    def test_null_like_strings_replaced_with_pd_na(self):
        """All null-like string tokens must become pd.NA."""
        for token in ["nan", "NaN", "none", "None", "<na>", "<NA>",
                      "null", "Null", "nat", "n/a"]:
            df = pd.DataFrame({"a": [token]})
            result = final_string_clean(df)
            assert pd.isna(result["a"].iloc[0]), \
                f"Token '{token}' was not replaced with pd.NA"

    def test_strings_are_lowercased(self):
        df = pd.DataFrame({"a": ["HELLO", "World"]})
        result = final_string_clean(df)
        assert result["a"].iloc[0] == "hello"
        assert result["a"].iloc[1] == "world"

    def test_strings_are_stripped(self):
        df = pd.DataFrame({"a": ["  hello  ", " world "]})
        result = final_string_clean(df)
        assert result["a"].iloc[0] == "hello"

    def test_does_not_drop_rows(self):
        df = pd.DataFrame({"a": ["nan", "real", "value"]})
        assert len(final_string_clean(df)) == 3

    def test_vca_uppercased_by_classify_becomes_lowercase(self):
        df = pd.DataFrame({"a": ["VCA"], "condiciones_especiales": ["vca"]})
        result = final_string_clean(df)
        assert result["a"].iloc[0] == "vca"

    def test_migrante_mixed_case_becomes_lowercase(self):
        df = pd.DataFrame({"a": ["Migrante o Retornado"]})
        result = final_string_clean(df)
        assert result["a"].iloc[0] == "migrante o retornado"

    def test_date_columns_not_modified(self):
        """DATE_SCALAR_COLS must be skipped by the string cleaner."""
        ts = pd.Timestamp("2025-03-02")
        df = pd.DataFrame({
            "fechaejecucion_orientacion": [ts],
            "a": ["HELLO"],
        })
        result = final_string_clean(df)
        assert result["fechaejecucion_orientacion"].iloc[0] == ts

    def test_numeric_cols_not_modified(self):
        """NUMERIC_COLS must be skipped and retain their dtype."""
        df = pd.DataFrame({
            "edad":                pd.array([35], dtype="Int64"),
            "mes_evento":          pd.array([3],  dtype="Int64"),
            "anio_evento":         pd.array([2025], dtype="Int64"),
            "porcentajeasistencia": [80.0],
        })
        result = final_string_clean(df)
        assert result["edad"].dtype == pd.Int64Dtype()
        assert result["porcentajeasistencia"].iloc[0] == 80.0

    def test_real_values_not_nullified(self):
        df = pd.DataFrame({"a": ["migrante o retornado", "vca", "reincorporados"]})
        result = final_string_clean(df)
        assert result["a"].iloc[0] == "migrante o retornado"
        assert result["a"].iloc[1] == "vca"
        assert result["a"].iloc[2] == "reincorporados"


# ===========================================================================
# 8. FILTERING
# ===========================================================================

class TestFilterByMonth:
    """
    filter_by_month()         — any tipo_evento, matches mes_evento + anio_evento
    filter_orientacion_by_month() — tipo_evento='orientacion' + month
    filter_taller_by_month()      — tipo_evento='taller' + month
    """

    @pytest.fixture
    def event_df(self):
        return pd.DataFrame({
            "tipo_evento": ["orientacion", "orientacion", "taller", "taller"],
            "mes_evento":  pd.array([3, 3, 3, 4], dtype="Int64"),
            "anio_evento": pd.array([2025, 2025, 2025, 2025], dtype="Int64"),
            "sexo":        ["f", "m", "f", "f"],
        })

    def test_filter_by_month_keeps_all_types(self, event_df):
        result = filter_by_month(event_df, month=3, year=2025)
        assert len(result) == 3   # 2 orientacion + 1 taller in March

    def test_filter_by_month_empty_when_no_match(self, event_df):
        assert filter_by_month(event_df, month=12, year=2025).empty

    def test_filter_by_month_excludes_different_year(self):
        df = pd.DataFrame({
            "tipo_evento": ["orientacion", "orientacion"],
            "mes_evento":  pd.array([3, 3], dtype="Int64"),
            "anio_evento": pd.array([2024, 2025], dtype="Int64"),
        })
        result = filter_by_month(df, month=3, year=2025)
        assert len(result) == 1

    def test_filter_orientacion_keeps_only_orientacion(self, event_df):
        result = filter_orientacion_by_month(event_df, month=3, year=2025)
        assert len(result) == 2
        assert (result["tipo_evento"] == "orientacion").all()

    def test_filter_orientacion_empty_when_no_match(self, event_df):
        assert filter_orientacion_by_month(event_df, month=12, year=2025).empty

    def test_filter_taller_keeps_only_taller(self, event_df):
        result = filter_taller_by_month(event_df, month=3, year=2025)
        assert len(result) == 1
        assert (result["tipo_evento"] == "taller").all()

    def test_filter_taller_empty_when_no_match(self, event_df):
        assert filter_taller_by_month(event_df, month=12, year=2025).empty

    def test_filter_does_not_mutate_original(self, event_df):
        original_len = len(event_df)
        filter_by_month(event_df, month=3, year=2025)
        assert len(event_df) == original_len


# ===========================================================================
# 9. INTEGRATION — full in-memory pipeline
# ===========================================================================

class TestFullPipeline:
    """
    Exercises the complete pipeline using in-memory DataFrames, without any
    file I/O or database connections.  Tests the interaction between all
    steps end-to-end.
    """

    @pytest.fixture
    def full_df(self, raw_orientados, raw_talleres, raw_registrados, raw_psicologas):
        """Run every step manually using the real public API."""
        orientados  = clean_orientados(raw_orientados.copy())
        talleres    = clean_talleres(raw_talleres.copy())
        registrados = clean_registrados(raw_registrados.copy())
        psicologas  = clean_psicologas(raw_psicologas.copy())

        oe = build_orientacion_events(orientados)
        te = build_taller_events(talleres)
        events = pd.concat([oe, te], ignore_index=True)

        events = enrich_events(events, registrados, psicologas)
        events = derive_age_range(events)
        events = run_all_classifications(events)
        events = final_string_clean(events)
        return events

    def test_pipeline_returns_non_empty_dataframe(self, full_df):
        assert isinstance(full_df, pd.DataFrame) and not full_df.empty

    def test_all_classification_columns_exist(self, full_df):
        for col in ["grupos_etnicos", "vca", "discapacidad",
                    "migrante", "vvg", "reincorporados", "rango_de_edad"]:
            assert col in full_df.columns, f"Missing column: {col}"

    def test_tipo_evento_values_are_valid(self, full_df):
        valid = {"orientacion", "taller"}
        assert set(full_df["tipo_evento"].unique()).issubset(valid)

    def test_orientacion_rows_present(self, full_df):
        assert (full_df["tipo_evento"] == "orientacion").any()

    def test_taller_rows_present(self, full_df):
        assert (full_df["tipo_evento"] == "taller").any()

    def test_vca_flagged_and_lowercased_for_armed_conflict_record(self, full_df):
        """doc 1000001: programa_de_gobierno has 'victimas del conflicto armado'
        → classified as 'VCA', then final_string_clean → 'vca'."""
        row = full_df[full_df["numerodocumento"] == "1000001"]
        assert not row.empty
        assert row["vca"].iloc[0] == "vca"

    def test_no_literal_null_strings_remain(self, full_df):
        for col in full_df.select_dtypes(include=["object"]).columns:
            for bad in ["nan", "none", "<na>", "null"]:
                count = (full_df[col] == bad).sum()
                assert count == 0, \
                    f"Column '{col}' contains {count} literal '{bad}' strings"

    def test_no_unresolved_suffix_columns(self, full_df):
        bad = [c for c in full_df.columns if c.endswith("_x") or c.endswith("_y")]
        assert bad == [], f"Unresolved duplicate columns: {bad}"

    def test_mes_evento_and_anio_evento_populated(self, full_df):
        assert full_df["mes_evento"].notna().any()
        assert full_df["anio_evento"].notna().any()

    def test_filter_orientacion_by_month_returns_correct_subset(self, full_df):
        result = filter_orientacion_by_month(full_df, month=3, year=2025)
        assert not result.empty
        assert (result["tipo_evento"] == "orientacion").all()
        assert (result["mes_evento"] == 3).all()
        assert (result["anio_evento"] == 2025).all()

    def test_filter_taller_by_month_returns_correct_subset(self, full_df):
        result = filter_taller_by_month(full_df, month=3, year=2025)
        assert not result.empty
        assert (result["tipo_evento"] == "taller").all()

    def test_filter_by_month_union_covers_both_types(self, full_df):
        all_march = filter_by_month(full_df, month=3, year=2025)
        orientacion = filter_orientacion_by_month(full_df, month=3, year=2025)
        taller      = filter_taller_by_month(full_df, month=3, year=2025)
        assert len(all_march) == len(orientacion) + len(taller)

    def test_edad_is_nullable_int64_throughout(self, full_df):
        assert full_df["edad"].dtype == pd.Int64Dtype()

    def test_migrante_lowercased_after_final_clean(self, full_df):
        """Any 'Migrante o Retornado' assigned by classify_migrants must be
        lowercased to 'migrante o retornado' after final_string_clean."""
        non_null = full_df["migrante"].dropna()
        for val in non_null:
            assert val == val.lower(), \
                f"migrante value not lowercased: '{val}'"

    def test_vca_lowercased_after_final_clean(self, full_df):
        non_null = full_df["vca"].dropna()
        for val in non_null:
            assert val == val.lower(), \
                f"vca value not lowercased: '{val}'"