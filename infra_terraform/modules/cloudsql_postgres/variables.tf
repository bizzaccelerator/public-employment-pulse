variable "instance_name" {}
variable "region" {}
variable "vpc_network" {}
variable "db_user" {}
variable "db_password" {}
variable "db_name" {}
variable "project_id" {}
variable "peering_dependency" {
  description = "Resource to wait for VPC peering"
}
