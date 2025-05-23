locals {
  data_lake_bucket = "operations-raw-data "
}

variable "credentials" {
  description = "My Credentials"
  default     = "C://Users/jober/OneDrive/Desktop/public-employment-pulse/.keys/public-employment-pulse-27a9b5e5fd00.json"
}

variable "project" {
  description = "Public Employment Pulse is a strategic data-driven project designed to provide insights into the structure and dynamics of the public employment center operations in the city of Barranquilla."
  default = "public-employment-pulse"
}

variable "region" {
  description = "Region for GCP resources. Choose as per your location: https://cloud.google.com/about/locations"
  default = "us-central1"
  type = string
}

variable "location" {
  description = "Project Location"
  #Update the below to your desired location
  default     = "US"
}

variable "storage_class" {
  description = "Storage class type for your bucket. Check official docs for more info."
  default = "STANDARD"
}

variable "BQ_DATASET" {
  description = "BigQuery Dataset that raw data (from GCS) will be written to"
  type = string
  default = "operations-co"
}

variable "TABLE_NAME" {
  description = "BigQuery table"
  type = string
  default = "dummy"
}