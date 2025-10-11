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