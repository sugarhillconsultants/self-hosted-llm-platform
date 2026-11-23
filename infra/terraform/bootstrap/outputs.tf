output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "budget_name" {
  value = module.budget.name
}

output "github_secrets" {
  description = "Add these as repository secrets (Settings -> Secrets and variables -> Actions). They are identifiers, not credentials."
  value = {
    AWS_PLAN_ROLE_ARN  = module.github_oidc.plan_role_arn
    AWS_APPLY_ROLE_ARN = module.github_oidc.apply_role_arn
  }
}

output "trusted_subjects" {
  description = "The exact OIDC subjects each role accepts."
  value       = module.github_oidc.trusted_subjects
}
