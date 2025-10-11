# modules/kestra/outputs.tf

output "kestra_public_ip" {
  description = "Public IP address of Kestra server"
  value       = google_compute_address.kestra_static_ip.address
}

output "kestra_url" {
  description = "URL to access Kestra UI"
  value       = "http://${google_compute_address.kestra_static_ip.address}:8080"
}

output "database_instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.kestra_db.name
}

output "database_connection_name" {
  description = "Cloud SQL connection name"
  value       = google_sql_database_instance.kestra_db.connection_name
}

output "service_account_email" {
  description = "Email of the Kestra service account"
  value       = google_service_account.kestra_sa.email
}

output "vm_instance_name" {
  description = "Name of the Kestra VM instance"
  value       = google_compute_instance.kestra_vm.name
}
