# Which IAM roles get EKS cluster-admin, in addition to whoever runs apply.
#
# Pure logic, no resources, so it can be tested without AWS
# (tests/cluster_admins.tftest.hcl). Two rules:
#   1. EKS access entries take a role ARN *without* its IAM path, and SSO roles
#      live under /aws-reserved/sso.amazonaws.com/, so the path is dropped.
#   2. The role running apply already gets admin from the EKS module
#      (enable_cluster_creator_admin_permissions). Adding it again fails with
#      ResourceInUseException, so it is skipped.

variable "account_id" {
  type = string
}

variable "candidate_role_names" {
  description = "Role names (no path) that should be cluster admins."
  type        = list(string)
}

variable "applying_role_arn" {
  description = "issuer_arn of the session running apply (may include a path)."
  type        = string
}

locals {
  applying_role_name = element(split("/", var.applying_role_arn), length(split("/", var.applying_role_arn)) - 1)
}

output "extra_admin_role_arns" {
  value = [
    for n in var.candidate_role_names : "arn:aws:iam::${var.account_id}:role/${n}"
    if n != local.applying_role_name
  ]
}
