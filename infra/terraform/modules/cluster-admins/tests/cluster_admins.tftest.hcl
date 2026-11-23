variables {
  candidate_role_arns = ["arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_321d3283c27feef6"]
}

# Incident #5: the ARN must reach EKS exactly as IAM returned it, path included.
run "ci_apply_adds_sso_role_with_path_intact" {
  command = plan
  variables {
    applying_role_arn = "arn:aws:iam::111122223333:role/self-hosted-llm-platform-github-apply"
  }
  assert {
    condition     = output.extra_admin_role_arns == ["arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_321d3283c27feef6"]
    error_message = "CI apply must add the SSO admin role with its IAM path intact"
  }
}

run "sso_apply_with_path_is_not_added_twice" {
  command = plan
  variables {
    applying_role_arn = "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_321d3283c27feef6"
  }
  assert {
    condition     = length(output.extra_admin_role_arns) == 0
    error_message = "Applying as the SSO role must not add it again"
  }
}

run "sso_apply_without_path_is_not_added_twice" {
  command = plan
  variables {
    applying_role_arn = "arn:aws:iam::111122223333:role/AWSReservedSSO_AdministratorAccess_321d3283c27feef6"
  }
  assert {
    condition     = length(output.extra_admin_role_arns) == 0
    error_message = "Applying as the SSO role must not add it again"
  }
}

run "no_sso_role_in_account" {
  command = plan
  variables {
    candidate_role_arns = []
    applying_role_arn   = "arn:aws:iam::111122223333:role/self-hosted-llm-platform-github-apply"
  }
  assert {
    condition     = length(output.extra_admin_role_arns) == 0
    error_message = "No SSO role means no extra admins"
  }
}

run "similar_name_is_not_confused" {
  command = plan
  variables {
    applying_role_arn = "arn:aws:iam::111122223333:role/x-AWSReservedSSO_AdministratorAccess_321d3283c27feef6"
  }
  assert {
    condition     = length(output.extra_admin_role_arns) == 1
    error_message = "Only an exact role-name match should be skipped"
  }
}

run "rejects_bare_role_names" {
  command = plan
  variables {
    candidate_role_arns = ["AWSReservedSSO_AdministratorAccess_321d3283c27feef6"]
    applying_role_arn   = "arn:aws:iam::111122223333:role/self-hosted-llm-platform-github-apply"
  }
  expect_failures = [var.candidate_role_arns]
}
