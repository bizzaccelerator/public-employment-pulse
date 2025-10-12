resource "google_vpc_access_connector" "connector" {
  name          = var.connector_name
  region        = var.region
  network       = var.vpc_network
  ip_cidr_range = "10.8.0.0/28"
  min_throughput = var.min_throughput
  max_throughput  = var.max_throughput
}
