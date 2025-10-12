output "pgadmin_url" {
  value = google_cloud_run_service.pgadmin.status[0].url
}
