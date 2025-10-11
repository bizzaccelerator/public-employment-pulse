# modules/kestra/main.tf

# Data sources
data "google_compute_default_service_account" "default" {}

# Data source para obtener el project number
data "google_project" "current" {
  project_id = var.project_id
}

# Habilitar APIs necesarias
resource "google_project_service" "cloudbuild_api" {
  project = var.project_id
  service = "cloudbuild.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "containerregistry_api" {
  project = var.project_id
  service = "containerregistry.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "storage_api" {
  project = var.project_id
  service = "storage.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

# Habilitar Logging API (necesaria para Cloud Build logs)
resource "google_project_service" "logging_api" {
  project = var.project_id
  service = "logging.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

# Cloud SQL instance for Kestra
resource "google_sql_database_instance" "kestra_db" {
  name             = "${replace(var.project_name, "_", "-")}-kestra-db"
  database_version = "POSTGRES_15"
  region          = var.region

  settings {
    tier = "db-f1-micro"

    backup_configuration {
      enabled                        = true
      start_time                    = "23:00"
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled    = true
      authorized_networks {
        name  = "allow-all"
        value = "0.0.0.0/0"
      }
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
  }

  deletion_protection = false

  # Permitir eliminación incluso con usuarios/bases de datos
  lifecycle {
    prevent_destroy = false
  }
}

resource "google_sql_database" "kestra_database" {
  name     = "kestra"
  instance = google_sql_database_instance.kestra_db.name
}

resource "google_sql_user" "kestra_user" {
  name     = "kestra"
  instance = google_sql_database_instance.kestra_db.name
  password = var.db_password
}

# Service Account for Kestra VM
resource "google_service_account" "kestra_sa" {
  account_id   = "kestra-service-account"
  display_name = "Kestra Service Account"
  description  = "Service account for Kestra VM with Cloud Build permissions"

  # Permitir eliminación
  lifecycle {
    prevent_destroy = false
  }
}

# PERMISOS BÁSICOS DE KESTRA
resource "google_project_iam_member" "kestra_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.storage_api]
}

resource "google_project_iam_member" "kestra_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"
}

resource "google_project_iam_member" "kestra_compute_viewer" {
  project = var.project_id
  role    = "roles/compute.viewer"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"
}

# PERMISOS PARA CLOUD BUILD Y CONTAINER REGISTRY
resource "google_project_iam_member" "kestra_cloudbuild_builder" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.cloudbuild_api]
}

resource "google_project_iam_member" "kestra_cloudbuild_editor" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.cloudbuild_api]
}

# CRÍTICO: Container Registry Service Agent
resource "google_project_iam_member" "kestra_container_registry_service_agent" {
  project = var.project_id
  role    = "roles/containerregistry.ServiceAgent"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.containerregistry_api]
}

# PERMISOS PARA STORAGE (más específicos)
resource "google_project_iam_member" "kestra_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.storage_api]
}

# PERMISOS PARA LOGGING (ver logs de Cloud Build)
resource "google_project_iam_member" "kestra_logging_viewer" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.logging_api]
}

# PERMISOS DE SERVICE ACCOUNT
resource "google_project_iam_member" "kestra_service_account_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"
}

# PERMISOS ADICIONALES PARA CLOUD BUILD (opcional pero recomendado)
resource "google_project_iam_member" "kestra_source_repo_admin" {
  project = var.project_id
  role    = "roles/source.admin"
  member  = "serviceAccount:${google_service_account.kestra_sa.email}"

  depends_on = [google_project_service.cloudbuild_api]
}

# Dar permisos al Cloud Build Service Account (se crea automáticamente)
resource "google_project_iam_member" "cloudbuild_sa_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.cloudbuild_api]
}

resource "google_project_iam_member" "cloudbuild_sa_container_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.cloudbuild_api]
}

# Firewall rule to allow HTTP traffic to Kestra
resource "google_compute_firewall" "kestra_firewall" {
  name    = "${replace(var.project_name, "_", "-")}-kestra-firewall"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["8080", "22", "443"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["kestra-server"]
}

# Static IP for Kestra VM
resource "google_compute_address" "kestra_static_ip" {
  name   = "${replace(var.project_name, "_", "-")}-kestra-ip"
  region = var.region
}

# Cloud Storage bucket para Cloud Build (opcional pero recomendado)
resource "google_storage_bucket" "cloudbuild_logs" {
  name     = "${var.project_id}-cloudbuild-logs"
  location = var.region

  uniform_bucket_level_access = true

  # Forzar eliminación incluso con objetos
  force_destroy = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  # Permitir eliminación
  lifecycle {
    prevent_destroy = false
  }
}

# Dar acceso al bucket de logs
resource "google_storage_bucket_iam_member" "kestra_cloudbuild_logs" {
  bucket = google_storage_bucket.cloudbuild_logs.name
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.kestra_sa.email}"
}

# Startup script for Kestra VM
locals {
  startup_script = templatefile("${path.module}/startup-script.sh", {
    db_host     = google_sql_database_instance.kestra_db.ip_address.0.ip_address
    db_name     = google_sql_database.kestra_database.name
    db_user     = google_sql_user.kestra_user.name
    db_password = var.db_password
    gcs_bucket  = var.gcs_bucket_name
    project_id  = var.project_id
  })
}

# Kestra VM instance
resource "google_compute_instance" "kestra_vm" {
  name         = "${replace(var.project_name, "_", "-")}-kestra-vm"
  machine_type = var.machine_type
  zone         = var.zone

  tags = ["kestra-server"]

  # Permitir eliminación
  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = 30
      type  = "pd-standard"
    }

    # Eliminar disco al eliminar la instancia
    auto_delete = true
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.kestra_static_ip.address
    }
  }

  service_account {
    email  = google_service_account.kestra_sa.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    startup-script = local.startup_script
  }

  # Allow recreation when startup script changes
  metadata_startup_script = local.startup_script

  # Permitir eliminación
  lifecycle {
    prevent_destroy = false
  }

  depends_on = [
    google_sql_database_instance.kestra_db,
    google_sql_database.kestra_database,
    google_sql_user.kestra_user,
    google_project_iam_member.kestra_cloudbuild_builder,
    google_project_iam_member.kestra_container_registry_service_agent
  ]
}

# Output para verificar la configuración
output "kestra_service_account_email" {
  description = "Email of the Kestra service account"
  value       = google_service_account.kestra_sa.email
}

output "cloudbuild_service_account" {
  description = "Cloud Build service account that gets created automatically"
  value       = "${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

output "project_number" {
  description = "Project number for reference"
  value       = data.google_project.current.number
}

output "cleanup_commands" {
  description = "Commands to run if terraform destroy fails"
  value = <<-EOT
    # Si terraform destroy falla, ejecuta estos comandos manualmente:

    # 1. Eliminar instancia VM
    gcloud compute instances delete ${replace(var.project_name, "_", "-")}-kestra-vm --zone=${var.zone} --quiet

    # 2. Liberar IP estática
    gcloud compute addresses delete ${replace(var.project_name, "_", "-")}-kestra-ip --region=${var.region} --quiet

    # 3. Eliminar regla de firewall
    gcloud compute firewall-rules delete ${replace(var.project_name, "_", "-")}-kestra-firewall --quiet

    # 4. Eliminar bucket de logs (forzar)
    gsutil rm -r gs://${var.project_id}-cloudbuild-logs

    # 5. Eliminar instancia de Cloud SQL
    gcloud sql instances delete ${replace(var.project_name, "_", "-")}-kestra-db --quiet

    # 6. Eliminar service account
    gcloud iam service-accounts delete kestra-service-account@${var.project_id}.iam.gserviceaccount.com --quiet

    # 7. Limpiar imágenes de Container Registry (opcional)
    gcloud container images list --repository=gcr.io/${var.project_id} --format="value(name)" | xargs -I {} gcloud container images delete {} --quiet --force-delete-tags
  EOT
}
