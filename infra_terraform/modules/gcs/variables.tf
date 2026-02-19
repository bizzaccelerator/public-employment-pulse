variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "Region for resources"
  type        = string
}

variable "location" {
  description = "Location for multi-regional resources"
  type        = string
}

variable "storage_class" {
  description = "Storage class for GCS buckets"
  type        = string
  default     = "STANDARD"
}

locals {
  data_lake_bucket = "operations-raw-data"
}