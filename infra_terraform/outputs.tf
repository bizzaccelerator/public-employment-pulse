# GCS Outputs
output "data_lake_bucket_name" {
  description = "Name of the data lake bucket"
  value       = module.gcs.data_lake_bucket_name
}

output "kestra_bucket_name" {
  description = "Name of the Kestra bucket"
  value       = module.gcs.kestra_bucket_name
}

# BigQuery Outputs
output "main_dataset_id" {
  description = "Main BigQuery dataset ID"
  value       = module.bigquery.main_dataset_id
}

output "operations_dataset_id" {
  description = "Operations BigQuery dataset ID"
  value       = module.bigquery.operations_dataset_id
}

# API Outputs
output "enabled_apis" {
  description = "List of enabled GCP APIs"
  value       = module.project_services.enabled_apis
}

# Kestra Outputs
output "kestra_url" {
  description = "URL to access Kestra UI"
  value       = module.kestra.kestra_url
}

output "kestra_vm_instance_name" {
  description = "Name of the Kestra VM instance"
  value       = module.kestra.vm_instance_name
}