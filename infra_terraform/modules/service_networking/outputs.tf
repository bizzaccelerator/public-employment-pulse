output "private_ip_range_name" {
  description = "Name of the reserved IP range used for VPC peering"
  value       = google_compute_global_address.private_ip_range.name
}

output "vpc_connection_name" {
  description = "VPC connection service name"
  value       = google_service_networking_connection.private_vpc_connection.peering
}

