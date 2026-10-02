data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
  tags = {
    Project   = "hungry"
    ManagedBy = "terraform"
    Ephemeral = "true"
  }
}

# --------------------------------------------------------------------------
# VPC: 2 AZs, public + private subnets, one NAT gateway (cost saver).
# Nodes live in private subnets; the NLB for the api lives in public.
# --------------------------------------------------------------------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.cluster_name}-vpc"
  cidr = "10.0.0.0/16"

  azs             = local.azs
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true # one NAT, not one per AZ — cheaper, less HA

  # Tags that let EKS auto-discover subnets for LoadBalancer Services.
  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }

  tags = local.tags
}

# --------------------------------------------------------------------------
# EKS: control plane + one managed CPU node group + core addons.
# --------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  # Public API endpoint so kubectl/helm reach it from here (learning cluster).
  cluster_endpoint_public_access = true
  # Grant the identity running terraform cluster-admin, so kubectl works after apply.
  enable_cluster_creator_admin_permissions = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = {}
    aws-ebs-csi-driver = {
      # IRSA role so the CSI driver can create EBS volumes without static keys.
      service_account_role_arn = module.ebs_csi_irsa.iam_role_arn
    }
  }

  eks_managed_node_groups = {
    cpu = {
      instance_types = [var.node_instance_type]
      capacity_type  = "ON_DEMAND"
      desired_size   = var.node_desired
      min_size       = var.node_min
      max_size       = var.node_max
    }
  }

  tags = local.tags
}

# IRSA role for the EBS CSI driver (attaches the AWS-managed CSI policy).
module "ebs_csi_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name             = "${var.cluster_name}-ebs-csi"
  attach_ebs_csi_policy = true

  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["kube-system:ebs-csi-controller-sa"]
    }
  }

  tags = local.tags
}

# --------------------------------------------------------------------------
# gp3 StorageClass, marked default. The EBS CSI addon does NOT create one,
# so PVCs (CNPG, TEI) would stay Pending without this. Matches global.storageClass
# in the Helm values.
# --------------------------------------------------------------------------
resource "kubernetes_storage_class" "gp3" {
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
    }
  }
  storage_provisioner    = "ebs.csi.aws.com"
  volume_binding_mode    = "WaitForFirstConsumer"
  allow_volume_expansion = true
  parameters = {
    type = "gp3"
  }

  depends_on = [module.eks]
}
