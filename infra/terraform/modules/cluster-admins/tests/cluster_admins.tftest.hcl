variables {
  account_id           = "111122223333"
  candidate_role_names = ["AWSReservedSSO_AdministratorAccess_321d3283c27feef6"]
}

run "ci_apply_adds_sso_role_without_path" {
  command = plan
  variables {
    applying_role_arn = "arn:aws:iam::111122223333:role/self-hosted-llm-platform-github-apply"
  }
  assert {
    condition     = output.extra_admin_role_arns == ["arn:aws:iam::111122223333:role/AWSReservedSSO_AdministratorAccess_321d3283c27feef6"]
    error_message = "CI apply should add the SSO admin role, without its IAM path"
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
    candidate_role_names = []
    applying_role_arn    = "arn:aws:iam::111122223333:role/self-hosted-llm-platform-github-apply"
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
