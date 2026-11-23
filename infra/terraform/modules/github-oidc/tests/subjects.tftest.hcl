mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "111122223333" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

variables {
  state_bucket_arn = "arn:aws:s3:::example-tfstate"
  name_prefix      = "self-hosted-llm-platform"
}

# Incident #4: GitHub sent the immutable form; the roles must trust exactly that.
run "immutable_subjects" {
  command = plan
  variables {
    subject_prefix = "repo:sugarhillconsultants@12613063/self-hosted-llm-platform@1420000000"
  }
  assert {
    condition     = output.trusted_subjects.plan == "repo:sugarhillconsultants@12613063/self-hosted-llm-platform@1420000000:pull_request"
    error_message = "plan role must trust the PR subject in immutable form"
  }
  assert {
    condition     = output.trusted_subjects.apply == "repo:sugarhillconsultants@12613063/self-hosted-llm-platform@1420000000:environment:aws-demo"
    error_message = "apply role must trust only the aws-demo environment"
  }
}

run "rejects_prefix_with_context" {
  command = plan
  variables {
    subject_prefix = "repo:owner/repo:pull_request"
  }
  expect_failures = [var.subject_prefix]
}

run "rejects_missing_repo_prefix" {
  command = plan
  variables {
    subject_prefix = "sugarhillconsultants/self-hosted-llm-platform"
  }
  expect_failures = [var.subject_prefix]
}
