output "raw_data_bucket_url" {
  value = module.gcs.raw_data_bucket_url
}

# KESTRA
output "kestra_public_ip" {
  description = "Public IP address of Kestra server"
  value       = module.kestra.kestra_public_ip
}

output "kestra_url" {
  description = "URL to access Kestra UI"
  value       = module.kestra.kestra_url
}
