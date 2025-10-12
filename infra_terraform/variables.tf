# GCS MODULE VARIABLES
locals {
  data_lake_bucket = "operations-raw-data"
}

variable "credentials" {
  description = "My Credentials"
}

variable "project_id" {
  description = "Public Employment Pulse is a strategic data-driven project designed to provide insights into the structure and dynamics of the public employment center operations in the city of Barranquilla."
}

variable "region" {
  description = "Region for GCP resources. Choose as per your location: https://cloud.google.com/about/locations"
  type = string
}

variable "location" {
  description = "Project Location"
  #Update the below to your desired location
}

variable "storage_class" {
  description = "Storage class type for your bucket. Check official docs for more info."
}

variable "BQ_DATASET" {
  description = "BigQuery Dataset that raw data (from GCS) will be written to"
  type = string
}

variable "TABLE_NAME" {
  description = "BigQuery table"
  type = string
}



# KESTRA MODULE VARIABLES
variable "kestra_db_password" {
  description = "Password for Kestra database user"
  type        = string
  sensitive   = true
}

variable "zone" {
  description = "GCP zone"
  type        = string
}

# VPC CONNECTOR MODULE VARIABLES
variable "vpc_network" {
  description = "Name of the VPC network"
  type        = string
}

# VPC Connector
variable "connector_name" {
  description = "Name of the VPC connector"
  type        = string
}

variable "max_throughput" {
  description = "VPC connector throughput in Mbps (200–1000, multiple of 100)"
  type        = number
}

variable "min_throughput" {
  description = "VPC connector throughput in Mbps (200–1000, multiple of 100)"
  type        = number
}


# CLOUDSQL POSTGRES MODULE VARIABLES
# Cloud SQL PostgreSQL
variable "instance_name" {
  description = "Cloud SQL instance name"
  type        = string
}

variable "db_user" {
  description = "PostgreSQL username"
  type        = string
}

variable "db_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Name of the application database"
  type        = string
}

# pgAdmin Cloud Run
variable "service_name" {
  description = "Cloud Run service name for pgAdmin"
  type        = string
}

variable "pgadmin_email" {
  description = "pgAdmin default login email"
  type        = string
}

variable "pgadmin_password" {
  description = "pgAdmin default login password"
  type        = string
  sensitive   = true
}

variable "invoker_identity" {
  description = "IAM identity allowed to invoke pgAdmin (e.g., user:you@example.com)"
  type        = string
}

# SERVICE NETWORKING MODULE VARIABLES
variable "private_ip_name" {
  description = "Name for the private IP address"
  type        = string
}
