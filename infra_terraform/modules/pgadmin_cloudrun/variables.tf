variable "service_name" {}
variable "region" {}
variable "pgadmin_email" {}
variable "pgadmin_password" {}
variable "invoker_identity" {} # e.g., "user:your-email@example.com"

variable "vpc_connector_id" {
  description = "The VPC connector ID for Cloud Run"
  type        = string
}