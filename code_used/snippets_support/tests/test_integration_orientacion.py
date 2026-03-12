"""
test_integration_orientacion.py
================================
Integration tests for the orientacion_hv ETL pipeline.

SCOPE
-----
These tests exercise the full pipeline composition end-to-end using
in-memory DataFrames — no Excel files, no PostgreSQL, no external modules.

They are distinct from the unit tests in test_orientacion_hv.py because they
test the CONTRACT between steps (how the output of one function flows into the
input of the next) rather than the behaviour of each function in isolation.

WHAT THESE TESTS COVER
-----------------------
  TestPipelineComposition
    - Full step sequence produces a non-empty DataFrame with the correct
      schema (tipo_evento, mes_evento, anio_evento, all classification cols).
    - Both 'orientacion' and 'taller' event types are present in the result.
    - Orientation events and taller events keep their own date values after
      build_taller_events() renames the taller date columns to the unified
      orientacion names.
    - Row count is correct: no rows silently dropped by any step (except
      NaT fechaejecucion rows, which must be dropped).
    - No duplicate _x / _y suffix columns survive the merge step.
    - All column names are fully lowercase after enrich_events().

  TestPartitioningAndFiltering
    - filter_orientacion_by_month() and filter_taller_by_month() correctly
      partition the pipeline result into non-overlapping subsets.
    - filter_by_month() returns the exact union of both.
    - Filtering a different month/year returns an empty DataFrame.
    - Filtering does not mutate the original DataFrame.

  TestClassificationEndToEnd
    - VCA, migrante, vvg, reincorporados, grupos_etnicos, and discapacidad
      labels produced by run_all_classifications() are still correct after
      final_string_clean() lowercases everything.
    - No null-like strings ("nan", "none", "<na>", "null", "nat") survive
      final_string_clean() in any object column.

  TestFinalCleanIdempotency
    - Calling final_string_clean() twice produces the same result as calling
      it once (safe to run multiple times without mangling data).

  TestExportAndCount
    - export_parquet() writes a valid Parquet file and returns the correct
      filename pattern (orientados_<year>_<month>.parquet).
    - The written Parquet has correct physical dtypes:
        porcentajeasistencia → float64
        edad / mes_evento / anio_evento → Int64 (nullable integer)
        fechaejecucion_orientacion → datetime64
    - The written Parquet contains exactly the rows passed to it.
    - write_count() writes the integer as a plain string to the given path.
    - write_count() result is readable back as an integer without error.

  TestPrintSummary
    - print_summary() runs without raising any exception (smoke test).
    - print_summary() accepts a DataFrame with no matching rows without
      crashing (edge case: month with zero sessions).

REQUIREMENTS
------------
  No database connection needed.
  No Excel files needed.
  Requires only: pytest, pandas, numpy, pyarrow or fastparquet (for parquet).

Run with:
    pytest test_integration_orientacion.py -v
"""

import os
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
    run_all_classifications,
    final_string_clean,
    filter_by_month,
    filter_orientacion_by_month,
    filter_taller_by_month,
    export_parquet,
    write_count,
    print_summary,
    _NULL_LIKE_STRINGS,
)


# ===========================================================================
# Shared in-memory fixtures
# ===========================================================================
#
# These fixtures mirror the shape of real Excel data after load_*() has
# lowercased column names.  They are intentionally richer than the unit-test
# fixtures so that classification cross-column interactions are exercised.
#
# Document roster:
#   1000001 — VCA (programa_de_gobierno), discapacidad física (condiciones)
#              + psicólogas POBLACIÓN: vca, discapacidad física
#   1000002 — migrante (tipodocumento=ppt)
#   1000003 — afrodescendiente (psicólogas POBLACIÓN)
#   1000004 — vvg (condiciones)
#   1000005 — reincorporado (condiciones)
#   1000006 — no special condition (control)
# ===========================================================================

@pytest.fixture(scope="module")
def raw_orientados():
    """Six orientation sessions across March and April 2025.
    Row for 1000006 has a NaT fechaejecucion — must be dropped."""
    return pd.DataFrame({
        "numerodocumento":         ["1000001","1000002","1000003","1000004","1000005","1000006"],
        "fechaagendamiento":       ["2025-03-01","2025-03-04","2025-03-07","2025-04-01","2025-04-05", "2025-03-10"],
        "fechaejecucion":          ["2025-03-02","2025-03-05","2025-03-08","2025-04-02","2025-04-06", pd.NaT],
        "fechaevaluacion":         ["2025-03-03","2025-03-06","2025-03-09","2025-04-03","2025-04-07", pd.NaT],
        "usuarionombre":           ["orientadora1","orientadora1","orientadora2","orientadora2","orientadora3","orientadora3"],
        "tipodocumento":           ["cc","ppt","cc","cc","cc","cc"],
        "correoelectronico":       ["a@t.com","b@t.com","c@t.com","d@t.com","e@t.com","f@t.com"],
        "primernombre":            ["Ana","Luis","Claudia","Jorge","Maria","Pedro"],
        "segundonombre":           [None,None,None,None,None,None],
        "primerapellido":          ["Gomez","Reyes","Salcedo","Torres","Ruiz","Pena"],
        "segundoapellido":         [None,None,None,None,None,None],
        "sexo":                    ["F","M","F","M","F","M"],
        "ciudad":                  ["bogota"]*6,
        "departamento":            ["cundinamarca"]*6,
        "area":                    ["urbano"]*6,
        "tipo":                    ["orientacion"]*6,
        "subtipo":                 ["individual"]*6,
        "nombreportafolio":        ["port_a"]*6,
        "nombreconvocatoria":      ["conv_1"]*6,
        "aprobacion":              ["si"]*6,
        "porcentajeasistencia":    [100.0, 80.0, 90.0, 75.0, 85.0, 70.0],
        "prestadornombre":         ["prestador_a"]*6,
        "institucionnombre":       ["inst_a"]*6,
        "instituciondireccion":    ["calle 1"]*6,
        "institucionmunicipio":    ["bog"]*6,
        "instituciondepartamento": ["cund"]*6,
        "programagobiernosino":    ["si","no","no","no","no","no"],
        "programagobierno":        ["victimas del conflicto armado",None,None,None,None,None],
        "alianzasentidadesexternas":[None]*6,
        "agencianombre":           ["agencia_a"]*6,
        "numerotelefono":          ["3001234567"]*6,
        "indicador":               ["I1"]*6,
        "tipodireccionamiento":    ["dir_a"]*6,
    })


@pytest.fixture(scope="module")
def raw_talleres():
    """Two taller sessions in March 2025 for docs 1000001 and 1000002."""
    return pd.DataFrame({
        "numerodocumento":         ["1000001","1000002"],
        "fechaagendamiento":       ["2025-03-10","2025-03-12"],
        "fechaejecucion":          ["2025-03-11","2025-03-13"],
        "fechaevaluacion":         ["2025-03-12", pd.NaT],
        "usuarionombre":           ["tallerista1","tallerista1"],
        "indicador":               ["I2","I2"],
        "tipodireccionamiento":    ["taller","taller"],
        "tipodocumento":           ["cc","ppt"],
        "correoelectronico":       ["a@t.com","b@t.com"],
        "primernombre":            ["Ana","Luis"],
        "segundonombre":           [None,None],
        "primerapellido":          ["Gomez","Reyes"],
        "segundoapellido":         [None,None],
        "sexo":                    ["f","m"],
        "ciudad":                  ["bogota","bogota"],
        "departamento":            ["cundinamarca","cundinamarca"],
        "area":                    ["urbano","urbano"],
        "tipo":                    ["taller","taller"],
        "subtipo":                 ["grupal","grupal"],
        "nombreportafolio":        ["port_b","port_b"],
        "nombreconvocatoria":      ["conv_2","conv_2"],
        "aprobacion":              ["si","si"],
        "porcentajeasistencia":    [90.0, 85.0],
        "prestadornombre":         ["prestador_a","prestador_a"],
        "institucionnombre":       ["inst_a","inst_a"],
        "instituciondireccion":    ["calle 1","calle 1"],
        "institucionmunicipio":    ["bog","bog"],
        "instituciondepartamento": ["cund","cund"],
        "programagobiernosino":    ["si","si"],
        "programagobierno":        [None,None],
        "alianzasentidadesexternas":[None,None],
        "agencianombre":           ["agencia_a","agencia_a"],
        "numerotelefono":          ["3001234567","3001234568"],
    })


@pytest.fixture(scope="module")
def raw_registrados():
    return pd.DataFrame({
        "Número Documento":               ["1000001","1000002","1000003","1000004","1000005","1000006"],
        "No. ":                           [1,2,3,4,5,6],
        "Programa / Aliado\n(Si aplica)": [None]*6,
        "Barrio donde vive":              ["barrio_x"]*6,
        "Tipo Documento":                 ["CC","PPT","CC","CC","CC","CC"],
        "TIPO_REGISTRO":                  ["Registro_nuevo"]*6,
        "Nombres":                        ["Ana","Luis","Claudia","Jorge","Maria","Pedro"],
        "Apellidos":                      ["Gomez","Reyes","Salcedo","Torres","Ruiz","Pena"],
        "Celular":                        ["3001234567"]*6,
        "Teléfono":                       [None]*6,
        "Canal de Registro":              ["Agencia"]*6,
        "Edad":                           [35, 28, 42, 31, 55, 60],
        "Rango_Edad":                     ["29-39","18-28","40-49","29-39","50-59","> 60"],
        "Género":                         ["F","M","F","M","F","M"],
        "Nivel de Estudio":               ["Técnico"]*6,
        "Título Homologado":              [None]*6,
        "Ciudad de Residencia":           ["Bogota"]*6,
        "Email":                          ["a@t.com","b@t.com","c@t.com","d@t.com","e@t.com","f@t.com"],
        "Fecha Registro":                 ["2025-01-10"]*6,
        "Programa de Gobierno":           ["victimas del conflicto armado",None,None,None,None,None],
        "Condiciones Especiales":         [
            "discapacidad física",
            "migrante venezolano",
            "sin condicion",
            "victima de violencia vvg",
            "proceso de reincorporacion farc",
            "",
        ],
        "Detalle Discapacidades":         ["fisica",None,None,None,None,None],
        "Situación Laboral":              ["desempleado"]*6,
        "Agente Registra":                ["agente1"]*6,
        "Fecha Actualización":            [None]*6,
        "% Hoja Vida":                    [80]*6,
        "Prestador Anterior":             [None]*6,
        "Fecha Cambio Prestador":         [None]*6,
        "Vereda/Localidad/Centro Poblado":[None]*6,
        "Pertenece A":                    [None]*6,
        "SISE_OFFLINE":                   [None]*6,
        "Mes":                            [1]*6,
        "Año":                            [2025]*6,
        "Punto Atención":                 ["punto_1"]*6,
    })


@pytest.fixture(scope="module")
def raw_psicologas():
    return pd.DataFrame({
        "NUMERO.1":          ["1000001","1000003"],
        "MES":               [3,3],
        "NUMERO":            [1,2],
        "FECHA":             ["2025-03-02","2025-03-08"],
        "ORIENTADOR":        ["Orientadora1","Orientadora2"],
        "NOMBRE":            ["Ana Gomez","Claudia Salcedo"],
        "TD":                ["CC","CC"],
        "GENERO":            ["F","F"],
        "EDAD":              [35,42],
        "RANGO":             ["29-39","40-49"],
        "TELEFONO":          ["3001234567","3007654321"],
        "BARRIO":            ["barrio_x","barrio_z"],
        "NIVEL DE FORMACIÓN":["Técnico","Bachiller"],
        "FORMACIÓN":         ["contabilidad",None],
        "EXPERIENCIA LABORAL":["3 años",None],
        "POBLACIÓN":         ["vca, discapacidad física","afrodescendiente"],
        "CORREO ELECTRONICO":["a@t.com","c@t.com"],
        "TALLER FIS":        [None,None],
        "OBSERVACIONES":     [None,None],
        "INTÉRES CURSO FORMACIÓN":             ["si","no"],
        "VALIDACIÓN DE BACHILLERATO (SI / NO)":["no","si"],
        "A TENER EN CUENTA": [None,None],
    })


# ===========================================================================
# Module-scoped pipeline result (built once, shared across all test classes)
# ===========================================================================

@pytest.fixture(scope="module")
def full_pipeline_df(raw_orientados, raw_talleres, raw_registrados, raw_psicologas):
    """
    Run the complete pipeline step-by-step using in-memory fixtures.
    Mirrors exactly what run_pipeline() does internally, without file I/O.
    """
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


# ===========================================================================
# INTEGRATION-01: Full pipeline composition
# ===========================================================================

class TestPipelineComposition:
    """
    Verifies that all pipeline steps compose correctly — schema, row count,
    and column cleanliness after the full sequence.
    """

    def test_result_is_non_empty_dataframe(self, full_pipeline_df):
        assert isinstance(full_pipeline_df, pd.DataFrame)
        assert not full_pipeline_df.empty

    def test_both_event_types_present(self, full_pipeline_df):
        types = set(full_pipeline_df["tipo_evento"].unique())
        assert "orientacion" in types, "No orientacion rows in pipeline result"
        assert "taller"      in types, "No taller rows in pipeline result"

    def test_correct_orientacion_row_count(self, full_pipeline_df):
        """
        5 raw orientation rows; the row with NaT fechaejecucion (1000006)
        is dropped by build_orientacion_events() → 5 rows remain.
        """
        orientacion_rows = full_pipeline_df[
            full_pipeline_df["tipo_evento"] == "orientacion"
        ]
        assert len(orientacion_rows) == 5, (
            f"Expected 5 orientacion rows (1 NaT-dropped), "
            f"got {len(orientacion_rows)}"
        )

    def test_correct_taller_row_count(self, full_pipeline_df):
        """2 taller sessions in raw_talleres → 2 taller rows."""
        taller_rows = full_pipeline_df[full_pipeline_df["tipo_evento"] == "taller"]
        assert len(taller_rows) == 2

    def test_nat_fechaejecucion_row_dropped(self, full_pipeline_df):
        """doc 1000006 had NaT fechaejecucion — must not appear as orientacion."""
        orientacion = full_pipeline_df[
            (full_pipeline_df["tipo_evento"] == "orientacion") &
            (full_pipeline_df["numerodocumento"] == "1000006")
        ]
        assert orientacion.empty, \
            "NaT-fechaejecucion row for 1000006 was not dropped"

    def test_no_unresolved_suffix_columns(self, full_pipeline_df):
        bad = [c for c in full_pipeline_df.columns
               if c.endswith("_x") or c.endswith("_y")]
        assert bad == [], f"Unresolved merge columns: {bad}"

    def test_all_column_names_lowercase(self, full_pipeline_df):
        for col in full_pipeline_df.columns:
            assert col == col.lower(), f"Column not lowercase: '{col}'"

    def test_required_schema_columns_present(self, full_pipeline_df):
        required = {
            "tipo_evento", "mes_evento", "anio_evento",
            "fechaejecucion_orientacion", "numerodocumento",
            "grupos_etnicos", "vca", "discapacidad",
            "migrante", "vvg", "reincorporados",
            "rango_de_edad", "edad", "sexo",
            "condiciones_especiales", "programa_de_gobierno",
        }
        missing = required - set(full_pipeline_df.columns)
        assert missing == set(), f"Required columns missing: {missing}"

    def test_mes_evento_is_nullable_int64(self, full_pipeline_df):
        assert full_pipeline_df["mes_evento"].dtype == pd.Int64Dtype()

    def test_anio_evento_is_nullable_int64(self, full_pipeline_df):
        assert full_pipeline_df["anio_evento"].dtype == pd.Int64Dtype()

    def test_edad_is_nullable_int64(self, full_pipeline_df):
        assert full_pipeline_df["edad"].dtype == pd.Int64Dtype()

    def test_fechaejecucion_is_datetime(self, full_pipeline_df):
        assert pd.api.types.is_datetime64_any_dtype(
            full_pipeline_df["fechaejecucion_orientacion"]
        )

    def test_taller_dates_unified_to_orientacion_column_names(
        self, full_pipeline_df
    ):
        """
        build_taller_events() renames fechaejecucion_taller to
        fechaejecucion_orientacion.  The unified column must be present
        and taller rows must have a valid datetime value in it.
        """
        taller_rows = full_pipeline_df[full_pipeline_df["tipo_evento"] == "taller"]
        valid_dates = taller_rows["fechaejecucion_orientacion"].notna()
        assert valid_dates.any(), \
            "Taller rows have no valid fechaejecucion_orientacion after renaming"

    def test_poblacion_column_not_present_after_enrich(self, full_pipeline_df):
        for name in ("población", "poblacion", "POBLACIÓN"):
            assert name not in full_pipeline_df.columns


# ===========================================================================
# INTEGRATION-02: Partitioning and filtering
# ===========================================================================

class TestPartitioningAndFiltering:
    """
    Verifies that the three filter functions correctly partition the
    combined events DataFrame produced by the pipeline.
    """

    def test_filter_orientacion_returns_only_orientacion(
        self, full_pipeline_df
    ):
        result = filter_orientacion_by_month(full_pipeline_df, month=3, year=2025)
        assert not result.empty
        assert (result["tipo_evento"] == "orientacion").all()
        assert (result["mes_evento"] == 3).all()
        assert (result["anio_evento"] == 2025).all()

    def test_filter_taller_returns_only_taller(self, full_pipeline_df):
        result = filter_taller_by_month(full_pipeline_df, month=3, year=2025)
        assert not result.empty
        assert (result["tipo_evento"] == "taller").all()
        assert (result["mes_evento"] == 3).all()
        assert (result["anio_evento"] == 2025).all()

    def test_filter_by_month_is_union_of_both_types(self, full_pipeline_df):
        all_march    = filter_by_month(full_pipeline_df, month=3, year=2025)
        orientacion  = filter_orientacion_by_month(full_pipeline_df, month=3, year=2025)
        taller       = filter_taller_by_month(full_pipeline_df, month=3, year=2025)
        assert len(all_march) == len(orientacion) + len(taller)

    def test_orientacion_and_taller_sets_are_disjoint(self, full_pipeline_df):
        orientacion = filter_orientacion_by_month(full_pipeline_df, month=3, year=2025)
        taller      = filter_taller_by_month(full_pipeline_df, month=3, year=2025)
        common_idx  = orientacion.index.intersection(taller.index)
        assert len(common_idx) == 0, \
            "orientacion and taller filters returned overlapping rows"

    def test_filter_different_month_returns_empty(self, full_pipeline_df):
        assert filter_orientacion_by_month(
            full_pipeline_df, month=12, year=2025
        ).empty

    def test_filter_different_year_returns_empty(self, full_pipeline_df):
        assert filter_taller_by_month(
            full_pipeline_df, month=3, year=2099
        ).empty

    def test_april_orientacion_rows_correctly_separated(self, full_pipeline_df):
        """Docs 1000004 and 1000005 have fechaejecucion in April 2025."""
        april = filter_orientacion_by_month(full_pipeline_df, month=4, year=2025)
        assert len(april) == 2
        docs = set(april["numerodocumento"].tolist())
        assert "1000004" in docs and "1000005" in docs

    def test_march_taller_rows_count(self, full_pipeline_df):
        """2 taller sessions were loaded for March 2025."""
        result = filter_taller_by_month(full_pipeline_df, month=3, year=2025)
        assert len(result) == 2

    def test_filter_does_not_mutate_source(self, full_pipeline_df):
        original_len = len(full_pipeline_df)
        filter_orientacion_by_month(full_pipeline_df, month=3, year=2025)
        filter_taller_by_month(full_pipeline_df, month=3, year=2025)
        filter_by_month(full_pipeline_df, month=3, year=2025)
        assert len(full_pipeline_df) == original_len


# ===========================================================================
# INTEGRATION-03: Classification results end-to-end
# ===========================================================================

class TestClassificationEndToEnd:
    """
    Classification labels must survive the full pipeline including
    final_string_clean() (which lowercases everything).
    """

    def test_vca_flagged_via_programa_de_gobierno(self, full_pipeline_df):
        """doc 1000001: programa_de_gobierno='victimas del conflicto armado'
        → classify_vca assigns 'VCA' → final_string_clean → 'vca'."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000001") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty, "doc 1000001 orientacion row not found"
        assert row["vca"].iloc[0] == "vca"

    def test_discapacidad_flagged_via_condiciones(self, full_pipeline_df):
        """doc 1000001: condiciones='discapacidad física' → 'física' after clean."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000001") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty
        # Pattern [íi]sic matches física → label "Física" → lowercased "física"
        assert row["discapacidad"].iloc[0] == "física"

    def test_migrante_flagged_via_tipodocumento_ppt(self, full_pipeline_df):
        """doc 1000002: tipodocumento='ppt' → 'Migrante o Retornado' → lowercased."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000002") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty, "doc 1000002 orientacion not found"
        assert row["migrante"].iloc[0] == "migrante o retornado"

    def test_afrodescendiente_flagged_via_psicologas_poblacion(
        self, full_pipeline_df
    ):
        """doc 1000003: psicologas POBLACIÓN='afrodescendiente' enriches
        condiciones_especiales → classify_ethnic_groups detects it."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000003") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty, "doc 1000003 orientacion not found"
        groups = row["grupos_etnicos"].iloc[0]
        # grupos_etnicos is a list before final_string_clean;
        # after clean it may stay a list (object col) but each string is lowercased.
        groups_str = str(groups).lower()
        assert "afrodescendiente" in groups_str, \
            f"Expected 'afrodescendiente' in grupos_etnicos, got: {groups_str}"

    def test_vvg_flagged_via_condiciones(self, full_pipeline_df):
        """doc 1000004: condiciones='victima de violencia vvg' → 'vvg'."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000004") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty, "doc 1000004 orientacion not found"
        assert row["vvg"].iloc[0] == "vvg"

    def test_reincorporado_flagged_via_condiciones(self, full_pipeline_df):
        """doc 1000005: condiciones='proceso de reincorporacion farc' → 'reincorporados'."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000005") &
            (full_pipeline_df["tipo_evento"] == "orientacion")
        ]
        assert not row.empty, "doc 1000005 orientacion not found"
        assert row["reincorporados"].iloc[0] == "reincorporados"

    def test_control_doc_has_no_special_classifications(self, full_pipeline_df):
        """doc 1000006 has no special conditions → all classification cols NaN.
        Note: 1000006 was dropped (NaT fechaejecucion) so it only appears as taller=absent."""
        # 1000006 has no taller rows either — just confirm no false-positive rows
        rows = full_pipeline_df[full_pipeline_df["numerodocumento"] == "1000006"]
        # If somehow present (shouldn't be as orientacion), classification must be null
        for row in rows.itertuples():
            assert pd.isna(row.vca)
            assert pd.isna(row.vvg)
            assert pd.isna(row.reincorporados)

    def test_vca_on_taller_row_for_doc_1000001(self, full_pipeline_df):
        """
        doc 1000001 also attended a taller in March 2025.
        The enrichment (left-join on numerodocumento) must bring VCA to
        the taller row too.
        """
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000001") &
            (full_pipeline_df["tipo_evento"] == "taller")
        ]
        assert not row.empty, "doc 1000001 taller row not found"
        assert row["vca"].iloc[0] == "vca"

    def test_migrante_on_taller_row_for_doc_1000002(self, full_pipeline_df):
        """doc 1000002 also attended a taller — migrante flag must carry over."""
        row = full_pipeline_df[
            (full_pipeline_df["numerodocumento"] == "1000002") &
            (full_pipeline_df["tipo_evento"] == "taller")
        ]
        assert not row.empty, "doc 1000002 taller row not found"
        assert row["migrante"].iloc[0] == "migrante o retornado"

    def test_no_null_like_strings_in_any_object_column(self, full_pipeline_df):
        """After final_string_clean(), no null-like string token should remain."""
        for col in full_pipeline_df.select_dtypes(include=["object"]).columns:
            for token in _NULL_LIKE_STRINGS:
                count = (full_pipeline_df[col] == token).sum()
                assert count == 0, (
                    f"Column '{col}' contains {count} literal '{token}' strings "
                    f"after final_string_clean()"
                )

    def test_all_vca_values_are_lowercase(self, full_pipeline_df):
        non_null = full_pipeline_df["vca"].dropna()
        for val in non_null:
            assert val == val.lower(), f"vca not lowercased: '{val}'"

    def test_all_migrante_values_are_lowercase(self, full_pipeline_df):
        non_null = full_pipeline_df["migrante"].dropna()
        for val in non_null:
            assert val == val.lower(), f"migrante not lowercased: '{val}'"


# ===========================================================================
# INTEGRATION-04: Idempotency of final_string_clean()
# ===========================================================================

class TestFinalCleanIdempotency:
    """
    Running final_string_clean() a second time must not change the result.
    This guards against accidental double-application in the pipeline.
    """

    def test_second_application_is_identical(self, full_pipeline_df):
        once  = final_string_clean(full_pipeline_df.copy())
        twice = final_string_clean(once.copy())

        # Compare object columns (numeric / datetime cols have separate tests)
        str_cols = once.select_dtypes(include=["object"]).columns
        for col in str_cols:
            # Both sides: treat pd.NA and None as equal "null"
            first_vals  = once[col].fillna("__NULL__").tolist()
            second_vals = twice[col].fillna("__NULL__").tolist()
            assert first_vals == second_vals, \
                f"Column '{col}' differs after second application of final_string_clean()"

    def test_numeric_cols_unchanged_after_second_application(
        self, full_pipeline_df
    ):
        once  = final_string_clean(full_pipeline_df.copy())
        twice = final_string_clean(once.copy())
        for col in ["mes_evento", "anio_evento", "edad"]:
            if col in once.columns:
                assert once[col].tolist() == twice[col].tolist(), \
                    f"Numeric column '{col}' changed after second final_string_clean()"

    def test_date_cols_unchanged_after_second_application(
        self, full_pipeline_df
    ):
        once  = final_string_clean(full_pipeline_df.copy())
        twice = final_string_clean(once.copy())
        col = "fechaejecucion_orientacion"
        if col in once.columns:
            assert once[col].tolist() == twice[col].tolist(), \
                f"Date column '{col}' changed after second final_string_clean()"


# ===========================================================================
# INTEGRATION-05: Export and count utilities
# ===========================================================================

class TestExportAndCount:
    """
    Verifies export_parquet() writes a correctly-typed Parquet file and
    write_count() produces the expected output.
    """

    @pytest.fixture
    def march_slice(self, full_pipeline_df, tmp_path, monkeypatch):
        """
        Returns a (df, tmp_path) pair where df is the March 2025 subset
        and the CWD is set to tmp_path so export_parquet() writes there.
        """
        df = filter_by_month(full_pipeline_df, month=3, year=2025).copy()
        monkeypatch.chdir(tmp_path)
        return df, tmp_path

    def test_export_parquet_returns_correct_filename(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        assert filename == "orientados_2025_3.parquet"

    def test_export_parquet_file_exists(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        assert os.path.exists(filename), f"Parquet file not created: {filename}"

    def test_export_parquet_row_count_matches_input(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert len(written) == len(df), (
            f"Parquet has {len(written)} rows; expected {len(df)}"
        )

    def test_porcentajeasistencia_is_float64_in_parquet(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert written["porcentajeasistencia"].dtype == "float64", (
            f"porcentajeasistencia dtype: {written['porcentajeasistencia'].dtype}"
        )

    def test_mes_evento_is_int64_in_parquet(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert pd.api.types.is_integer_dtype(written["mes_evento"]), (
            f"mes_evento dtype: {written['mes_evento'].dtype}"
        )

    def test_anio_evento_is_int64_in_parquet(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert pd.api.types.is_integer_dtype(written["anio_evento"]), (
            f"anio_evento dtype: {written['anio_evento'].dtype}"
        )

    def test_edad_is_int64_in_parquet(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert pd.api.types.is_integer_dtype(written["edad"]), (
            f"edad dtype: {written['edad'].dtype}"
        )

    def test_fechaejecucion_is_datetime_in_parquet(self, march_slice):
        df, tmp = march_slice
        filename = export_parquet(df, month=3, year=2025)
        written  = pd.read_parquet(filename)
        assert pd.api.types.is_datetime64_any_dtype(
            written["fechaejecucion_orientacion"]
        ), f"fechaejecucion_orientacion dtype: {written['fechaejecucion_orientacion'].dtype}"

    def test_write_count_creates_file(self, tmp_path):
        path = str(tmp_path / "count.txt")
        write_count(42, path)
        assert os.path.exists(path)

    def test_write_count_content_is_correct_integer_string(self, tmp_path):
        path = str(tmp_path / "count.txt")
        write_count(17, path)
        with open(path) as f:
            content = f.read()
        assert content == "17"

    def test_write_count_zero(self, tmp_path):
        path = str(tmp_path / "count_zero.txt")
        write_count(0, path)
        with open(path) as f:
            assert int(f.read()) == 0

    def test_write_count_readable_as_int(self, tmp_path):
        path = str(tmp_path / "count_readable.txt")
        write_count(123, path)
        with open(path) as f:
            assert int(f.read()) == 123


# ===========================================================================
# INTEGRATION-06: print_summary() smoke tests
# ===========================================================================

class TestPrintSummary:
    """
    print_summary() must not raise under any condition — it is purely for
    operator visibility and should never block the pipeline.
    """

    def test_smoke_with_valid_data(self, full_pipeline_df, capsys):
        print_summary(full_pipeline_df, month=3, year=2025)
        out = capsys.readouterr().out
        assert "orientados" in out.lower() or "taller" in out.lower()

    def test_smoke_with_empty_month(self, full_pipeline_df, capsys):
        """Month 12 has no data — must not raise."""
        print_summary(full_pipeline_df, month=12, year=2025)
        # No assertion on output content; just must not raise

    def test_smoke_with_empty_dataframe(self, capsys):
        """Empty DataFrame must not raise."""
        empty = pd.DataFrame(columns=[
            "tipo_evento", "mes_evento", "anio_evento",
            "sexo", "discapacidad", "vca", "vvg",
            "migrante", "grupos_etnicos", "reincorporados",
        ])
        empty["mes_evento"]  = empty["mes_evento"].astype("Int64")
        empty["anio_evento"] = empty["anio_evento"].astype("Int64")
        print_summary(empty, month=3, year=2025)