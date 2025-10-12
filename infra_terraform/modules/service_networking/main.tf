resource "google_project_service" "service_networking" {
  service = "servicenetworking.googleapis.com"
  project = var.project_id
}

resource "google_compute_global_address" "private_ip_range" {
  name          = var.private_ip_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = "projects/${var.project_id}/global/networks/${var.vpc_network}"
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = "projects/${var.project_id}/global/networks/${var.vpc_network}"
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]

  depends_on = [google_project_service.service_networking]
}
