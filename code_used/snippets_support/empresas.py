import pandas as pd 
import numpy as np
from datetime import timedelta
import os

# inputs 
# The new registries for this months are
prev_month = int(os.getenv('MONTH'))
prev_year = int(os.getenv('YEAR'))

# Reading the data
empresas = pd.read_excel('empresas', sheet_name='Sheet1')

# Typing column the names 
empresas.columns = empresas.columns.str.lower()
empresas.columns = empresas.columns.str.replace(" ","_")

# Cleaning NaN data. Data as 'nan' are not actual "NaN":
for column in empresas.columns:
    empresas[column] = empresas[column].replace('nan', pd.NA)
    empresas[column] = empresas[column].replace('', pd.NA)

for col in empresas.columns:
    if empresas[col].dtype == 'object':
        empresas[col] = empresas[col].astype(str)
        empresas[column] = [str(i).lower() for i in empresas[column]]
        empresas[column] = [str(i).strip() for i in empresas[column]]

# Modifying to datetime 

empresas['fecha_registro'] = empresas['fecha_registro'].fillna("")

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
empresas['fecha_registro'] = empresas['fecha_registro'].apply(parse_dates)

# Floor the date to remove time (ensures it's still a datetime object)
empresas['fecha_registro'] = empresas['fecha_registro'].dt.floor('D')


non_numeric = empresas[empresas['teléfono'].astype(str).str.contains(r'\D')]
print(f'The number of non numerical values in telephone column is:', non_numeric['teléfono'].count())

# Remove all non-digit characters except spaces
empresas['teléfono_clean'] = empresas['teléfono'].astype(str).str.replace(r'[^\d ]', '', regex=True)

# Remove all spaces
empresas['teléfono_clean'] = empresas['teléfono_clean'].str.replace(' ', '')

# Then extract only the first group of digits
empresas['teléfono_clean'] = empresas['teléfono_clean'].str.extract(r'^(\d+)', expand=False)

# Convert to integer
empresas['teléfono_clean'] = empresas['teléfono_clean'].astype('Int64')

# Creating the data points
empresas['mes'] = empresas['fecha_registro'].dt.month
empresas['año'] = empresas['fecha_registro'].dt.year

# The filtered monthly registries are: 
filter = (empresas['mes'] == prev_month) & (empresas['año'] == prev_year)
print(f"La cantidad de empresas registradas en durante el mes {prev_month} fueron: ", empresas[filter]['tipo_documento'].count())
print(f"Las {empresas[filter]['tipo_documento'].count()} empresas registradas fueron: ", empresas[filter]['razón_social'])
empresas = empresas[filter]

# Exporting the data
empresas.to_parquet(f"empresas_{prev_year}_{prev_month}.parquet", compression='zstd')

# Counting the number of valid records processed
num_empresas_records = empresas.shape[0]
print(f"Number of new clients registered during {prev_month}/{prev_year}: {num_empresas_records}")
# Output the count
with open('record_count.txt', 'w') as f:
    f.write(str(num_empresas_records))