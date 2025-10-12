variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "vpc_network" {
  description = "Name of the VPC network"
  type        = string
}

variable "private_ip_name" {
  description = "Name of the reserved private IP range"
  type        = string
}
