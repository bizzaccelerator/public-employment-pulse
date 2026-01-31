import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# inputs 
# The new registries for this months are
prev_month = int(os.getenv('MONTH'))
prev_year = int(os.getenv('YEAR'))

# data handling
registro = pd.read_excel('excel_file',sheet_name='BD_Acumulado-2024-2025')

registro.columns = registro.columns.str.lower()
registro.columns = registro.columns.str.replace(" ","_")

# Drop columns that are completely empty or have names like 'Unnamed'
registro = registro.loc[:, ~registro.columns.str.contains('^Unnamed', case=False, na=False)]

# # Also drop columns where all values are NaN
# df = df.dropna(axis=1, how='all')

# Drop rows where all values are NaN
registro = registro.dropna(axis=0, how='all')

# cleaning the columns
registro['número_documento'] = registro['número_documento'].astype(str).str.strip()
registro['teléfono'] = registro['teléfono'].astype(str).str.strip()
registro['título_homologado'] = registro['título_homologado'].astype(str).str.strip()
registro['ciudad_de_residencia'] = registro['ciudad_de_residencia'].astype(str).str.strip()
registro['email'] = registro['email'].astype(str).str.strip()
registro['programa_de_gobierno'] = registro['programa_de_gobierno'].astype(str).str.strip()
registro['fecha_actualización'] = registro['fecha_actualización'].astype(str).str.strip()
registro['%_hoja_vida'] = registro['%_hoja_vida'].astype(str).str.strip()
registro['fecha_cambio_prestador'] = registro['fecha_cambio_prestador'].astype(str).str.strip()
registro['vereda/localidad/centro_poblado'] = registro['vereda/localidad/centro_poblado'].astype(str).str.strip()
registro['celular'] = registro['celular'].astype(str).str.strip()


# Registros sin tipo de documento
non_td = registro[registro['tipo_documento'].isnull()].index
# Registro sin número de documento
non_nd = registro[registro['número_documento'].isnull()].index

# All the elements without information
to_revisit = pd.Series(list(set(non_td).union(set(non_nd))))
wrong = registro[registro.index.isin(to_revisit)]

# Those need to be sent into an excel document
# current date
date = datetime.now().strftime("%Y-%m-%d")
# wrong.to_excel(f"revisar-{date}.xlsx", index=False)

# The valid results are:
valid = registro[~registro.index.isin(to_revisit)]
valid = valid[valid['año']==prev_year]


# Cleaning NaN data. Data as 'nan' are not actual "NaN":
for column in valid.columns:
    valid[column] = valid[column].replace('nan', pd.NA)

# Clean gender
valid['género'] = valid['género'].replace({'m':'M','f':'F'})

# # FECHAS DE REGISTRO
# Ensure all date columns are treated as strings for consistent parsing
date_columns = ['fecha_registro', 'fecha_actualización', 'fecha_cambio_prestador']

# Function to handle different date formats
def parse_dates(date_str):
    if pd.isna(date_str) or date_str == "" or str(date_str).strip() == "":
        return pd.NaT
    
    date_str = str(date_str).strip()
    
    # Case 1: Excel serial number (pure digits or float representation)
    # Check if it's a number (could be "45679" or "45679.0")
    try:
        excel_num = float(date_str)
        # If it's a valid Excel serial number (typically between 1 and 50000+)
        if excel_num > 0 and '/' not in date_str and '-' not in date_str:
            # Excel's base date is December 30, 1899
            # No adjustment needed for modern dates
            base_date = datetime(1899, 12, 30)
            return base_date + timedelta(days=excel_num)
    except ValueError:
        pass  # Not a number, continue to other formats
    
    # Case 2: Format with slashes and time (DD/MM/YYYY with potential time)
    if '/' in date_str:
        try:
            # Remove the periods and extra spaces from "p. m." or "a. m."
            date_str_cleaned = date_str.replace(' p. m.', ' PM').replace(' a. m.', ' AM')
            
            # Try parsing with time component first
            if 'PM' in date_str_cleaned or 'AM' in date_str_cleaned:
                return pd.to_datetime(date_str_cleaned, format="%d/%m/%Y %I:%M:%S %p")
            
            # Try without time component - explicitly parse DD/MM/YYYY
            parts = date_str.split()[0].split('/')  # Get date part only
            if len(parts) == 3:
                day, month, year = parts
                return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass
    
    # Case 3: DD-MM-YYYY format (with dashes)
    if '-' in date_str and len(date_str.split('-')) == 3:
        try:
            parts = date_str.split('-')
            # Check if it looks like DD-MM-YYYY (day would be <= 31)
            if len(parts[0]) <= 2 and int(parts[0]) <= 31:
                day, month, year = parts
                return pd.to_datetime(f"{year}-{month}-{day}", format="%Y-%m-%d")
        except (ValueError, IndexError):
            pass
    
    # Case 4: Fallback - return NaT for unparseable dates
    return pd.NaT

# Convert date columns
for col in date_columns:
    valid[col] = valid[col].fillna("").astype(str)
    valid[col] = valid[col].apply(parse_dates)

# Get the latest date
valid['fecha_accion'] = valid[['fecha_registro', 'fecha_actualización', 'fecha_cambio_prestador']].max(axis=1)

# Floor the date to remove time (ensures it's still a datetime object)
valid['fecha_accion'] = valid['fecha_accion'].dt.floor('D')

# Calculate real month of action
valid = valid.drop('mes', axis=1)
valid['mes'] = valid['fecha_accion'].dt.month

# # PREPARING FOR POPULATION ANALYSIS

valid['condiciones_especiales'].unique()


# # GRUPOS ETNICOS

# Ensure conditions are strings and lowercase
valid['condiciones_especiales'] = valid['condiciones_especiales'].astype(str).str.lower().fillna('')

# Define filters
filter_afro = valid['condiciones_especiales'].str.contains('negr|afro|mulat|palen', regex=True)
filter_raizal = valid['condiciones_especiales'].str.contains('raiz', regex=True)
filter_indig = valid['condiciones_especiales'].str.contains('indí', regex=True)
filter_git = valid['condiciones_especiales'].str.contains('git', regex=True)

def get_ethnic_groups(row):
    groups = []
    if filter_afro[row.name]: groups.append("Afrodescendiente")
    if filter_raizal[row.name]: groups.append("Raizal y/o Isleño")
    if filter_indig[row.name]: groups.append("Indígenas")
    if filter_git[row.name]: groups.append("Gitano")
    return groups if groups else np.nan  # Use NaN for empty lists

# Apply the function
valid["grupos_etnicos"] = valid.apply(get_ethnic_groups, axis=1)


# # VICTIMAS DEL CONFLICTO ARMADO

valid['programa_de_gobierno'].astype(str)
valid['programa_de_gobierno'] = valid['programa_de_gobierno'].fillna('')

valid['vca'] = pd.Series(dtype='object') # Adding a new column

filter_vca = (
    (valid['programa_de_gobierno'].str.contains('armado', na=False)) |
    (valid['condiciones_especiales'].str.contains('vca|v.c.a'))
)

valid.loc[filter_vca,'vca'] = 'VCA'


# # PERSONAS EN CONDICION DE DISCAPACIDAD

# Initialize the column with NaN directly
valid['discapacidad'] = pd.Series([np.nan] * len(valid), dtype='object')

# Mapping of patterns to labels
discapacidad_patterns = {
    r'ognitiv|telect': 'Cognitiva o Intelectual',
    r'[ií]sic': 'Física',
    r'visual': 'Visual',
    r'auditiva': 'Auditiva',
    r'múltiple': 'Múltiple',
    r'sordoceguera': 'Sordoceguera',
    r'psicosocial': 'Psicosocial',
    r'capacidad': 'Discapacidad'
}

# Apply patterns
for pattern, label in discapacidad_patterns.items():
    mask = valid['condiciones_especiales'].str.contains(pattern, case=False, na=False)
    valid.loc[mask, 'discapacidad'] = label


# # MIGRANTES

print(valid.condiciones_especiales.unique())

# Migrant and internally displaced people
valid['migrante'] = ""

# Filters applied
filter_mig = (
    (valid['condiciones_especiales'].str.contains('migr|retor')) |
    (valid['tipo_documento'].str.contains('acional|ermiso|tranje'))
)

valid.loc[filter_mig,"migrante"] = "Migrante o Retornado"

# Replace empty strings with NaN
valid['migrante'] = valid['migrante'].replace("", np.nan)

valid['tipo_documento'].value_counts()


# # VÍCTIMA DE VIOLENCIA

# Population VVG
valid['vvg'] = ""

# Filters applied
filter_vvg = (
    (valid['condiciones_especiales'].str.contains('viole')) |
    (valid['condiciones_especiales'].str.contains('vvg'))     
)

valid.loc[filter_vvg,"vvg"] = "vvg"

# Replace empty strings with NaN
valid['vvg'] = valid['vvg'].replace("",  np.nan)


# # REINSERTADOS

# Reincorporados
valid['reincorporados'] = ""

# Filters applied
filter_rei = (
    (valid['condiciones_especiales'].str.contains('rein'))
)

valid.loc[filter_rei,"reincorporados"] = "reincorporados"

# Replace empty strings with NaN
valid['reincorporados'] = valid['reincorporados'].replace("", np.nan)


print(valid['%_hoja_vida'].apply(type).unique())

# Hojas de Vida autoregistro
fr_autoregistro = (pd.to_datetime(valid['fecha_accion']).dt.month == prev_month) & (valid['canal_de_registro'] == 'Autoregistro') & (valid['tipo_registro'] == 'Registro_nuevo') & (pd.to_datetime(valid['fecha_accion']).dt.year == prev_year)

print(f"El número de HV de hombres autoregistradas durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['género']=='M')]['género'].count()}")
print(f"El número de HV de mujeres autoregistradas durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['género']=='F')]['género'].count()}")
print()

print(f"El número de HV autoregistradas para PCD durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['discapacidad'])]['discapacidad'].count()}")
print(f"El número de HV autoregistradas para VCA durante el mes {prev_month} es: {valid[fr_autoregistro]['vca'].count()}")
print(f"El número de HV autoregistradas para VVG durante el mes {prev_month} es: {valid[fr_autoregistro]['vvg'].count()}")
print(f"El número de HV autoregistradas para migrantes durante el mes {prev_month} es: {valid[fr_autoregistro]['migrante'].count()}")
print(f"El número de HV autoregistradas para grupos étnicos durante el mes {prev_month} es: {valid[fr_autoregistro]['grupos_etnicos'].count()}")
print(f"El número de HV autoregistradas para personas en reincorporacion durante el mes {prev_month} es: {valid[fr_autoregistro]['reincorporados'].count()}")
print()

print(f"El número de HV con autoregistro nuevo para adultos mayores durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['edad'] >= 60)]['género'].count()}")
print(f"El número de HV con autoregistro nuevo para adultos durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['edad'] >= 29) & (valid['edad'] < 60)]['género'].count()}")
print(f"El número de HV con autoregistro nuevo para jovenes durante el mes {prev_month} es: {valid[fr_autoregistro & (valid['edad'] <= 28)]['género'].count()}")


# Hojas de Vida de registros nuevos
fr_nuevo = (pd.to_datetime(valid['fecha_accion']).dt.month == prev_month) & (valid['canal_de_registro'] == 'Agencia') & (valid['tipo_registro'] == 'Registro_nuevo') & (pd.to_datetime(valid['fecha_accion']).dt.year == prev_year)

print(f"El número de HV de hombres con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo & (valid['género']=='M')]['género'].count()}")
print(f"El número de HV de mujeres con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo & (valid['género']=='F')]['género'].count()}")
print()

print(f"El número de HV para PCD con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo & (valid['discapacidad'])]['discapacidad'].count()}")
print(f"El número de HV para victimas con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo]['vca'].count()}")
print(f"El número de HV para Víctimas de Violencia con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo]['vvg'].count()}")
print(f"El número de HV para migrantes con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo]['migrante'].count()}")
print(f"El número de HV para grupos étnicos con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo]['grupos_etnicos'].count()}")
print(f"El número de HV para personas en reincorporacion con registro nuevo durante el mes {prev_month} es: {valid[fr_nuevo]['reincorporados'].count()}")
print()

print(f"El número de HV con registro nuevo para adultos mayores durante el mes {prev_month} es: {valid[fr_nuevo & (valid['edad'] >= 60)]['género'].count()}")
print(f"El número de HV con registro nuevo para adultos durante el mes {prev_month} es: {valid[fr_nuevo & (valid['edad'] >= 29) & (valid['edad'] < 60)]['género'].count()}")
print(f"El número de HV con registro nuevo para jovenes durante el mes {prev_month} es: {valid[fr_nuevo & (valid['edad'] <= 28)]['género'].count()}")


# Hojas de Vida actualizadas
fr_actualizado = (pd.to_datetime(valid['fecha_accion']).dt.month == prev_month) & (valid['canal_de_registro'] == 'Agencia') & (valid['tipo_registro'] == 'Actualizacion') & (pd.to_datetime(valid['fecha_accion']).dt.year == prev_year)

print(f"El número de HV de hombres actualizadas durante el mes {prev_month} es: {valid[fr_actualizado & (valid['género']=='M')]['género'].count()}")
print(f"El número de HV de mujeres actualizadas durante el mes {prev_month} es: {valid[fr_actualizado & (valid['género']=='F')]['género'].count()}")
print()

print(f"El número de HV actualizadas para PCD durante el mes {prev_month} es: {valid[fr_actualizado & (valid['discapacidad'])]['discapacidad'].count()}")
print(f"El número de HV actualizadas para VCA durante el mes {prev_month} es: {valid[fr_actualizado]['vca'].count()}")
print(f"El número de HV actualizadas para VVG durante el mes {prev_month} es: {valid[fr_actualizado]['vvg'].count()}")
print(f"El número de HV actualizadas para migrantes durante el mes {prev_month} es: {valid[fr_actualizado]['migrante'].count()}")
print(f"El número de HV actualizadas para grupos étnicos durante el mes {prev_month} es: {valid[fr_actualizado]['grupos_etnicos'].count()}")
print(f"El número de HV actualizadas para personas en reincorporacion durante el mes {prev_month} es: {valid[fr_actualizado]['reincorporados'].count()}")
print()

print(f"El número de HV actualizadas para adultos mayores durante el mes {prev_month} es: {valid[fr_actualizado & (valid['edad'] >= 60)]['género'].count()}")
print(f"El número de HV actualizadas para adultos durante el mes {prev_month} es: {valid[fr_actualizado & (valid['edad'] >= 29) & (valid['edad'] < 60)]['género'].count()}")
print(f"El número de HV actualizadas para jovenes durante el mes {prev_month} es: {valid[fr_actualizado & (valid['edad'] <= 28)]['género'].count()}")


# Exporting the data
valid = valid[(pd.to_datetime(valid['fecha_accion']).dt.month == prev_month) & (pd.to_datetime(valid['fecha_accion']).dt.year == prev_year)]
valid.to_parquet(f'registro_hv_{prev_year}_{prev_month}.parquet', compression='zstd')

# Counting the number of valid records processed
num_valid_records = valid.shape[0]
print(f"Number of valid records processed for {prev_month}/{prev_year}: {num_valid_records}")
# Output the count
with open('record_count.txt', 'w') as f:
    f.write(str(num_valid_records))
