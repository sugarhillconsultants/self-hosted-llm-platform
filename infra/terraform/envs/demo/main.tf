# The demo environment: built for timed sessions, torn down after each.
# Approximate running cost: EKS control plane $0.10/h + one NAT gateway
# ~$0.045/h + 2 x t3.medium ~$0.083/h, about $0.23/hour or $5.50/day if left on.

data "aws_availability_zones" "available" {
  state = "available"
  # Local Zones and Wavelength zones don't support EKS node groups.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "${var.project}-demo"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

# --- Network -------------------------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.8.0"

  name = local.name
  cidr = "10.40.0.0/16"
  azs  = local.azs

  private_subnets = ["10.40.0.0/19", "10.40.32.0/19"]
  public_subnets  = ["10.40.128.0/24", "10.40.129.0/24"]

  # One NAT gateway, not one per AZ: an AZ outage takes out egress for the
  # other AZ's nodes. Accepted for a demo; it halves the NAT cost.
  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = 1
  }
}

# --- Cluster -------------------------------------------------------------------

# If the SSO AdministratorAccess role exists, give it cluster admin too, so
# you can use kubectl from your Mac when CI created the cluster (and vice versa).
data "aws_iam_roles" "sso_admin" {
  name_regex  = "^AWSReservedSSO_AdministratorAccess_.*"
  path_prefix = "/aws-reserved/sso.amazonaws.com/"
}

data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

module "cluster_admins" {
  source = "../../modules/cluster-admins"
  # The ARNs IAM itself returns, path included. Never rebuild an ARN from a
  # name: incident #5 was a rebuilt ARN naming a role that doesn't exist.
  candidate_role_arns = tolist(data.aws_iam_roles.sso_admin.arns)
  applying_role_arn   = data.aws_iam_session_context.current.issuer_arn
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.30.2"

  name               = local.name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.api_allowed_cidrs

  # Access entries (not the aws-auth ConfigMap). Creator gets admin.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true
  access_entries = {
    for i, arn in module.cluster_admins.extra_admin_role_arns : "sso-admin-${i}" => {
      principal_arn = arn
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }

  # No customer-managed KMS key: EKS already envelope-encrypts Kubernetes
  # secrets with an AWS-owned key, and a module-created key would cost $1/month
  # and linger for 7+ days in "pending deletion" after every teardown.
  create_kms_key    = false
  encryption_config = null

  enabled_log_types                      = ["audit", "authenticator"]
  cloudwatch_log_group_retention_in_days = 7

  addons = {
    vpc-cni = {
      before_compute = true
    }
    eks-pod-identity-agent = {
      before_compute = true
    }
    kube-proxy = {}
    coredns    = {}
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = [var.system_node_instance_type]
      min_size       = 1
      max_size       = 3
      desired_size   = 2

      labels = {
        "node-role" = "system"
      }
    }
  }
}

# --- Images --------------------------------------------------------------------

module "ecr_gateway" {
  source = "../../modules/ecr"
  name   = "${var.project}/gateway"
}
