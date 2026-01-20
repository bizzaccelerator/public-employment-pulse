# Main Data Warehouse Dataset
resource "google_bigquery_dataset" "main_dataset" {
  dataset_id = var.main_dataset_name
  project    = var.project_id
  location   = var.location
  
  description = "Main data warehouse dataset"
  
  labels = {
    env  = "production"
    type = "data_warehouse"
  }
}

# Operations Dataset
resource "google_bigquery_dataset" "operations_dataset" {
  dataset_id = var.operations_dataset_name
  project    = var.project_id
  location   = var.location
  
  description = "Operations dataset for workflow orchestration"
  
  labels = {
    env  = "production"
    type = "operations"
  }
}