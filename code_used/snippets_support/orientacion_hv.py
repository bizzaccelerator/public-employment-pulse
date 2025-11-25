import pandas as pd
import numpy as np
import os

# inputs 
# The new registries for this months are
prev_month = int(os.getenv('MONTH'))
prev_year = int(os.getenv('YEAR'))

# reading the raw data
orientados = pd.read_excel('sise_psico', sheet_name='BD_Indicador_1')
registrados = pd.read_excel('registries',sheet_name='BD_Acumulado-2024-2025')
psicologas = pd.read_excel('psicologist', sheet_name='Orientados')
talleres = pd.read_excel('sise_psico', sheet_name='Reporte_Indicador_2')


# Cleaning and preprocessing
orientados.columns = orientados.columns.str.lower()
talleres.columns = talleres.columns.str.lower()

for column in ['fechaagendamiento', 'fechaejecucion', 'fechaevaluacion']:
    orientados[column] = pd.to_datetime(orientados[column])
    talleres[column] = pd.to_datetime(talleres[column])

for name in orientados.columns:
    orientados[name] = orientados[name].apply(lambda x: x.lower() if isinstance(x, str) else x)
    talleres[name] = talleres[name].apply(lambda x: x.lower() if isinstance(x, str) else x)

orientados = orientados.rename(columns={
    'fechaagendamiento':'fechaagendamiento_orientacion',
    'fechaejecucion':'fechaejecucion_orientacion',
    'fechaevaluacion':'fechaevaluacion_orientacion',
    'usuarionombre':'orientador',
})
talleres = talleres.rename(columns={
    'fechaagendamiento':'fechaagendamiento_taller',
    'fechaejecucion':'fechaejecucion_taller',
    'fechaevaluacion':'fechaevaluacion_taller',
    'usuarionombre':'tallerista',
})

# Preprocessing date columns to extract month and year
orientados['mes_orientado'] = orientados['fechaejecucion_orientacion'].dt.month
orientados['mes_orientado'] = pd.to_numeric(orientados['mes_orientado'], errors='coerce').round().astype('Int64')

orientados['año_orientado'] = orientados['fechaejecucion_orientacion'].dt.year
orientados['año_orientado'] = pd.to_numeric(orientados['año_orientado'], errors='coerce').round().astype('Int64')

talleres['mes_taller'] = talleres['fechaejecucion_taller'].dt.month
talleres['mes_taller'] = pd.to_numeric(talleres['mes_taller'], errors='coerce').round().astype('Int64')

talleres['año_taller'] = talleres['fechaejecucion_taller'].dt.year
talleres['año_taller'] = pd.to_numeric(talleres['año_taller'], errors='coerce').round().astype('Int64')


# Remaning columns to lowercase
registrados.columns = registrados.columns.str.replace('Número Documento','numerodocumento')
psicologas.columns = psicologas.columns.str.replace('NUMERO.1','numerodocumento')
psicologas = psicologas.drop('Unnamed: 22', axis=1)

for name in psicologas.columns:
    psicologas[name] = psicologas[name].apply(lambda x: x.lower() if isinstance(x, str) else x)

talleres = talleres.groupby('numerodocumento').agg({
    'indicador': 'first',
    'tipodireccionamiento': 'first', 
    'tipodocumento': 'first', 
    'correoelectronico': 'first', 
    'primernombre': 'first', 
    'segundonombre': 'first', 
    'primerapellido': 'first',
    'segundoapellido': 'first', 
    'sexo': 'first', 
    'ciudad': 'first', 
    'departamento': 'first', 
    'area': 'first', 
    'tipo': 'first',
    'subtipo': 'first', 
    'nombreportafolio': 'first', 
    'nombreconvocatoria': 'first',
    'fechaagendamiento_taller': 'first', 
    'fechaejecucion_taller': 'first',
    'fechaevaluacion_taller': 'first', 
    'aprobacion': 'first', 
    'porcentajeasistencia': 'first',
    'prestadornombre': 'first', 
    'institucionnombre': 'first',
    'instituciondireccion': 'first',
    'institucionmunicipio': 'first', 
    'instituciondepartamento': 'first',
    'programagobiernosino': 'first', 
    'programagobierno': lambda x: ','.join(map(str, x.dropna().unique())), 
    'alianzasentidadesexternas': 'first',
    'tallerista': 'first', 
    'agencianombre': 'first', 
    'numerotelefono': 'first',
    'mes_taller': 'first',
    'año_taller': 'first'
}).reset_index()

# Adding the talleres data to orientados
orientados = orientados.merge(talleres, on='numerodocumento',how='outer')

columns_to_merge = ['indicador', 'tipodireccionamiento', 'tipodocumento',
       'correoelectronico', 'primernombre','segundonombre', 'primerapellido', 
       'segundoapellido', 'sexo','ciudad', 'departamento', 'area', 'tipo', 'subtipo',
       'nombreportafolio', 'nombreconvocatoria', 'aprobacion',
       'porcentajeasistencia', 'prestadornombre', 'institucionnombre',
       'instituciondireccion', 'institucionmunicipio',
       'instituciondepartamento', 'programagobiernosino',
       'programagobierno', 'alianzasentidadesexternas', 
       'agencianombre', 'numerotelefono']

for col in columns_to_merge:
    orientados[col] = orientados[f'{col}_x'].combine_first(orientados[f'{col}_y'])
    orientados.drop(columns=[f'{col}_x', f'{col}_y'], inplace=True)

registrados = registrados.groupby('numerodocumento').agg({
    'No. ': 'first',
    'Programa / Aliado\n(Si aplica)': 'first',
    'Barrio donde vive': 'first',
    'Tipo Documento': 'first',
    'TIPO_REGISTRO':'first',
    'Nombres': 'first',
    'Apellidos': 'first',
    'Celular': 'first',
    'Teléfono': 'first',
    'Canal de Registro': 'first',
    'Edad':'first',
    'Rango_Edad': 'first',
    'Género': 'first',
    'Nivel de Estudio': 'first',
    'Título Homologado':'first',
    'Ciudad de Residencia':'first', 
    'Email':'first',
    'Fecha Registro' :'first',
    'Programa de Gobierno': lambda x: ','.join(map(str, x.dropna().unique())),
    'Condiciones Especiales': lambda x: ','.join(map(str, x.dropna().unique())),
    'Detalle Discapacidades':'first', 
    'Situación Laboral':'first', 
    'Agente Registra':'first',
    'Fecha Actualización':'first',
    '% Hoja Vida':'first',
    'Prestador Anterior':'first',
    'Fecha Cambio Prestador':'first', 
    'Vereda/Localidad/Centro Poblado':'first',
    'Pertenece A':'first', 
    'SISE_OFFLINE':'first', 
    'Mes':'first',
    'Año':'first', 
    'Punto Atención':'first',
}).reset_index()

psicologas = psicologas.groupby('numerodocumento').agg({
    'MES': 'first', 
    'NUMERO': 'first', 
    'FECHA': 'first', 
    'ORIENTADOR': 'first', 
    'NOMBRE': 'first', 
    'TD': 'first',
    'GENERO': 'first', 
    'EDAD': 'first', 
    'RANGO': 'first', 
    'TELEFONO': 'first', 
    'BARRIO': 'first',
    'NIVEL DE FORMACIÓN': 'first', 
    'FORMACIÓN': 'first', 
    'EXPERIENCIA LABORAL': 'first',
    'POBLACIÓN': lambda x: ','.join(map(str, x.dropna().unique())),
    'CORREO ELECTRONICO': 'first', 
    'TALLER FIS': lambda x: ','.join(map(str, x.dropna().unique())),
    'OBSERVACIONES': 'first',
    'INTÉRES CURSO FORMACIÓN': 'first', 
    'VALIDACIÓN DE BACHILLERATO (SI / NO)': 'first',
    'A TENER EN CUENTA': 'first'
}).reset_index()

# Merging data from registrados and psicologas into orientados
orientados = orientados.merge(registrados[['numerodocumento', 'Programa de Gobierno','Condiciones Especiales']], on='numerodocumento', how='left')

orientados = orientados.merge(psicologas[['numerodocumento','EDAD','POBLACIÓN']], on='numerodocumento', how='left')

orientados['Condiciones Especiales'] = orientados.apply(
    lambda row: f"{row['Condiciones Especiales']}, {row['POBLACIÓN']}" if pd.notnull(row['POBLACIÓN']) else row['Condiciones Especiales'],
    axis=1
)

orientados = orientados.drop('POBLACIÓN', axis=1)

orientados.columns = orientados.columns.str.lower()
orientados.columns = orientados.columns.str.replace(' ','_')

orientados['edad'] = pd.to_numeric(orientados['edad'], errors='coerce').round().astype('Int64')

# Cleaning column 'edad': 
def range_age(age):
    if  0 < age < 18:
        return '< 18'
    elif 18 <= age < 29:
        return '18-28'
    elif 29 <= age < 40:
        return '29-39'
    elif 40 <= age < 50:
        return '40-49'
    elif 50 <= age < 60:
        return '50-59'
    elif 60 <= age < 2000:
        return '> 60'
    else:
        return np.nan

orientados['rango_de_edad'] = orientados['edad'].apply(range_age)


# # GRUPOS ETNICOS
# Ensure conditions are strings and lowercase
orientados['condiciones_especiales'] = orientados['condiciones_especiales'].astype(str).str.lower().fillna('')

# Define filters
filter_afro = orientados['condiciones_especiales'].str.contains('negr|afro|mulat|palen', regex=True)
filter_raizal = orientados['condiciones_especiales'].str.contains('raiz', regex=True)
filter_indig = orientados['condiciones_especiales'].str.contains('indí', regex=True)
filter_git = orientados['condiciones_especiales'].str.contains('git', regex=True)

def get_ethnic_groups(row):
    groups = []
    if filter_afro[row.name]: groups.append("Afrodescendiente")
    if filter_raizal[row.name]: groups.append("Raizal y/o Isleño")
    if filter_indig[row.name]: groups.append("Indígenas")
    if filter_git[row.name]: groups.append("Gitano")
    return groups if groups else np.nan  # Use NaN for empty lists

# Apply the function
orientados["grupos_etnicos"] = orientados.apply(get_ethnic_groups, axis=1)

# # VICTIMAS DEL CONFLICTO ARMADO
# Poblacion VCA 
orientados['programa_de_gobierno'].astype(str)
orientados['programa_de_gobierno'] = orientados['programa_de_gobierno'].fillna('')

orientados['vca'] = pd.Series(dtype='object') # Adding a new column

filter_vca = (
    (orientados['programa_de_gobierno'].str.contains('armado', na=False)) |
    (orientados['condiciones_especiales'].str.contains('vca|v.c.a'))
)

orientados.loc[filter_vca,'vca'] = 'VCA'


# # PERSONAS EN CONDICION DE DISCAPACIDAD

# Initialize the column with NaN directly
orientados['discapacidad'] = pd.Series([np.nan] * len(orientados), dtype='object')

# Mapping of patterns to labels
discapacidad_patterns = {
    r'capacidad': 'Discapacidad',
    r'ognitiv|telect': 'Cognitiva o Intelectual',
    r'[ií]sic': 'Física',
    r'visual': 'Visual',
    r'auditiva': 'Auditiva',
    r'múltiple': 'Múltiple',
    r'sordoceguera': 'Sordoceguera',
    r'psicosocial': 'Psicosocial'
}

# Apply the patterns
for pattern, label in discapacidad_patterns.items():
    mask = orientados['condiciones_especiales'].str.contains(pattern, case=False, na=False)
    orientados.loc[mask, 'discapacidad'] = label


# # MIGRANTES

# Migrant and internally displaced people
orientados['migrante'] = ""

# Filters applied
filter_mig = (
    (orientados['condiciones_especiales'].str.contains('migr|retor')) |
    (orientados['tipodocumento'].str.contains('dni|ppt|ce'))
)

orientados.loc[filter_mig,"migrante"] = "Migrante o Retornado"

# Replace empty strings with NaN
orientados['migrante'] = orientados['migrante'].replace("", np.nan)


# # VÍCTIMA DE VIOLENCIA 
# Population VVG
orientados['vvg'] = ""

# Filters applied
filter_vvg = (
    (orientados['condiciones_especiales'].str.contains('viole')) |
    (orientados['condiciones_especiales'].str.contains('vvg'))     
)

orientados.loc[filter_vvg,"vvg"] = "vvg"

# Replace empty strings with NaN
orientados['vvg'] = orientados['vvg'].replace("",  np.nan)

# # REINSERTADOS
# Reincorporados
orientados['reincorporados'] = ""

# Filters applied
filter_rei = (
    (orientados['condiciones_especiales'].str.contains('rein'))
)

orientados.loc[filter_rei,"reincorporados"] = "reincorporados"

# Replace empty strings with NaN
orientados['reincorporados'] = orientados['reincorporados'].replace("", np.nan)

# # Final cleaning
for col in orientados.columns:
    if orientados[col].dtype == 'object':
        orientados[col] = orientados[col].astype(str)
        orientados[col] = [str(i).lower() for i in orientados[col]]
        orientados[col] = [str(i).strip() for i in orientados[col]]

orientados = orientados.replace('nan',pd.NA)


# # Reportes de población
# Personas orientadas
f_orientado = (orientados['mes_orientado'] == prev_month) & (orientados['año_orientado'] == prev_year)
oriented = orientados[f_orientado]

print(f"El número de hombres orientados durante el mes {prev_month} es: {orientados[f_orientado & (orientados['sexo']=='m')]['sexo'].count()}")
print(f"El número de mujeres orientadas durante el mes {prev_month} es: {orientados[f_orientado & (orientados['sexo']=='f')]['sexo'].count()}")
print()

print(f"El número de PCD orientadas durante el mes {prev_month} es: {orientados[f_orientado]['discapacidad'].count()}")
print(f"El número de victimas orientadas durante el mes {prev_month} es: {orientados[f_orientado]['vca'].count()}")
print(f"El número de victimas de violencia de género orientadas durante el mes {prev_month} es: {orientados[f_orientado]['vvg'].count()}")
print(f"El número de migrantes orientadas durante el mes {prev_month} es: {orientados[f_orientado]['migrante'].count()}")
print(f"El número de personas de grupos étnicos orientadas durante el mes {prev_month} es: {orientados[f_orientado]['grupos_etnicos'].count()}")
print(f"El número de reincorporados orientados durante el mes {prev_month} es: {orientados[f_orientado]['reincorporados'].count()}")
print()

print(f"El número de adultos mayores orientados durante el mes {prev_month} es: {orientados[f_orientado & (orientados['edad'] >= 60)]['sexo'].count()}")
print(f"El número de adultos orientados durante el mes {prev_month} es: {orientados[f_orientado & (orientados['edad'] >= 29) & (orientados['edad'] < 60)]['sexo'].count()}")
print(f"El número de jovenes orientados durante el mes {prev_month} es: {orientados[f_orientado & (orientados['edad'] <= 28)]['sexo'].count()}")


# Personas taller FIS
f_taller = (orientados['mes_taller'] == prev_month) & (orientados['año_taller'] == prev_year)
workshops = orientados[f_taller]

print(f"El número de hombres on taller FIS durante el mes {prev_month} es: {orientados[f_taller & (orientados['sexo']=='m')]['sexo'].count()}")
print(f"El número de mujeres on taller FIS durante el mes {prev_month} es: {orientados[f_taller & (orientados['sexo']=='f')]['sexo'].count()}")
print()

print(f"El número de PCD con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['discapacidad'].count()}")
print(f"El número de victimas con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['vca'].count()}")
print(f"El número de victimas de violencia de género con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['vvg'].count()}")
print(f"El número de migrantes con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['migrante'].count()}")
print(f"El número de personas de grupos étnicos con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['grupos_etnicos'].count()}")
print(f"El número de reincorporados con taller FIS durante el mes {prev_month} es: {orientados[f_taller]['reincorporados'].count()}")
print()

print(f"El número de adultos mayores con taller FIS durante el mes {prev_month} es: {orientados[f_taller & (orientados['edad'] >= 60)]['sexo'].count()}")
print(f"El número de adultos con taller FIS durante el mes {prev_month} es: {orientados[f_taller & (orientados['edad'] >= 29) & (orientados['edad'] < 60)]['sexo'].count()}")
print(f"El número de jovenes con taller FIS durante el mes {prev_month} es: {orientados[f_taller & (orientados['edad'] <= 28)]['sexo'].count()}")

# Exporting the data
f_export = (orientados['mes_orientado'] == prev_month) | (orientados['mes_taller'] == prev_month) & (orientados['año_taller'] == prev_year)
oriented_workshops = orientados[f_export]
oriented_workshops.to_parquet(f'orientados_{prev_year}_{prev_month}.parquet', compression='zstd')

# Counting the number of valid records processed
num_oriented_records = oriented.shape[0]
print(f"Number of people attended by psicologist during {prev_month}/{prev_year}: {num_oriented_records}")
# Output the count
with open('psico_count.txt', 'w') as f:
    f.write(str(num_oriented_records))

num_workshops_records = workshops.shape[0]
print(f"Number of people who attended workshops during {prev_month}/{prev_year}: {num_workshops_records}")
with open('workshop_count.txt', 'w') as f:
    f.write(str(num_workshops_records))