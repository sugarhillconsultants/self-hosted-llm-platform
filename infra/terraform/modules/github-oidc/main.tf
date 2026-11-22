# GitHub Actions -> AWS without stored keys. Two roles, each trusted only by
# one kind of workflow run in one repository:
#
#   plan  : pull_request runs. Read-only on the account + the state bucket.
#   apply : runs in the GitHub environment `aws-demo`. Can create and destroy
#           the demo environment. See docs/decisions/0008.

variable "github_repository" {
  description = "owner/repo"
  type        = string
}

variable "apply_environment" {
  description = "GitHub environment whose jobs may assume the apply role."
  type        = string
  default     = "aws-demo"
}

variable "name_prefix" {
  type = string
}

variable "state_bucket_arn" {
  type = string
}

variable "create_oidc_provider" {
  description = "Set false if this account already has the GitHub OIDC provider (one per account)."
  type        = bool
  default     = true
}

locals {
  oidc_host = "token.actions.githubusercontent.com"
}

data "aws_caller_identity" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
  # AWS no longer uses thumbprints for this provider, but older APIs require
  # the field; these are GitHub's published values.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.oidc_host}"
}

data "aws_iam_policy_document" "trust" {
  for_each = {
    plan  = "repo:${var.github_repository}:pull_request"
    apply = "repo:${var.github_repository}:environment:${var.apply_environment}"
  }

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
    # StringEquals, not StringLike: an exact subject, no wildcards. A typo
    # here is the AWS twin of the Azure AADSTS700213 incident in
    # multi-cloud-mlops-showcase.
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "this" {
  for_each             = data.aws_iam_policy_document.trust
  name                 = "${var.name_prefix}-github-${each.key}"
  assume_role_policy   = each.value.json
  max_session_duration = 3600
}

# --- plan: read-only everywhere, read/write only on the state bucket ---------

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.this["plan"].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "state" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.state_bucket_arn]
  }
  # Read state, and write/delete the .tflock lockfile that plan takes.
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.state_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "terraform-state"
  role   = aws_iam_role.this["plan"].id
  policy = data.aws_iam_policy_document.state.json
}

# --- apply: administrator, guarded by the trust policy -----------------------
# Creating a VPC, an EKS cluster and its IAM roles needs broad rights. The
# guard is who can assume the role (one environment of one repo, optionally
# with a required reviewer), not what the role can do. ADR 0008.

resource "aws_iam_role_policy_attachment" "apply_admin" {
  role       = aws_iam_role.this["apply"].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "plan_role_arn" {
  value = aws_iam_role.this["plan"].arn
}

output "apply_role_arn" {
  value = aws_iam_role.this["apply"].arn
}
