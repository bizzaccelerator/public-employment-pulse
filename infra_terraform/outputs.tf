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

# CLOUDSQL POSTGRES
output "postgres_instance_connection_name" {
  description = "Cloud SQL connection string"
  value       = module.cloudsql_postgres.postgres_instance_connection_name
}

output "pgadmin_url" {
  description = "Public URL of the pgAdmin Cloud Run service"
  value       = module.pgadmin_cloudrun.pgadmin_url
}

output "vpc_connector_name" {
  description = "Name of the VPC connector"
  value       = module.vpc_connector.vpc_connector_name
}
