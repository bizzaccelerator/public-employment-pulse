# Variables for GCP resources
credentials = "C://Users/jober/OneDrive/Desktop/public-employment-pulse/.keys/public-employment-pulse-ffa3f15171f6.json"
project_id  = "public-employment-pulse"
region      = "us-central1"
location     = "US"
storage_class = "STANDARD"
BQ_DATASET = "operations_co"
TABLE_NAME = "dummy"

# Variables for Kestra module
kestra_db_password = "kestra_secure_password_2024"
zone = "us-central1-a"

# Variables for VPC Connector module
connector_name = "pgadmin-connector"
vpc_network = "default"
min_throughput = 200
max_throughput = 400

# variables for Cloud SQL module
instance_name = "postgres-16"
db_user       = "main"
db_password   = "postgres_secure_password_2024"
db_name       = "app_db"

# pgAdmin Cloud Run variables
service_name = "pgadmin-service"
pgadmin_email = "jobert.gutierrez@gmail.com"
pgadmin_password = "pgadmin_secure_password_2024"

# IAM member with the role roles/run.invoker
invoker_identity = "user:jobert.gutierrez@gmail.com"

# Variables for Service Networking module
private_ip_name = "cloudsql-private-ip"