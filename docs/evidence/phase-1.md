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

```
<terraform apply summary: resources created>
<terraform output: state_bucket, budget_name (role ARNs trimmed)>
```

## 2. Bootstrap state moved into S3

```
<terraform init -migrate-state output; aws s3 ls of the bucket>
```

## 3. PR plan comment

- PR link:
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
<gh secret list>
```

## Cost of this phase

| Item | Hours | Cost |
|---|---|---|
| EKS + NAT + nodes during the gate | | |
