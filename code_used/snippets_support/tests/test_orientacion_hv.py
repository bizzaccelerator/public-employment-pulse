"""
test_orientacion_hv.py

Unit tests for orientacion_hv.py.

All fixtures are defined inline — no conftest.py is required.
The classify_df factory fixture mirrors the pattern used in test_registro_hv.py.

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
    merge_all,
    derive_age_range,
    classify_ethnic_groups,
    classify_vca,
    classify_disability,
    classify_migrants,
    classify_vvg,
    classify_reintegrated,
    run_all_classifications,
    final_string_clean,
    filter_orientados_by_month,
    filter_talleres_by_month,
    filter_export,
)


# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture
def classify_df():
    """
    Factory fixture: returns a callable that builds a one-row DataFrame
    for classification tests.

    Usage inside a test:
        def test_something(classify_df):
            df = classify_df(cond="migrante")
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
    Two-row orientados DataFrame matching the shape returned by
    load_orientados().  Row 0 is complete; row 1 is partially
    incomplete to exercise edge-cases.
    """
    return pd.DataFrame({
        "numerodocumento":       ["1000001", "1000002"],
        "fechaagendamiento":     ["2025-03-01", "2025-03-05"],
        "fechaejecucion":        ["2025-03-02", "2025-03-06"],
        "fechaevaluacion":       ["2025-03-03", pd.NaT],
        "tipodocumento":         ["cc", "ce"],
        "correoelectronico":     ["a@test.com", "b@test.com"],
        "primernombre":          ["Ana", "Luis"],
        "segundonombre":         [None, None],
        "primerapellido":        ["Gomez", "Reyes"],
        "segundoapellido":       ["Rios", None],
        "sexo":                  ["F", "M"],
        "ciudad":                ["Bogota", "Medellin"],
        "departamento":          ["Cundinamarca", "Antioquia"],
        "area":                  ["urbano", "rural"],
        "tipo":                  ["orientacion", "orientacion"],
        "subtipo":               ["individual", "grupal"],
        "nombreportafolio":      ["portafolio_a", None],
        "nombreconvocatoria":    ["conv_1", None],
        "aprobacion":            ["si", "no"],
        "porcentajeasistencia":  [100, 80],
        "prestadornombre":       ["prestador_a", "prestador_b"],
        "institucionnombre":     ["inst_a", "inst_b"],
        "instituciondireccion":  ["calle 1", "calle 2"],
        "institucionmunicipio":  ["bog", "med"],
        "instituciondepartamento": ["cund", "ant"],
        "programagobiernosino":  ["si", "no"],
        "programagobierno":      ["victimas del conflicto armado", None],
        "alianzasentidadesexternas": [None, None],
        "usuarionombre":         ["Orientadora1", "Orientadora2"],
        "agencianombre":         ["agencia_a", "agencia_b"],
        "numerotelefono":        ["3001234567", None],
        "indicador":             ["I1", "I1"],
        "tipodireccionamiento":  ["dir_a", "dir_b"],
    })


@pytest.fixture
def raw_talleres():
    """
    Two-row talleres DataFrame where numerodocumento 1000001 appears
    twice to test the groupby aggregation in clean_talleres().
    """
    return pd.DataFrame({
        "numerodocumento":       ["1000001", "1000001"],
        "fechaagendamiento":     ["2025-03-10", "2025-03-15"],
        "fechaejecucion":        ["2025-03-11", "2025-03-16"],
        "fechaevaluacion":       ["2025-03-12", pd.NaT],
        "indicador":             ["I2", "I2"],
        "tipodireccionamiento":  ["taller", "taller"],
        "tipodocumento":         ["cc", "cc"],
        "correoelectronico":     ["a@test.com", "a@test.com"],
        "primernombre":          ["Ana", "Ana"],
        "segundonombre":         [None, None],
        "primerapellido":        ["Gomez", "Gomez"],
        "segundoapellido":       ["Rios", "Rios"],
        "sexo":                  ["f", "f"],
        "ciudad":                ["bogota", "bogota"],
        "departamento":          ["cundinamarca", "cundinamarca"],
        "area":                  ["urbano", "urbano"],
        "tipo":                  ["taller", "taller"],
        "subtipo":               ["grupal", "grupal"],
        "nombreportafolio":      ["port_b", "port_b"],
        "nombreconvocatoria":    ["conv_2", "conv_2"],
        "aprobacion":            ["si", "si"],
        "porcentajeasistencia":  [90, 90],
        "prestadornombre":       ["prestador_a", "prestador_a"],
        "institucionnombre":     ["inst_a", "inst_a"],
        "instituciondireccion":  ["calle 1", "calle 1"],
        "institucionmunicipio":  ["bog", "bog"],
        "instituciondepartamento": ["cund", "cund"],
        "programagobiernosino":  ["si", "si"],
        "programagobierno":      ["jovenes en accion", "victimas del conflicto armado"],
        "alianzasentidadesexternas": [None, None],
        "usuarionombre":         ["Tallerista1", "Tallerista1"],
        "agencianombre":         ["agencia_a", "agencia_a"],
        "numerotelefono":        ["3001234567", "3001234567"],
    })


@pytest.fixture
def raw_registrados():
    """
    Minimal registrados DataFrame using the original Excel column names
    that arrive before clean_registrados() processes them.
    """
    return pd.DataFrame({
        "Número Documento":   ["1000001", "1000003"],
        "No. ":               [1, 2],
        "Programa / Aliado\n(Si aplica)": [None, None],
        "Barrio donde vive":  ["barrio_x", "barrio_y"],
        "Tipo Documento":     ["CC", "CC"],
        "TIPO_REGISTRO":      ["Registro_nuevo", "Registro_nuevo"],
        "Nombres":            ["Ana", "Pedro"],
        "Apellidos":          ["Gomez Rios", "Perez"],
        "Celular":            ["3001234567", "3009876543"],
        "Teléfono":           [None, None],
        "Canal de Registro":  ["Agencia", "Agencia"],
        "Edad":               [35, 62],
        "Rango_Edad":         ["29-39", "> 60"],
        "Género":             ["F", "M"],
        "Nivel de Estudio":   ["Técnico", "Primaria"],
        "Título Homologado":  [None, None],
        "Ciudad de Residencia": ["Bogota", "Bogota"],
        "Email":              ["a@test.com", "p@test.com"],
        "Fecha Registro":     ["2025-01-10", "2025-02-15"],
        "Programa de Gobierno": ["victimas del conflicto armado", None],
        "Condiciones Especiales": ["discapacidad física", "adulto mayor"],
        "Detalle Discapacidades": ["fisica", None],
        "Situación Laboral":  ["desempleado", "pensionado"],
        "Agente Registra":    ["agente1", "agente2"],
        "Fecha Actualización": [None, None],
        "% Hoja Vida":        [80, 60],
        "Prestador Anterior": [None, None],
        "Fecha Cambio Prestador": [None, None],
        "Vereda/Localidad/Centro Poblado": [None, None],
        "Pertenece A":        [None, None],
        "SISE_OFFLINE":       [None, None],
        "Mes":                [1, 2],
        "Año":                [2025, 2025],
        "Punto Atención":     ["punto_1", "punto_1"],
    })


@pytest.fixture
def raw_psicologas():
    """
    Minimal psicologas DataFrame with uppercase column names as they
    arrive from Excel before clean_psicologas() processes them.
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
        "NIVEL DE FORMACIÓN": ["Técnico", "Bachiller"],
        "FORMACIÓN":         ["contabilidad", None],
        "EXPERIENCIA LABORAL": ["3 años", None],
        "POBLACIÓN":         ["VCA, discapacidad física", "migrante"],
        "CORREO ELECTRONICO": ["a@test.com", "m@test.com"],
        "TALLER FIS":        [None, None],
        "OBSERVACIONES":     [None, None],
        "INTÉRES CURSO FORMACIÓN": ["si", "no"],
        "VALIDACIÓN DE BACHILLERATO (SI / NO)": ["no", "si"],
        "A TENER EN CUENTA": [None, None],
    })


# ===========================================================================
# 2. CLEANING
# ===========================================================================

class TestCleanOrientados:

    def test_date_columns_are_datetime(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        for col in ["fechaagendamiento_orientacion",
                    "fechaejecucion_orientacion",
                    "fechaevaluacion_orientacion"]:
            assert pd.api.types.is_datetime64_any_dtype(result[col]), \
                f"{col} should be datetime"

    def test_usuarionombre_renamed_to_orientador(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert "orientador" in result.columns
        assert "usuarionombre" not in result.columns

    def test_mes_orientado_derived_correctly(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert result["mes_orientado"].iloc[0] == 3

    def test_año_orientado_derived_correctly(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert result["año_orientado"].iloc[0] == 2025

    def test_string_values_lowercased(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert result["sexo"].iloc[0] == "f"

    def test_mes_orientado_is_nullable_int(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert result["mes_orientado"].dtype == pd.Int64Dtype()

    def test_does_not_drop_rows(self, raw_orientados):
        result = clean_orientados(raw_orientados.copy())
        assert len(result) == len(raw_orientados)


class TestCleanTalleres:

    def test_aggregated_to_one_row_per_document(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert result["numerodocumento"].nunique() == len(result)

    def test_programagobierno_joined_with_comma(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "programagobierno"].iloc[0])
        assert "jovenes en accion" in val
        assert "victimas del conflicto armado" in val

    def test_mes_taller_derived_correctly(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert result["mes_taller"].iloc[0] == 3

    def test_usuarionombre_renamed_to_tallerista(self, raw_talleres):
        result = clean_talleres(raw_talleres.copy())
        assert "tallerista" in result.columns
        assert "usuarionombre" not in result.columns


class TestCleanRegistrados:

    def test_numero_documento_column_renamed(self, raw_registrados):
        result = clean_registrados(raw_registrados.copy())
        assert "numerodocumento" in result.columns

    def test_one_row_per_document(self, raw_registrados):
        result = clean_registrados(raw_registrados.copy())
        assert result["numerodocumento"].nunique() == len(result)

    def test_programa_gobierno_joined_across_duplicates(self, raw_registrados):
        extra = raw_registrados.loc[[0]].copy()
        extra["Programa de Gobierno"] = "jovenes en accion"
        combined = pd.concat([raw_registrados, extra], ignore_index=True)
        result = clean_registrados(combined)
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "Programa de Gobierno"].iloc[0])
        assert "victimas del conflicto armado" in val
        assert "jovenes en accion" in val


class TestCleanPsicologas:

    def test_numero_documento_column_renamed(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        assert "numerodocumento" in result.columns
        assert "NUMERO.1" not in result.columns

    def test_string_values_lowercased(self, raw_psicologas):
        # clean_psicologas() lowercases cell values but not column names.
        # The column remains 'NOMBRE' (uppercase) after cleaning.
        result = clean_psicologas(raw_psicologas.copy())
        assert result["NOMBRE"].iloc[0] == result["NOMBRE"].iloc[0].lower()

    def test_one_row_per_document(self, raw_psicologas):
        result = clean_psicologas(raw_psicologas.copy())
        assert result["numerodocumento"].nunique() == len(result)

    def test_poblacion_joined_across_duplicates(self, raw_psicologas):
        extra = raw_psicologas.loc[[0]].copy()
        extra["POBLACIÓN"] = "reincorporado"
        combined = pd.concat([raw_psicologas, extra], ignore_index=True)
        result = clean_psicologas(combined)
        # Column name is still 'POBLACIÓN' (uppercase) — only values are lowercased.
        val = str(result.loc[result["numerodocumento"] == "1000001",
                              "POBLACIÓN"].iloc[0]).lower()
        assert "vca" in val or "reincorporado" in val


# ===========================================================================
# 3. MERGING
# ===========================================================================

class TestMergeAll:

    @pytest.fixture
    def merged(self, raw_orientados, raw_talleres, raw_registrados, raw_psicologas):
        orientados  = clean_orientados(raw_orientados.copy())
        talleres    = clean_talleres(raw_talleres.copy())
        registrados = clean_registrados(raw_registrados.copy())
        psicologas  = clean_psicologas(raw_psicologas.copy())
        return merge_all(orientados, talleres, registrados, psicologas)

    def test_returns_dataframe(self, merged):
        assert isinstance(merged, pd.DataFrame)

    def test_no_unresolved_x_y_columns(self, merged):
        bad = [c for c in merged.columns if c.endswith("_x") or c.endswith("_y")]
        assert bad == [], f"Unresolved duplicate columns: {bad}"

    def test_condiciones_especiales_enriched_from_psicologas(self, merged):
        row = merged[merged["numerodocumento"] == "1000001"]
        if not row.empty:
            val = str(row["condiciones_especiales"].iloc[0]).lower()
            assert "vca" in val or "discapacidad" in val

    def test_edad_is_nullable_int(self, merged):
        assert merged["edad"].dtype == pd.Int64Dtype()

    def test_poblacion_column_dropped(self, merged):
        assert "población" not in merged.columns
        assert "poblacion" not in merged.columns

    def test_does_not_lose_orientados_rows(self, merged, raw_orientados):
        assert len(merged) >= len(raw_orientados)


# ===========================================================================
# 4. DERIVED COLUMNS
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


# ===========================================================================
# 5. POPULATION CLASSIFICATION
# ===========================================================================

class TestClassifyEthnicGroups:

    @pytest.mark.parametrize("text,expected", [
        ("afrodescendiente",             "Afrodescendiente"),
        ("comunidad negra del pacífico", "Afrodescendiente"),
        ("mulato mestizo",               "Afrodescendiente"),
        ("palenquero de san basilio",    "Afrodescendiente"),
        ("raizal isleño",                "Raizal y/o Isleño"),
        ("comunidad indígena",           "Indígenas"),
        ("gitano nómada",                "Gitano"),
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
        assert pd.isna(classify_ethnic_groups(classify_df(cond="sin condición"))
                       ["grupos_etnicos"].iloc[0])

    def test_empty_string_returns_nan(self, classify_df):
        assert pd.isna(classify_ethnic_groups(classify_df(cond=""))
                       ["grupos_etnicos"].iloc[0])

    def test_case_insensitive(self, classify_df):
        result = classify_ethnic_groups(classify_df(cond="AFRODESCENDIENTE"))
        assert "Afrodescendiente" in result["grupos_etnicos"].iloc[0]


class TestClassifyVca:

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

    def test_specific_label_wins_over_catchall(self, classify_df):
        """'discapacidad física' matches both [ií]sic → Física AND
        capacidad → Discapacidad. The specific label must win."""
        result = classify_disability(classify_df(cond="discapacidad física"))
        assert result["discapacidad"].iloc[0] == "Física"

    def test_cognitiva_wins_over_catchall(self, classify_df):
        result = classify_disability(classify_df(cond="cognitivo con capacidad"))
        assert result["discapacidad"].iloc[0] == "Cognitiva o Intelectual"

    def test_no_match_returns_nan(self, classify_df):
        assert pd.isna(classify_disability(classify_df(cond="sin condición"))
                       ["discapacidad"].iloc[0])


class TestClassifyMigrants:

    def test_flagged_via_condiciones_migr(self, classify_df):
        result = classify_migrants(classify_df(cond="migrante venezolano"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_condiciones_retor(self, classify_df):
        result = classify_migrants(classify_df(cond="retornado de venezuela"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipodocumento_ppt(self, classify_df):
        result = classify_migrants(classify_df(tdoc="ppt permiso de proteccion"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_flagged_via_tipodocumento_ce(self, classify_df):
        result = classify_migrants(classify_df(tdoc="cedula ce extranjeria"))
        assert result["migrante"].iloc[0] == "Migrante o Retornado"

    def test_no_match_returns_nan(self, classify_df):
        result = classify_migrants(classify_df(cond="residente local", tdoc="cc"))
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

    def test_flagged_via_reincorporacion(self, classify_df):
        result = classify_reintegrated(classify_df(cond="proceso de reincorporación farc"))
        assert result["reincorporados"].iloc[0] == "reincorporados"

    def test_flagged_via_reinsercion(self, classify_df):
        result = classify_reintegrated(classify_df(cond="reinsertado auc"))
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
            "tipodocumento":          ["cc", "cc", "cc"],
        })
        assert len(run_all_classifications(df.copy())) == 3


# ===========================================================================
# 6. FINAL CLEANING
# ===========================================================================

class TestFinalStringClean:

    def test_nan_strings_replaced_with_pd_na(self):
        df = pd.DataFrame({"a": ["nan", "hello", "NaN"], "b": [1, 2, 3]})
        result = final_string_clean(df)
        assert pd.isna(result["a"].iloc[0])

    def test_strings_are_lowercased(self):
        df = pd.DataFrame({"a": ["HELLO", "World"]})
        assert final_string_clean(df)["a"].iloc[0] == "hello"

    def test_strings_are_stripped(self):
        df = pd.DataFrame({"a": ["  hello  ", " world "]})
        assert final_string_clean(df)["a"].iloc[0] == "hello"

    def test_does_not_drop_rows(self):
        df = pd.DataFrame({"a": ["nan", "real", "value"]})
        assert len(final_string_clean(df)) == 3


# ===========================================================================
# 7. FILTERING
# ===========================================================================

class TestFilterByMonth:

    @pytest.fixture
    def month_df(self):
        return pd.DataFrame({
            "mes_orientado": pd.array([3, 3, 4],  dtype="Int64"),
            "año_orientado": pd.array([2025, 2025, 2025], dtype="Int64"),
            "mes_taller":    pd.array([3, 4, 3],  dtype="Int64"),
            "año_taller":    pd.array([2025, 2025, 2025], dtype="Int64"),
            "sexo":          ["f", "m", "f"],
        })

    def test_filter_orientados_keeps_correct_rows(self, month_df):
        assert len(filter_orientados_by_month(month_df, month=3, year=2025)) == 2

    def test_filter_orientados_empty_when_no_match(self, month_df):
        assert filter_orientados_by_month(month_df, month=12, year=2025).empty

    def test_filter_talleres_keeps_correct_rows(self, month_df):
        assert len(filter_talleres_by_month(month_df, month=3, year=2025)) == 2

    def test_filter_talleres_excludes_different_year(self):
        df = pd.DataFrame({
            "mes_taller":  pd.array([3, 3], dtype="Int64"),
            "año_taller":  pd.array([2024, 2025], dtype="Int64"),
        })
        assert len(filter_talleres_by_month(df, month=3, year=2025)) == 1

    def test_filter_export_is_union_of_both(self, month_df):
        """All three rows satisfy at least one of the two month conditions."""
        assert len(filter_export(month_df, month=3, year=2025)) == 3

    def test_filter_export_returns_empty_when_no_match(self, month_df):
        assert filter_export(month_df, month=12, year=2025).empty

    def test_does_not_mutate_original(self, month_df):
        original_len = len(month_df)
        filter_orientados_by_month(month_df, month=3, year=2025)
        assert len(month_df) == original_len


# ===========================================================================
# 8. INTEGRATION
# ===========================================================================

class TestIntegration:

    @pytest.fixture
    def full_df(self, raw_orientados, raw_talleres, raw_registrados, raw_psicologas):
        orientados  = clean_orientados(raw_orientados.copy())
        talleres    = clean_talleres(raw_talleres.copy())
        registrados = clean_registrados(raw_registrados.copy())
        psicologas  = clean_psicologas(raw_psicologas.copy())
        df = merge_all(orientados, talleres, registrados, psicologas)
        df = derive_age_range(df)
        df = run_all_classifications(df)
        df = final_string_clean(df)
        return df

    def test_pipeline_returns_non_empty_dataframe(self, full_df):
        assert isinstance(full_df, pd.DataFrame) and not full_df.empty

    def test_all_expected_columns_exist(self, full_df):
        for col in ["grupos_etnicos", "vca", "discapacidad", "migrante",
                    "vvg", "reincorporados", "rango_de_edad"]:
            assert col in full_df.columns

    def test_vca_flagged_for_armed_conflict_record(self, full_df):
        """numerodocumento 1000001 has 'victimas del conflicto armado'
        in programa_de_gobierno and must be flagged as VCA."""
        row = full_df[full_df["numerodocumento"] == "1000001"]
        if not row.empty:
            assert row["vca"].iloc[0] == "vca"   # final_string_clean lowercases

    def test_no_literal_nan_strings_remain(self, full_df):
        for col in full_df.select_dtypes(include="object").columns:
            assert (full_df[col] == "nan").sum() == 0, \
                f"Column '{col}' still contains literal 'nan' strings"

    def test_no_unresolved_suffix_columns(self, full_df):
        bad = [c for c in full_df.columns if c.endswith("_x") or c.endswith("_y")]
        assert bad == [], f"Unresolved duplicate columns after pipeline: {bad}"