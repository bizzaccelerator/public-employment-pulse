output "main_dataset_id" {
  description = "Main BigQuery dataset ID"
  value       = google_bigquery_dataset.main_dataset.dataset_id
}

output "operations_dataset_id" {
  description = "Operations BigQuery dataset ID"
  value       = google_bigquery_dataset.operations_dataset.dataset_id
}

output "main_dataset_self_link" {
  description = "Main dataset self link"
  value       = google_bigquery_dataset.main_dataset.self_link
}

output "operations_dataset_self_link" {
  description = "Operations dataset self link"
  value       = google_bigquery_dataset.operations_dataset.self_link
}