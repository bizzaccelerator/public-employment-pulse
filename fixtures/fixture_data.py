"""
fixtures/fixture_data.py
========================
Builds the minimal fixture Excel file used by integration tests.

ROW INVENTORY
─────────────
 #  Scenario
 0  Jan 2025 — new agency registration, female, Afrodescendiente
 1  Jan 2025 — new agency registration, male, disability (física)
 2  Jan 2025 — autoregistro, female, VCA (via programa_de_gobierno)
 3  Jan 2025 — updated agency registration, male, migrant (via tipo_documento)
 4  Feb 2025 — new agency registration, female, VVG
 5  Feb 2025 — new agency registration, male, reincorporado
 6  Jan 2024 — valid but different year (must be excluded from 2025 runs)
 7  INVALID   — null tipo_documento (must never reach the database)
 8  INVALID   — null número_documento (must never reach the database)
 9  Jan 2025 — DUPLICATE of row 0 (same unique_row_id fields)

DESIGN NOTES
────────────
- Número_documento is stored as integers (not strings) so openpyxl does
  not coerce to float64 when there is a None in the column.
  clean_string_columns() handles the Int64→str conversion cleanly.
- Barrio_donde_vive and Programa_/_aliado\n(si_aplica) are included
  because they exist in the real Excel and are required by COLUMN_MAPPING.
"""

import io
import pandas as pd


SHEET_NAME = "BD_Acumulado-2024-2026"


def build_fixture_df() -> pd.DataFrame:
    """
    Return the fixture DataFrame with production-realistic column names
    matching what the real Excel file looks like before load_excel() normalises them.
    """
    return pd.DataFrame({
        "No._": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        # Previously missing — caused validate_columns() to report
        # ['barrio_donde_vive', 'programa_aliado'] missing after mapping.
        "Programa_/_aliado\n(si_aplica)": [""] * 10,
        "Barrio_donde_vive": ["El Centro"] * 10,
        "Tipo_documento": [
            "CC", "CC", "CC", "Permiso especial",
            "CC", "CC",
            "CC",           # year 2024
            None,           # INVALID — no tipo_documento
            "CC",           # INVALID — no número_documento
            "CC",           # DUPLICATE of row 0
        ],
        # Stored as integers so openpyxl does not force float64 dtype.
        # The None in row 8 is what previously caused the entire column to be
        # read as float64, making 111111 → 111111.0 → "111111.0" after astype(str).
        "Número_documento": [
            111111, 222222, 333333, 444444,
            555555, 666666,
            777777,
            888888,
            None,
            111111,         # same as row 0
        ],
        "Tipo_registro": [
            "Registro_nuevo", "Registro_nuevo", "Registro_nuevo", "Actualizacion",
            "Registro_nuevo", "Registro_nuevo",
            "Registro_nuevo",
            "Registro_nuevo",
            "Registro_nuevo",
            "Registro_nuevo",
        ],
        "Nombres": [
            "Ana", "Luis", "María", "Jorge",
            "Carmen", "Pedro",
            "Rosa",
            "Ghost", "Empty",
            "Ana",          # duplicate
        ],
        "Apellidos": [
            "García", "Martínez", "López", "Rodríguez",
            "Hernández", "Sánchez",
            "Castro",
            "X", "Y",
            "García",       # duplicate
        ],
        "Celular": [
            "3001111111", "3002222222", "3003333333", "3004444444",
            "3005555555", "3006666666",
            "3007777777",
            "3008888888", "3009999999",
            "3001111111",   # duplicate
        ],
        "Teléfono": ["111", "222", "333", "444", "555", "666", "777", "888", "999", "111"],
        "Canal_de_registro": [
            "Agencia", "Agencia", "Autoregistro", "Agencia",
            "Agencia", "Agencia",
            "Agencia",
            "Agencia", "Agencia",
            "Agencia",
        ],
        "Edad":       [25, 45, 32, 55, 28, 40, 60, 22, 33, 25],
        "Rango_edad": ["18-28", "29-59", "29-59", "29-59", "18-28", "29-59", "60+", "18-28", "29-59", "18-28"],
        "Género":     ["F", "M", "F", "M", "F", "M", "F", "M", "F", "F"],
        "Nivel_de_estudio": ["Técnico"] * 10,
        "Título_homologado": ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T1"],
        "Ciudad_de_residencia": ["Neiva"] * 10,
        "Email": [
            "ana@test.com", "luis@test.com", "maria@test.com", "jorge@test.com",
            "carmen@test.com", "pedro@test.com",
            "rosa@test.com",
            "ghost@test.com", "empty@test.com",
            "ana@test.com", # duplicate
        ],
        "Fecha_registro": [
            "15/01/2025", "20/01/2025", "10/01/2025", "05/01/2025",
            "14/02/2025", "20/02/2025",
            "15/01/2024",
            "01/01/2025", "02/01/2025",
            "15/01/2025",   # duplicate — same date as row 0
        ],
        "Programa_de_gobierno": [
            "", "", "Conflicto armado", "",
            "", "", "", "", "", "",
        ],
        "Condiciones_especiales": [
            "afrodescendiente",
            "discapacidad física",
            "",
            "",
            "violencia vvg",
            "proceso de reincorporación",
            "",
            "", "",
            "afrodescendiente", # duplicate
        ],
        "Detalle_discapacidades": ["", "Física", "", "", "", "", "", "", "", ""],
        "Situación_laboral":      ["Desempleado"] * 10,
        "Agente_registra":        ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A1"],
        "Fecha_actualización":    ["", "", "", "06/01/2025", "", "", "", "", "", ""],
        "%_hoja_vida":            ["80%", "60%", "90%", "70%", "50%", "85%", "75%", "40%", "55%", "80%"],
        "Prestador_anterior":     [""] * 10,
        "Fecha_cambio_prestador": [""] * 10,
        "Vereda/localidad/centro_poblado": ["Centro"] * 10,
        "Pertenece_a":    [""] * 10,
        "Sise_offline":   ["No"] * 10,
        "Mes":            [1, 1, 1, 1, 2, 2, 1, 1, 1, 1],
        "Año":            [2025, 2025, 2025, 2025, 2025, 2025, 2024, 2025, 2025, 2025],
        "Punto_atención": ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P1"],
    })


def write_fixture_excel(path: str) -> None:
    """Write the fixture DataFrame to an Excel file at the given path."""
    df = build_fixture_df()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)


def fixture_excel_bytes() -> bytes:
    """Return the fixture as raw Excel bytes (for in-memory use)."""
    buf = io.BytesIO()
    df = build_fixture_df()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=SHEET_NAME, index=False)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "fixture.xlsx"
    write_fixture_excel(path)
    print(f"Fixture written to: {path}")