output "data_lake_bucket_name" {
  description = "Name of the data lake bucket"
  value       = google_storage_bucket.data-lake-bucket.name
}

output "kestra_bucket_name" {
  description = "Name of the Kestra bucket"
  value       = google_storage_bucket.kestra_bucket.name
}

output "data_lake_bucket_url" {
  description = "URL of the data lake bucket"
  value       = google_storage_bucket.data-lake-bucket.url
}

output "kestra_bucket_url" {
  description = "URL of the Kestra bucket"
  value       = google_storage_bucket.kestra_bucket.url
}