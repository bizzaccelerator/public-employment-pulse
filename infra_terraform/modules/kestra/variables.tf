# modules/kestra/variables.tf

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "Machine type for Kestra VM"
  type        = string
  default     = "e2-standard-2"
}

variable "db_password" {
  description = "Password for Kestra database user"
  type        = string
  sensitive   = true
}

variable "gcs_bucket_name" {
  description = "GCS bucket name for Kestra storage"
  type        = string
}
