import pandas as pd
import numpy as np
import os

# inputs 
# The new registries for this months are
prev_month = int(os.getenv('MONTH'))
prev_year = int(os.getenv('YEAR'))

df = pd.read_excel('intermediacion',sheet_name="BASE GENERAL")

# Drop columns that are completely empty or have names like 'Unnamed'
df = df.loc[:, ~df.columns.str.contains('^Unnamed', case=False, na=False)]

# # Also drop columns where all values are NaN
# df = df.dropna(axis=1, how='all')

# Drop rows where all values are NaN
df = df.dropna(axis=0, how='all')

print(f"After cleanup shape: {df.shape}")
print(f"After cleanup columns count: {len(df.columns)}")

# Typing column the names 
df.columns = df.columns.str.lower()
df.columns = df.columns.str.replace(" ","_")


# ## 0. Selecting the useful rows
# Cleaning NaN data. Data as 'nan' are not actual "NaN":
for column in df.columns:
    df[column] = df[column].replace('nan', pd.NA)

df['fecha_envío_hojas_de_vida_a_la_empresa'] = pd.to_datetime(df['fecha_envío_hojas_de_vida_a_la_empresa'],errors='coerce')
df['fecha_de_publicacion_de_la_vacante'] = pd.to_datetime(df['fecha_de_publicacion_de_la_vacante'],errors='coerce')

# Selecting the useful rows only
filter_mt = (df['mes_registro'].isna() & df['gestión_vacante_'].isna() & 
             df['población'].isna() & df['código_proceso'].isna() )
             # & ~df['nombre_del_candidato'].str.contains('REMIT') & ~df['fecha_envío_hojas_de_vida_a_la_empresa'].isna())
df = df[~filter_mt]

# ## 1. Cleaning columns

# Cleaning columns
subset_columns = ['mes_registro', 'convenio', 'gestión_vacante_', 'población',
       'código_proceso', 'nombre_de_la_empresa', 'nombre_de_la_vacante',
       'nombre_del_candidato', 'nivel_educativo', 'formacion', 'sexo', 'barrio', 'condicion', 
       'gestor', 'intermediador_','llamada_/_convocatoria/_base_de_datos', 'observación_intermediación',
       'observación_gestión', 'observación_del_candidato', 'mes_de_colocación_en_plataforma', 'colocado',
       'semana_publicacion_vacante', 'mes_publicacion_vacante', 'tipo_de_vacante']

for column in subset_columns:
    df[column] = [str(i).lower() for i in df[column]]
    df[column] = [str(i).strip() for i in df[column]]

df = df.rename(columns={'vacantes_solicitadas/puestos_de_trabajo_en_plataforma':'puestos_de_trabajo_en_plataforma'})

# Cleaning column 'convenio': 
df['convenio'] = df['convenio'].replace(['ninguno', 'ninguna'],np.nan)

# Cleaning column 'nivel_educativo': 
dictionary = {
    'técnico':'tecnico',
    'tegnologo':'tecnologo',
    'tecnologa':'tecnologo',
    'universitaria':'universitario',
    'pfofesional':'universitario',
    'profesional':'universitario',
    'primaria':'basica primaria',
    'bachiller':'educación media',
}
df['nivel_educativo'] = df['nivel_educativo'].replace(dictionary)

# Cleaning column 'edad': 
df['edad'] = df['edad'].fillna(0)
df['edad'] = (pd.to_numeric(df['edad'], errors='coerce').round(0).astype('Int64'))

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

df['rango_de_edad'] = df['edad'].apply(range_age)

# Cleaning column 'condicion': 
df['condicion'] = df['condicion'].replace(['ninguna','ninguno','nimguno'],np.nan)

# Cleaning column 'semana_publicacion_vacante': 
df['semana_publicacion_vacante'] = df['fecha_de_publicacion_de_la_vacante'].dt.isocalendar().week

# Cleaning column 'mes_publicacion_vacante': 
df['mes_publicacion_vacante'] = df['fecha_de_publicacion_de_la_vacante'].dt.month.fillna(0).astype(int)

# Cleaning column 'año_publicacion_vacante': 
df['año_publicacion_vacante'] = df['fecha_de_publicacion_de_la_vacante'].dt.isocalendar().year

# Evaluating unique values:
for column in df.columns:
    print(df[column].value_counts())

# Converting to integer
df['colocado'] = pd.to_numeric(df['colocado'], errors='coerce')
df['colocado'] = df['colocado'].astype(float).fillna(0).astype(int)

# Working with dates
df['mes_publicacion_vacante'] = df['fecha_de_publicacion_de_la_vacante'].dt.month
df['mes_publicacion_vacante'] = pd.to_numeric(df['mes_publicacion_vacante'], errors='coerce')
df['mes_publicacion_vacante'] = df['mes_publicacion_vacante'].fillna(0).astype(int)


# ## CALCULO DE POBLACIONES

# Initialize the column with NaN directly
df['discapacidad'] = pd.Series([np.nan] * len(df), dtype='object')

# Mapping of patterns to labels
discapacidad_patterns = {
    r'ognitiv|telect': 'Cognitiva o Intelectual',
    r'[ií]sic': 'Física',
    r'visual': 'Visual',
    r'auditiva': 'Auditiva',
    r'múltiple': 'Múltiple',
    r'sordoceguera': 'Sordoceguera',
    r'psicosocial': 'Psicosocial',
    # r'capacidad': 'Discapacidad'
}

# Apply patterns
for pattern, label in discapacidad_patterns.items():
    mask = df['condicion'].str.contains(pattern, case=False, na=False)
    df.loc[mask, 'discapacidad'] = label


# Poblacion VCA
df['vca'] = pd.Series(dtype='object') # Adding a new column

filter_vca = (
    df['condicion'].str.contains('vca|v.c.a|ctima', na=False) 
)

df.loc[filter_vca,'vca'] = 'vca'

# Replace empty strings with NaN
df['vca'] = df['vca'].replace("", np.nan)


# Población Víctima de Violencia de Género
df['vvg'] = pd.Series(dtype='object')

filter_vvg = (
    df['condicion'].str.contains('vvg|violencia|mch', na=False)
)

df.loc[filter_vvg,'vvg'] = 'vvg'

# Replace empty strings
df['vvg'] = df['vvg'].replace("", np.nan)

# Población migrante y retornada
df['migrante'] = ""

# Filters applied
filter_migrante = (
    (df['condicion'].str.contains('igran')) |
    (df['condicion'].str.contains('etorn')) 
)

df.loc[filter_migrante,'migrante'] = 'Migrante y/o retronado'

# Replace empty strings with NaN
df['migrante'] = df['migrante'].replace("", np.nan)

# Grupos etnicos
df['condicion'] = df['condicion'].fillna('')

df['etnias'] = ""

# Filters applied
filter_afro = (
    (df['condicion'].str.contains('negr')) |
    (df['condicion'].str.contains('afro')) |
    (df['condicion'].str.contains('mulat')) |
    (df['condicion'].str.contains('palen')) 
)

filter_raizal = (
    (df['condicion'].str.contains('raiz'))
)

filter_indig = (
    (df['condicion'].str.contains('indí'))
)

filter_git = (
    (df['condicion'].str.contains('git'))
)

# Column etnic groups
df.loc[(filter_afro | filter_git | filter_indig | filter_raizal),'etnias'] = "grupo_etnico"

# Replace empty strings with NaN
df['etnias'] = df['etnias'].replace("", np.nan)

# Poblacion Reincorporada
df['reincorporados'] = pd.Series(dtype=object)

filter_rei = (
    df['condicion'].str.contains('rein', na=False)
)

df.loc[filter_rei,'reincorporados'] = "reincorporados"

# Cleaning the column
df['reincorporados'] = df['reincorporados'].replace('', np.nan)

# Preparatgion for text:
for col in df.columns:
    if df[col].dtype == 'object':
        df[col] = df[col].astype(str)
        df[col] = [str(i).lower() for i in df[col]]
        df[col] = [str(i).strip() for i in df[col]]

df = df.replace('nan',pd.NA)

# ## REPORTE DE INDICADORES

# The new registries for this months are
months = {
    1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
    5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
    9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'
}

# Vacantes registradas
mes_registro = months[prev_month]
f_vacante = (df['mes_registro'] == mes_registro)

print(f"El número de empresas que solicitaron vacantes durante el mes {mes_registro} es: {len(df[f_vacante]['nombre_de_la_empresa'].unique())}")
print(f"El número de vacantes atendidas durante el mes {mes_registro} es: {len(df[f_vacante]['código_proceso'].unique())}")
# print(f'El número de puestos de trabajo atendidos durante el mes {mes_registro} es: {df[f_vacante]['vacantes_solicitadas/puestos_de_trabajo_en_plataforma'].sum()}')
print(f"El número de puestos de trabajo atendidos durante el mes {mes_registro} es: {df[f_vacante]['puestos_de_trabajo_en_plataforma'].sum()}")

# Hojas de vida remitidas
mes = float(prev_month)
f_remitidos = (df['fecha_envío_hojas_de_vida_a_la_empresa'].dt.month == mes)

print(f"El número de hombres con HV remitidas durante el mes {mes} es: {df[f_remitidos & (df['sexo']=='m')]['sexo'].count()}")
print(f"El número de mujeres con HV remitidas durante el mes {mes} es: {df[f_remitidos & (df['sexo']=='f')]['sexo'].count()}")
print()

print(f"El número de HV remitidas para PCD durante el mes {mes} es: {df[f_remitidos]['discapacidad'].count()}")
print(f"El número de HV remitidas para victimas durante el mes {mes} es: {df[f_remitidos]['vca'].count()}")
print(f"El número de HV remitidas para victimas de violencia de género durante el mes {mes} es: {df[f_remitidos]['vvg'].count()}")
print(f"El número de HV remitidas para migrantes durante el mes {mes} es: {df[f_remitidos]['migrante'].count()}")
print(f"El número de HV remitidas para grupos étnicos durante el mes {mes} es: {df[f_remitidos]['etnias'].count()}")
print(f"El número de HV remitidas para reincorporados durante el mes {mes} es: {df[f_remitidos]['reincorporados'].count()}")
print()

print(f"El número de HV remitidas para adultos mayores durante el mes {mes} es: {df[f_remitidos & (df['edad'] >= 60)]['sexo'].count()}")
print(f"El número de HV remitidas para adultos durante el mes {mes} es: {df[f_remitidos & (df['edad'] >= 29) & (df['edad'] < 60)]['sexo'].count()}")
print(f"El número de HV remitidas para jovenes durante el mes {mes} es: {df[f_remitidos & (df['edad'] <= 28)]['sexo'].count()}")

# Colocados por mes
mes_colocado = months[prev_month]
f_colocados = (df['colocado'] == 1)&(df['mes_de_colocación_en_plataforma'] == mes_colocado)

print(f"El número de hombres colocados durante el mes {mes_colocado} es: {df[f_colocados & (df['sexo']=='m')]['sexo'].count()}")
print(f"El número de mujeres colocados durante el mes {mes_colocado} es: {df[f_colocados & (df['sexo']=='f')]['sexo'].count()}")
print()

print(f"El número de colocados para PCD durante el mes {mes_colocado} es: {df[f_colocados]['discapacidad'].count()}")
print(f"El número de colocados para victimas durante el mes {mes_colocado} es: {df[f_colocados]['vca'].count()}")
print(f"El número de colocados para para victimas de violencia de género durante el mes {mes} es: {df[f_colocados]['vvg'].count()}")
print(f"El número de colocados para migrantes durante el mes {mes_colocado} es: {df[f_colocados]['migrante'].count()}")
print(f"El número de colocados para grupos étnicos durante el mes {mes_colocado} es: {df[f_colocados]['etnias'].count()}")
print(f"El número de colocados para reincorporados durante el mes {mes_colocado} es: {df[f_remitidos]['reincorporados'].count()}")
print()

print(f"El número de colocados para adultos mayores durante el mes {mes_colocado} es: {df[f_colocados & (df['edad'] >= 60)]['sexo'].count()}")
print(f"El número de colocados para adultos durante el mes {mes_colocado} es: {df[f_colocados & (df['edad'] >= 29) & (df['edad'] < 60)]['sexo'].count()}")
print(f"El número de colocados para jovenes durante el mes {mes_colocado} es: {df[f_colocados & (df['edad'] <= 28)]['sexo'].count()}")

# El número de empresas que contrataron población fueron:
f_poblaciones = ~(df['etnias'].isna() & df['migrante'].isna() & df['vca'].isna() & df['discapacidad'].isna())
print(f"El número de empresas que contrataron poblaciones PCD, VCA, migrantes y Etnias durante el mes {mes_registro} es: {len(df[f_poblaciones & f_colocados]['nombre_de_la_empresa'].unique())}")
print()
print(f"El nombre de las empresas que contrataron poblaciones PCD, VCA, migrantes y Etnias durante el mes {mes_registro} son: ")
print(df[f_poblaciones & f_colocados]['nombre_de_la_empresa'].unique())


# ## EXPORTAR DOCUMENTO
f_export = (df['mes_registro'] == months[prev_month]) | (df['fecha_envío_hojas_de_vida_a_la_empresa'].dt.month == float(prev_month)) | (df['mes_de_colocación_en_plataforma'] == months[prev_month])
intermediation = df[f_export]
# Exporting the data
intermediation.to_parquet(f'intermediacion_{prev_year}_{prev_month}.parquet', compression='zstd')

# Counting the number of valid records processed
num_intermediation_records = intermediation.shape[0]
print(f"Number of people sent to interviews during {prev_month}/{prev_year}: {num_intermediation_records}")
# Output the count
with open('registries_count.txt', 'w') as f:
    f.write(str(num_intermediation_records))