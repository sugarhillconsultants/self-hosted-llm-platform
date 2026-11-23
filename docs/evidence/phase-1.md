# Phase 1 evidence: Terraform foundation on AWS

**Gate:** a PR shows a real `terraform plan` comment; a manual apply creates
the cluster; `kubectl get nodes` from CI shows the system nodes; the repo
holds no AWS access keys (only role ARNs, as masked secrets). Revised from
the original "apply on merge" by ADR 0008.

Paste real output only. Trim account IDs to the last four digits.

## Pre-deployment checks (cloud sandbox, no AWS access)

- Both layers pass `validate` against the real pinned modules (VPC 6.8.0,
  EKS 21.30.2) and AWS provider 6.73.0, using OpenTofu 1.11 (Terraform's
  registry was unreachable from the sandbox; CI runs real Terraform 1.17.2).
- `fmt` clean; workflows pass actionlint; scripts pass shellcheck.
- `modules/cluster-admins`: 5 `terraform test` cases pass.
- Not yet done: any `plan` or `apply` against AWS.

## 1. Bootstrap apply (from the Mac)

2026-11-22, from the Mac with the `llm-platform` SSO profile (AdministratorAccess).

```
Apply complete! Resources: 14 added, 0 changed, 0 destroyed.

Outputs:

budget_name = "self-hosted-llm-platform-monthly"
github_secrets = {
  "AWS_APPLY_ROLE_ARN" = "arn:aws:iam::00xx…:role/self-hosted-llm-platform-github-apply"
  "AWS_PLAN_ROLE_ARN" = "arn:aws:iam::00xx…:role/self-hosted-llm-platform-github-plan"
}
state_bucket = "self-hosted-llm-platform-tfstate-00xx…"
```

14 = budget (1) + state bucket and its 7 settings (8) + OIDC provider, two
roles and three permission attachments (5).

## 2. Bootstrap state moved into S3

2026-11-23. First attempt failed: the runbook derived the bucket name with
`terraform output`, which refuses to run once a new backend block is present,
so the bucket name came out empty (`The value cannot be empty`). Runbook
fixed to derive it from the account ID instead.

```
$ terraform state list | wc -l
      20
$ terraform state list | grep -v 'data\.' | wc -l
      14
$ aws s3 ls "s3://$BUCKET/bootstrap/"
2026-11-23 04:43:50      37103 terraform.tfstate
$ terraform plan
No changes. Your infrastructure matches the configuration.
```

(20 includes 6 data sources: lookups, not created resources.)

## 3. PR plan comment

- PR: #1 (`phase-1-gate`)
- First run: failed before Terraform ran, OIDC subject mismatch (incident #4)
- Plan summary line:

## 4. Manual apply from CI

- Workflow run link:
- Duration:

```
<kubectl get nodes -o wide from the job summary>
```

## 5. kubectl from the Mac (SSO role access entry)

```
<kubectl get nodes>
```

## 6. Destroy and check

```
<destroy summary>
<make running output>
```

## Secrets in the repo

```
$ gh secret list
NAME                UPDATED
AWS_APPLY_ROLE_ARN  about 1 minute ago
AWS_PLAN_ROLE_ARN   about 1 minute ago
```

No AWS access keys: two role ARNs only. Environment `aws-demo` exists with
`required_reviewers`.

## Cost of this phase

| Item | Hours | Cost |
|---|---|---|
| EKS + NAT + nodes during the gate | | |
