resource "google_cloud_run_service" "pgadmin" {
  name     = var.service_name
  location = var.region

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/initial-scale" = "1"
        "run.googleapis.com/vpc-access-connector" = var.vpc_connector_id
        "run.googleapis.com/vpc-access-egress"    = "private-ranges-only"
      }
    }
    spec {
      containers {
        image = "dpage/pgadmin4:latest"
        ports {
          container_port = 80
        }
        env {
          name  = "PGADMIN_DEFAULT_EMAIL"
          value = var.pgadmin_email
        }
        env {
          name  = "PGADMIN_DEFAULT_PASSWORD"
          value = var.pgadmin_password
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

resource "google_cloud_run_service_iam_member" "invoker" {
  service    = google_cloud_run_service.pgadmin.name
  location   = var.region
  role       = "roles/run.invoker"
  member     = var.invoker_identity
}
