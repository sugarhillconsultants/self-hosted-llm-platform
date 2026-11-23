# Which IAM roles get EKS cluster-admin, in addition to whoever runs apply.
#
# Pure logic, no resources, so it can be tested without AWS
# (tests/cluster_admins.tftest.hcl). Two rules:
#   1. Role ARNs are passed through exactly as IAM returns them, path
#      included. EKS access entries look the principal up in IAM; an SSO role
#      ARN with its /aws-reserved/sso.amazonaws.com/ path removed names a role
#      that doesn't exist ("invalid principal", incident #5). Stripping the
#      path was a rule for the older aws-auth ConfigMap, not access entries.
#   2. The role running apply already gets admin from the EKS module
#      (enable_cluster_creator_admin_permissions). Adding it again fails with
#      ResourceInUseException, so it is skipped. Compared by role name, since
#      the session's issuer ARN may or may not carry the path.

variable "candidate_role_arns" {
  description = "Full IAM role ARNs (with path), as returned by IAM, that should be cluster admins."
  type        = list(string)
  validation {
    condition     = alltrue([for a in var.candidate_role_arns : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+", a))])
    error_message = "candidate_role_arns must be IAM role ARNs."
  }
}

variable "applying_role_arn" {
  description = "issuer_arn of the session running apply (may include a path)."
  type        = string
}

locals {
  role_name          = { for a in var.candidate_role_arns : a => element(split("/", a), length(split("/", a)) - 1) }
  applying_role_name = element(split("/", var.applying_role_arn), length(split("/", var.applying_role_arn)) - 1)
}

output "extra_admin_role_arns" {
  value = [
    for a in var.candidate_role_arns : a
    if local.role_name[a] != local.applying_role_name
  ]
}
