terraform {
  required_version = ">= 1.6"

  # Local state on purpose: ephemeral cluster, destroyed each session, solo dev.
  # Upgrade path (later): an S3 backend + DynamoDB lock (see project_plan Phase 9).
  # backend "s3" { ... }

  required_providers {
    aws        = { source = "hashicorp/aws", version = "~> 5.60" }
    kubernetes = { source = "hashicorp/kubernetes", version = "~> 2.30" }
  }
}

provider "aws" {
  region = var.region
}

# Kubernetes provider points at the EKS cluster this same config creates.
# Auth via `aws eks get-token` (exec plugin) — no static kubeconfig needed.
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.region]
  }
}
