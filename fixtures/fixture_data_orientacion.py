"""
fixture_data_orientacion.py
===========================
Writes a synthetic Excel file that mirrors the three-source structure
consumed by orientacion_hv.run_pipeline():

  Sheet BD_Indicador_1   → orientados   (SISE file)
  Sheet Reporte_Indicador_2 → talleres  (SISE file)
  Sheet BD_Acumulado-2024-2026 → registrados
  Sheet Orientados        → psicologas

All three sheets are written to a SINGLE workbook so the fixture can be
passed to run_pipeline() directly via the sise_psico / registries /
psicologist paths.

FIXTURE ROWS
------------
SISE (BD_Indicador_1) — orientados
  Row 0  doc=1000001  Mar 2025  sexo=F  prog=victimas del conflicto armado  → VCA
  Row 1  doc=1000002  Mar 2025  sexo=M  condicion=discapacidad física       → PCD Física
  Row 2  doc=1000003  Mar 2025  sexo=F  condicion=afrodescendiente          → Étnico
  Row 3  doc=1000004  Mar 2025  tipodoc=ppt                                 → Migrante
  Row 4  doc=1000005  Apr 2025  condicion=violencia vvg                     → VVG
  Row 5  doc=1000006  Apr 2025  condicion=reincorporación farc              → Reincorporado
  Row 6  doc=1000007  Feb 2024  (excluded — wrong year)
  Row 7  doc=1000001  Mar 2025  DUPLICATE of Row 0 (same doc+date+orientador)
  Row 8  doc=None     Mar 2025  (excluded — missing document)

SISE (Reporte_Indicador_2) — talleres
  Row 0  doc=1000001  Mar 2025  taller FIS

Registrados (BD_Acumulado-2024-2026)
  doc=1000001  prog=victimas del conflicto armado
  doc=1000002  condicion=discapacidad física

Psicologas (Orientados)
  doc=1000003  POBLACIÓN=afrodescendiente
  doc=1000004  POBLACIÓN=migrante venezolano
"""

from datetime import datetime
import pandas as pd


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------

def _orientados_rows() -> pd.DataFrame:
    base_orient = {
        "numerodocumento":   None,
        "fechaagendamiento": None,
        "fechaejecucion":    None,
        "fechaevaluacion":   None,
        "tipodocumento":     "cc",
        "correoelectronico": None,
        "primernombre":      None,
        "segundonombre":     None,
        "primerapellido":    None,
        "segundoapellido":   None,
        "sexo":              None,
        "ciudad":            "bogota",
        "departamento":      "cundinamarca",
        "area":              "urbano",
        "tipo":              "orientacion",
        "subtipo":           "individual",
        "nombreportafolio":  None,
        "nombreconvocatoria": None,
        "aprobacion":        "si",
        "porcentajeasistencia": 100,
        "prestadornombre":   "prestador_a",
        "institucionnombre": "inst_a",
        "instituciondireccion": "calle 1",
        "institucionmunicipio": "bog",
        "instituciondepartamento": "cund",
        "programagobiernosino": "si",
        "programagobierno":  None,
        "alianzasentidadesexternas": None,
        "usuarionombre":     "Orientadora1",
        "agencianombre":     "agencia_a",
        "numerotelefono":    "3001234567",
        "indicador":         "I1",
        "tipodireccionamiento": "dir_a",
    }

    rows = []

    # Row 0: VCA via programa_de_gobierno
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000001",
        "fechaagendamiento": datetime(2025, 3, 1),
        "fechaejecucion":    datetime(2025, 3, 2),
        "fechaevaluacion":   datetime(2025, 3, 3),
        "sexo": "f",
        "primernombre": "Ana",   "primerapellido": "Gomez",
        "correoelectronico": "a@test.com",
        "programagobierno": "victimas del conflicto armado",
    })
    rows.append(r)

    # Row 1: PCD Física
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000002",
        "fechaagendamiento": datetime(2025, 3, 5),
        "fechaejecucion":    datetime(2025, 3, 6),
        "sexo": "m",
        "primernombre": "Luis",  "primerapellido": "Reyes",
        "correoelectronico": "b@test.com",
    })
    rows.append(r)

    # Row 2: Étnico (afrodescendiente) — via psicologas enrichment
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000003",
        "fechaagendamiento": datetime(2025, 3, 8),
        "fechaejecucion":    datetime(2025, 3, 9),
        "sexo": "f",
        "primernombre": "Maria", "primerapellido": "Lopez",
        "correoelectronico": "c@test.com",
    })
    rows.append(r)

    # Row 3: Migrante via tipodocumento=ppt
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000004",
        "fechaagendamiento": datetime(2025, 3, 10),
        "fechaejecucion":    datetime(2025, 3, 11),
        "tipodocumento": "ppt",
        "sexo": "m",
        "primernombre": "Carlos", "primerapellido": "Vega",
        "correoelectronico": "d@test.com",
    })
    rows.append(r)

    # Row 4: VVG — April 2025
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000005",
        "fechaagendamiento": datetime(2025, 4, 1),
        "fechaejecucion":    datetime(2025, 4, 2),
        "sexo": "f",
        "primernombre": "Sofia",  "primerapellido": "Torres",
        "correoelectronico": "e@test.com",
        "programagobierno": "violencia vvg",
    })
    rows.append(r)

    # Row 5: Reincorporado — April 2025
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000006",
        "fechaagendamiento": datetime(2025, 4, 5),
        "fechaejecucion":    datetime(2025, 4, 6),
        "sexo": "m",
        "primernombre": "Pedro",  "primerapellido": "Diaz",
        "correoelectronico": "f@test.com",
        "programagobierno": "reincorporación farc",
    })
    rows.append(r)

    # Row 6: Wrong year (Feb 2024) — must be excluded
    r = base_orient.copy()
    r.update({
        "numerodocumento": "1000007",
        "fechaagendamiento": datetime(2024, 2, 1),
        "fechaejecucion":    datetime(2024, 2, 2),
        "sexo": "f",
        "primernombre": "Elena", "primerapellido": "Castro",
        "correoelectronico": "g@test.com",
    })
    rows.append(r)

    # Row 7: Duplicate of Row 0 (same doc + same fechaejecucion + same orientador)
    r = rows[0].copy()
    rows.append(r)

    # Row 8: Missing document — must be excluded
    r = base_orient.copy()
    r.update({
        "numerodocumento": None,
        "fechaagendamiento": datetime(2025, 3, 12),
        "fechaejecucion":    datetime(2025, 3, 13),
        "sexo": "m",
        "primernombre": "Juan", "primerapellido": "Mora",
    })
    rows.append(r)

    df = pd.DataFrame(rows)
    df["numerodocumento"] = df["numerodocumento"].astype(str)
    return df


def _talleres_rows() -> pd.DataFrame:
    _t = pd.DataFrame([{
        "numerodocumento":    "1000001",
        "fechaagendamiento":  datetime(2025, 3, 15),
        "fechaejecucion":     datetime(2025, 3, 16),
        "fechaevaluacion":    datetime(2025, 3, 17),
        "indicador":          "I2",
        "tipodireccionamiento": "taller",
        "tipodocumento":      "cc",
        "correoelectronico":  "a@test.com",
        "primernombre":       "ana",
        "segundonombre":      None,
        "primerapellido":     "gomez",
        "segundoapellido":    None,
        "sexo":               "f",
        "ciudad":             "bogota",
        "departamento":       "cundinamarca",
        "area":               "urbano",
        "tipo":               "taller",
        "subtipo":            "grupal",
        "nombreportafolio":   "port_b",
        "nombreconvocatoria": "conv_2",
        "aprobacion":         "si",
        "porcentajeasistencia": 90,
        "prestadornombre":    "prestador_a",
        "institucionnombre":  "inst_a",
        "instituciondireccion": "calle 1",
        "institucionmunicipio": "bog",
        "instituciondepartamento": "cund",
        "programagobiernosino": "si",
        "programagobierno":   "jovenes en accion",
        "alianzasentidadesexternas": None,
        "usuarionombre":      "Tallerista1",
        "agencianombre":      "agencia_a",
        "numerotelefono":     "3001234567",
    }])
    _t["numerodocumento"] = _t["numerodocumento"].astype(str)
    return _t


def _registrados_rows() -> pd.DataFrame:
    _r = pd.DataFrame([
        {
            "Número Documento": "1000005",
            "No. ": 5,
            "Programa / Aliado\n(Si aplica)": None,
            "Barrio donde vive": "barrio_a",
            "Tipo Documento": "CC",
            "TIPO_REGISTRO": "Registro_nuevo",
            "Nombres": "Sofia",
            "Apellidos": "Torres",
            "Celular": "3001111111",
            "Teléfono": None,
            "Canal de Registro": "Agencia",
            "Edad": 32,
            "Rango_Edad": "29-39",
            "Género": "F",
            "Nivel de Estudio": "Técnico",
            "Título Homologado": None,
            "Ciudad de Residencia": "Bogota",
            "Email": "e@test.com",
            "Fecha Registro": datetime(2025, 4, 1),
            "Programa de Gobierno": None,
            "Condiciones Especiales": "violencia vvg",
            "Detalle Discapacidades": None,
            "Situación Laboral": "desempleado",
            "Agente Registra": "agente3",
            "Fecha Actualización": None,
            "% Hoja Vida": 50,
            "Prestador Anterior": None,
            "Fecha Cambio Prestador": None,
            "Vereda/Localidad/Centro Poblado": None,
            "Pertenece A": None,
            "SISE_OFFLINE": None,
            "Mes": 4,
            "Año": 2025,
            "Punto Atención": "punto_1",
        },
        {
            "Número Documento": "1000006",
            "No. ": 6,
            "Programa / Aliado\n(Si aplica)": None,
            "Barrio donde vive": "barrio_b",
            "Tipo Documento": "CC",
            "TIPO_REGISTRO": "Registro_nuevo",
            "Nombres": "Pedro",
            "Apellidos": "Diaz",
            "Celular": "3002222222",
            "Teléfono": None,
            "Canal de Registro": "Agencia",
            "Edad": 40,
            "Rango_Edad": "40-49",
            "Género": "M",
            "Nivel de Estudio": "Bachiller",
            "Título Homologado": None,
            "Ciudad de Residencia": "Cali",
            "Email": "f@test.com",
            "Fecha Registro": datetime(2025, 4, 5),
            "Programa de Gobierno": None,
            "Condiciones Especiales": "reincorporación farc",
            "Detalle Discapacidades": None,
            "Situación Laboral": "desempleado",
            "Agente Registra": "agente3",
            "Fecha Actualización": None,
            "% Hoja Vida": 40,
            "Prestador Anterior": None,
            "Fecha Cambio Prestador": None,
            "Vereda/Localidad/Centro Poblado": None,
            "Pertenece A": None,
            "SISE_OFFLINE": None,
            "Mes": 4,
            "Año": 2025,
            "Punto Atención": "punto_1",
        },
        {
            "Número Documento": "1000001",
            "No. ": 1,
            "Programa / Aliado\n(Si aplica)": None,
            "Barrio donde vive": "barrio_x",
            "Tipo Documento": "CC",
            "TIPO_REGISTRO": "Registro_nuevo",
            "Nombres": "Ana",
            "Apellidos": "Gomez",
            "Celular": "3001234567",
            "Teléfono": None,
            "Canal de Registro": "Agencia",
            "Edad": 35,
            "Rango_Edad": "29-39",
            "Género": "F",
            "Nivel de Estudio": "Técnico",
            "Título Homologado": None,
            "Ciudad de Residencia": "Bogota",
            "Email": "a@test.com",
            "Fecha Registro": datetime(2025, 1, 10),
            "Programa de Gobierno": "victimas del conflicto armado",
            "Condiciones Especiales": None,
            "Detalle Discapacidades": None,
            "Situación Laboral": "desempleado",
            "Agente Registra": "agente1",
            "Fecha Actualización": None,
            "% Hoja Vida": 80,
            "Prestador Anterior": None,
            "Fecha Cambio Prestador": None,
            "Vereda/Localidad/Centro Poblado": None,
            "Pertenece A": None,
            "SISE_OFFLINE": None,
            "Mes": 1,
            "Año": 2025,
            "Punto Atención": "punto_1",
        },
        {
            "Número Documento": "1000002",
            "No. ": 2,
            "Programa / Aliado\n(Si aplica)": None,
            "Barrio donde vive": "barrio_y",
            "Tipo Documento": "CC",
            "TIPO_REGISTRO": "Registro_nuevo",
            "Nombres": "Luis",
            "Apellidos": "Reyes",
            "Celular": "3009876543",
            "Teléfono": None,
            "Canal de Registro": "Agencia",
            "Edad": 28,
            "Rango_Edad": "18-28",
            "Género": "M",
            "Nivel de Estudio": "Bachiller",
            "Título Homologado": None,
            "Ciudad de Residencia": "Medellin",
            "Email": "b@test.com",
            "Fecha Registro": datetime(2025, 1, 15),
            "Programa de Gobierno": None,
            "Condiciones Especiales": "discapacidad física",
            "Detalle Discapacidades": "fisica",
            "Situación Laboral": "desempleado",
            "Agente Registra": "agente2",
            "Fecha Actualización": None,
            "% Hoja Vida": 60,
            "Prestador Anterior": None,
            "Fecha Cambio Prestador": None,
            "Vereda/Localidad/Centro Poblado": None,
            "Pertenece A": None,
            "SISE_OFFLINE": None,
            "Mes": 1,
            "Año": 2025,
            "Punto Atención": "punto_1",
        },
    ])
    _r["Número Documento"] = _r["Número Documento"].astype(str)
    return _r


def _psicologas_rows() -> pd.DataFrame:
    _p = pd.DataFrame([
        {
            "NUMERO.1":    "1000003",
            "MES":         3,
            "NUMERO":      1,
            "FECHA":       datetime(2025, 3, 9),
            "ORIENTADOR":  "Orientadora1",
            "NOMBRE":      "Maria Lopez",
            "TD":          "CC",
            "GENERO":      "F",
            "EDAD":        30,
            "RANGO":       "29-39",
            "TELEFONO":    "3005555555",
            "BARRIO":      "barrio_z",
            "NIVEL DE FORMACIÓN": "Técnico",
            "FORMACIÓN":   "administracion",
            "EXPERIENCIA LABORAL": "2 años",
            "POBLACIÓN":   "afrodescendiente",
            "CORREO ELECTRONICO": "c@test.com",
            "TALLER FIS":  None,
            "OBSERVACIONES": None,
            "INTÉRES CURSO FORMACIÓN": "si",
            "VALIDACIÓN DE BACHILLERATO (SI / NO)": "no",
            "A TENER EN CUENTA": None,
        },
        {
            "NUMERO.1":    "1000004",
            "MES":         3,
            "NUMERO":      2,
            "FECHA":       datetime(2025, 3, 11),
            "ORIENTADOR":  "Orientadora1",
            "NOMBRE":      "Carlos Vega",
            "TD":          "PPT",
            "GENERO":      "M",
            "EDAD":        25,
            "RANGO":       "18-28",
            "TELEFONO":    "3007654321",
            "BARRIO":      "barrio_w",
            "NIVEL DE FORMACIÓN": "Bachiller",
            "FORMACIÓN":   None,
            "EXPERIENCIA LABORAL": None,
            "POBLACIÓN":   "migrante venezolano",
            "CORREO ELECTRONICO": "d@test.com",
            "TALLER FIS":  None,
            "OBSERVACIONES": None,
            "INTÉRES CURSO FORMACIÓN": "no",
            "VALIDACIÓN DE BACHILLERATO (SI / NO)": "si",
            "A TENER EN CUENTA": None,
        },
    ])
    _p["NUMERO.1"] = _p["NUMERO.1"].astype(str)
    return _p


# ---------------------------------------------------------------------------
# Public writer
# ---------------------------------------------------------------------------

def write_fixture_excel_orientacion(
    sise_path: str,
    registries_path: str,
    psicologist_path: str,
) -> None:
    """
    Write three fixture Excel files that orientacion_hv.run_pipeline()
    can consume directly.

    Args:
        sise_path:        Path for the SISE file
                          (sheets: BD_Indicador_1, Reporte_Indicador_2).
        registries_path:  Path for the registries file
                          (sheet: BD_Acumulado-2024-2026).
        psicologist_path: Path for the psicologist file
                          (sheet: Orientados).
    """
    # SISE file — two sheets
    with pd.ExcelWriter(sise_path, engine="openpyxl") as writer:
        _orientados_rows().to_excel(writer, sheet_name="BD_Indicador_1",      index=False)
        _talleres_rows().to_excel(writer,   sheet_name="Reporte_Indicador_2", index=False)

    # Registries file
    with pd.ExcelWriter(registries_path, engine="openpyxl") as writer:
        _registrados_rows().to_excel(writer, sheet_name="BD_Acumulado-2024-2026", index=False)

    # Psicologist file
    with pd.ExcelWriter(psicologist_path, engine="openpyxl") as writer:
        _psicologas_rows().to_excel(writer, sheet_name="Orientados", index=False)