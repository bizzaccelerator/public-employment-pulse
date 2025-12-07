import pandas as pd
import numpy as np
import os

# INPUTS
prev_month = int(os.getenv('MONTH'))
prev_year = int(os.getenv('YEAR'))

jobs = pd.read_excel('job_posting', sheet_name="Vacantes")

# Typing column the names 
jobs.columns = jobs.columns.str.lower()
jobs.columns = jobs.columns.str.replace(" ","_")

jobs = jobs.drop('empre_reg', axis=1)

# Cleaning NaN data. Data as 'nan' are not actual "NaN":
for column in jobs.columns:
    jobs[column] = jobs[column].replace('nan', pd.NA)
    jobs[column] = jobs[column].replace('', pd.NA)

for col in jobs.columns:
    if jobs[col].dtype == 'object':
        jobs[col] = jobs[col].astype(str)
        jobs[column] = [str(i).lower() for i in jobs[column]]
        jobs[column] = [str(i).strip() for i in jobs[column]]

jobs['fecha_registro'] = jobs['fecha_registro'].fillna("")

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
jobs['fecha_registro'] = jobs['fecha_registro'].apply(parse_dates)

# Floor the date to remove time (ensures it's still a datetime object)
jobs['fecha_registro'] = jobs['fecha_registro'].dt.floor('D')

# Extracting the relevant data to work with
jobs = jobs[['código_proceso', 'nombre_vacante', 'cargo', '#_postulados', 'empresa',
       'tipodocumentoempresa', 'numerodocumentoempresa', 'fecha_registro',
       'fecha_vencimiento', 'estado_actual', 'tipo_de_vacante',
       'puestos_de_trabajo', 'tipo_de_contrato', 'agente_aprobó',
       'mes', 'año', 'punto_atención', 'país']]

# The new companies for this months are
filter = (jobs['mes'] == prev_month) & (jobs['año'] == prev_year)

jobs = jobs[filter]

jobs['empresa'].count()

# Exporting the data
# jobs.to_parquet(f'jobs_2024', compression='zstd')
jobs.to_parquet(f'vacantes_{prev_year}_{prev_month}.parquet', compression='zstd')

# Counting the number of valid records processed
num_valid_records = jobs.shape[0]
print(f"Number of valid records processed for {prev_month}/{prev_year}: {num_valid_records}")
# Output the count
with open('record_count.txt', 'w') as f:
    f.write(str(num_valid_records))

