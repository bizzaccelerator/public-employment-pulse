variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "location" {
  description = "Location for BigQuery datasets"
  type        = string
}

variable "main_dataset_name" {
  description = "Name for the main BigQuery dataset"
  type        = string
}

variable "operations_dataset_name" {
  description = "Name for the operations BigQuery dataset"
  type        = string
  default     = "operations_co"
}