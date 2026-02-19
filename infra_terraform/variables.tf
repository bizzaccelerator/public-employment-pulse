# GCP Project Variables
variable "credentials" {
  description = "Path to GCP service account credentials JSON file"
  type        = string
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "location" {
  description = "GCP location for multi-regional resources"
  type        = string
  default     = "US"
}

# Storage Variables
variable "storage_class" {
  description = "Storage class for GCS buckets"
  type        = string
  default     = "STANDARD"
}

# BigQuery Variables
variable "BQ_DATASET" {
  description = "Main BigQuery dataset name"
  type        = string
}

variable "OPERATIONS_DATASET" {
  description = "Operations BigQuery dataset name"
  type        = string
  default     = "operations_co"
}

variable "TABLE_NAME" {
  description = "BigQuery table name"
  type        = string
}

# Kestra Variables
variable "kestra_db_password" {
  description = "Password for Kestra database"
  type        = string
  sensitive   = true
}

variable "zone" {
  description = "GCP zone for zonal resources"
  type        = string
  default     = "us-central1-a"
}

# VPC Connector Variables
variable "connector_name" {
  description = "Name of the VPC connector"
  type        = string
  default     = "pgadmin-connector"
}

variable "vpc_network" {
  description = "VPC network name"
  type        = string
  default     = "default"
}

variable "min_throughput" {
  description = "Minimum throughput for VPC connector"
  type        = number
  default     = 200
}

variable "max_throughput" {
  description = "Maximum throughput for VPC connector"
  type        = number
  default     = 400
}

# Cloud SQL Variables
variable "instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "postgres-16"
}

variable "db_user" {
  description = "Database user name"
  type        = string
}

variable "db_password" {
  description = "Database password"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
}

# pgAdmin Variables
variable "service_name" {
  description = "pgAdmin Cloud Run service name"
  type        = string
  default     = "pgadmin-service"
}

variable "pgadmin_email" {
  description = "pgAdmin login email"
  type        = string
}

variable "pgadmin_password" {
  description = "pgAdmin login password"
  type        = string
  sensitive   = true
}

# IAM Variables
variable "invoker_identity" {
  description = "Identity that can invoke Cloud Run services"
  type        = string
}

# Service Networking Variables
variable "private_ip_name" {
  description = "Name for the private IP address range"
  type        = string
  default     = "cloudsql-private-ip"
}