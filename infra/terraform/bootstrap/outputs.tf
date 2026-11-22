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
