resource "google_sql_database_instance" "postgres_instance" {
  name             = var.instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    edition = "ENTERPRISE"
    tier    = "db-custom-1-3840"
    ip_configuration {
      private_network = "projects/${var.project_id}/global/networks/${var.vpc_network}"
    }
    backup_configuration {
      enabled = true
    }
  }
  depends_on = [var.peering_dependency]

  deletion_protection = false

  lifecycle {
    prevent_destroy = false
  }
}

resource "google_sql_user" "postgres_user" {
  name     = var.db_user
  instance = google_sql_database_instance.postgres_instance.name
  password = var.db_password

  deletion_policy = "ABANDON"
  
  lifecycle {
    prevent_destroy = false
  }
}

resource "google_sql_database" "app_db" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres_instance.name
  
  deletion_policy = "ABANDON"
  
  lifecycle {
    prevent_destroy = false
  }
}
