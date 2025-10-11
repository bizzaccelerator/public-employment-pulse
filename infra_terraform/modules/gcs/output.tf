output "raw_data_bucket_url" {
  value = "gs://${google_storage_bucket.data-lake-bucket.name}"
}

output "bq_dataset_id" {
  value = google_bigquery_dataset.dataset.dataset_id
}

output "kestra_bucket_name" {
  description = "Name of the Kestra GCS bucket"
  value       = google_storage_bucket.kestra_bucket.name
}

output "kestra_bucket_url" {
  description = "URL of the Kestra GCS bucket"
  value       = google_storage_bucket.kestra_bucket.url
}