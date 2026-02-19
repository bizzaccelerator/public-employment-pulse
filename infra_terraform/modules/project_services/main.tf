resource "google_project_service" "required_apis" {
  for_each = toset([
    "iam.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "logging.googleapis.com",
    "vpcaccess.googleapis.com",
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
    "container.googleapis.com",
    "storage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "serviceusage.googleapis.com",
    "servicenetworking.googleapis.com",
    "bigquery.googleapis.com",
    "bigquerystorage.googleapis.com",
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
  disable_dependent_services = false
}