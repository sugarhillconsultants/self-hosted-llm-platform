variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "self-hosted-llm-platform"
}

variable "github_oidc_subject_prefix" {
  description = <<-EOT
    This repo's GitHub OIDC subject prefix. Set in local.auto.tfvars:
      gh api repos/sugarhillconsultants/self-hosted-llm-platform/actions/oidc/customization/sub --jq .sub_claim_prefix
  EOT
  type        = string
}

variable "budget_limit_usd" {
  type    = number
  default = 50
}

variable "budget_alert_email" {
  description = "Where budget alerts go. Set in local.auto.tfvars (gitignored), not in git."
  type        = string
}

variable "create_oidc_provider" {
  description = "false if the account already has a GitHub OIDC provider."
  type        = bool
  default     = true
}
