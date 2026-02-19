terraform {
  required_version = ">= 1.0"
  backend "gcs" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  credentials = file(var.credentials)
  project     = var.project_id
  region      = var.region
}

module "project_services" {
  source     = "./modules/project_services"
  project_id = var.project_id
}

module "gcs" {
  source        = "./modules/gcs"
  project_id    = var.project_id
  region        = var.region
  location      = var.location
  storage_class = var.storage_class

  depends_on = [module.project_services]
}

module "bigquery" {
  source                = "./modules/bigquery"
  project_id            = var.project_id
  location              = var.location
  main_dataset_name     = var.BQ_DATASET
  operations_dataset_name = var.OPERATIONS_DATASET

  depends_on = [module.project_services]
}

module "kestra" {
  source          = "./modules/kestra"
  project_id      = var.project_id
  project_name    = replace(var.project_id, "-", "_")
  region          = var.region
  zone            = var.zone
  db_password     = var.kestra_db_password
  gcs_bucket_name = module.gcs.kestra_bucket_name

  depends_on = [module.project_services]
}

module "vpc_connector" {
  source         = "./modules/vpc_connector"
  connector_name = "pgadmin-connector"
  region         = var.region
  vpc_network    = var.vpc_network
  min_throughput = var.min_throughput
  max_throughput = var.max_throughput
  
  depends_on = [module.service_networking, module.project_services]
}

module "service_networking" {
  source          = "./modules/service_networking"
  project_id      = var.project_id
  vpc_network     = var.vpc_network
  private_ip_name = var.private_ip_name

  depends_on = [module.project_services]
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = var.invoker_identity

  depends_on = [module.project_services]
}

module "cloudsql_postgres" {
  source             = "./modules/cloudsql_postgres"
  instance_name      = "postgres-16"
  region             = var.region
  vpc_network        = var.vpc_network
  db_user            = var.db_user
  db_password        = var.db_password
  db_name            = var.db_name
  project_id         = var.project_id
  peering_dependency = module.service_networking.vpc_connection_name

  depends_on = [module.project_services]
}

module "pgadmin_cloudrun" {
  source           = "./modules/pgadmin_cloudrun"
  service_name     = "pgadmin-service"
  region           = var.region
  pgadmin_email    = var.pgadmin_email
  pgadmin_password = var.pgadmin_password
  invoker_identity = "allUsers"
  vpc_connector_id = module.vpc_connector.connector_id
  
  depends_on = [module.vpc_connector, module.cloudsql_postgres, module.project_services]
}