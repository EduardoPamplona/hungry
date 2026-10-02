variable "region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  type    = string
  default = "hungry"
}

variable "cluster_version" {
  type    = string
  default = "1.31" # a version EKS currently supports; bump deliberately
}

variable "node_instance_type" {
  type    = string
  default = "t3.large" # 2 vCPU / 8GB each
}

variable "node_desired" {
  type    = number
  default = 2
}

variable "node_min" {
  type    = number
  default = 1
}

variable "node_max" {
  type    = number
  default = 3
}
