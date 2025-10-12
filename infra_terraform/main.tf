terraform {
  required_version = ">= 1.0"
  backend "gcs" {}  # Can change from "local" to "gcs" (for google) or "s3" (for aws), if you would like to preserve your tf-state online
  required_providers {
    google = {
      source  = "hashicorp/google"
    }
  }
}

provider "google" {
  credentials = file(var.credentials)
  project = var.project_id
  region = var.region
}

module "gcs" {
  source        = "./modules/gcs"
  
  project_id    = var.project_id
  region        = var.region
  credentials   = var.credentials
  location      = var.location
  BQ_DATASET    = var.BQ_DATASET
  TABLE_NAME    = var.TABLE_NAME
  storage_class = var.storage_class
}

module "kestra" {
  source = "./modules/kestra"

  project_id      = var.project_id
  project_name    = replace(var.project_id, "-", "_")
  region          = var.region
  zone            = var.zone
  db_password     = var.kestra_db_password
  gcs_bucket_name = module.gcs.kestra_bucket_name
}

module "vpc_connector" {
  source         = "./modules/vpc_connector"
  connector_name = "pgadmin-connector"
  region         = var.region
  vpc_network    = var.vpc_network
}

module "cloudsql_postgres" {
  source        = "./modules/cloudsql_postgres"
  instance_name = "postgres-16"
  region        = var.region
  vpc_network   = var.vpc_network
  db_user       = var.db_user
  db_password   = var.db_password
  db_name       = var.db_name
}

module "pgadmin_cloudrun" {
  source           = "./modules/pgadmin_cloudrun"
  service_name     = "pgadmin-service"
  region           = var.region
  pgadmin_email    = var.pgadmin_email
  pgadmin_password = var.pgadmin_password
  invoker_identity = var.invoker_identity
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = var.invoker_identity
}
