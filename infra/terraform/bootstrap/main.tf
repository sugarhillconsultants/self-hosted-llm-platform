# Applied once, by hand, with your own (SSO) credentials. Everything else
# goes through GitHub Actions using the roles created here.

data "aws_caller_identity" "current" {}

locals {
  # Deterministic, so scripts and CI can derive it from the account ID
  # instead of storing it anywhere.
  state_bucket = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"
}

# --- 1. Cost guardrail first ---------------------------------------------------

module "budget" {
  source       = "../modules/budget"
  name         = "${var.project}-monthly"
  limit_usd    = var.budget_limit_usd
  alert_emails = [var.budget_alert_email]
}

# --- 2. Remote state -----------------------------------------------------------
# S3 native locking (use_lockfile) instead of a DynamoDB table: ADR 0007.

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket
  # Refuse `terraform destroy` while it still holds state.
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# --- 3. GitHub Actions identity -------------------------------------------------

module "github_oidc" {
  source               = "../modules/github-oidc"
  name_prefix          = var.project
  subject_prefix       = var.github_oidc_subject_prefix
  state_bucket_arn     = aws_s3_bucket.state.arn
  create_oidc_provider = var.create_oidc_provider
}
