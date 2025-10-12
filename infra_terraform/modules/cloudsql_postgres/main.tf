resource "google_sql_database_instance" "postgres_instance" {
  name             = var.instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = "db-custom-1-3840" # Customize as needed
    ip_configuration {
      private_network = var.vpc_network
    }
    backup_configuration {
      enabled = true
    }
  }
}

resource "google_sql_user" "postgres_user" {
  name     = var.db_user
  instance = google_sql_database_instance.postgres_instance.name
  password = var.db_password
}

resource "google_sql_database" "app_db" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres_instance.name
}
