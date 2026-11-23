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

- PR #1 (`phase-1-gate`): first run failed before Terraform ran, OIDC
  subject mismatch (incident #4). After the fix, the plan job passed with the
  read-only role: **Plan: 56 to add, 0 to change, 0 to destroy.**
- PR #2 (`fix-access-entry-path`, incidents #5 and #6, Node 24 actions): same
  plan, **Plan: 56 to add, 0 to change, 0 to destroy.** All checks green,
  including real Terraform 1.17.2 running the 6 + 3 module tests.

## 4. Manual apply from CI

All times UTC, 2026-11-23. Each run waited for approval in the `aws-demo`
environment.

| Run | Action | Start → end | Result |
|---|---|---|---|
| 45269613895 | apply | 21:26:04 → 21:44:19 | Failed: `InvalidParameterException: The specified principalArn is invalid: invalid principal` (incident #5) |
| 45274373387 | destroy | 21:54:27 → 22:07:30 | Partial environment removed |
| 45284951554 | apply | 23:00:33 → 23:17:29 | **Apply complete! Resources: 56 added, 0 changed, 0 destroyed.** |
| 45288422080 | destroy | 23:23:42 → 23:36:46 | Destroy complete; job 11m53s |

`kubectl get nodes` from the CI job, using the apply role (the cluster
creator), 110 s after the nodes joined:

```
2026-11-23T23:17:21Z Apply complete! Resources: 56 added, 0 changed, 0 destroyed.
NAME                           STATUS   ROLES    AGE    VERSION               INTERNAL-IP    EXTERNAL-IP   OS-IMAGE
ip-10-40-24-133.ec2.internal   Ready    <none>   110s   v1.37.1-eks-9adbfea   10.40.24.133   <none>        Amazon Linux 2023.12.20261118
ip-10-40-36-184.ec2.internal   Ready    <none>   110s   v1.37.1-eks-9adbfea   10.40.36.184   <none>        Amazon Linux 2023.12.20261118
```

Two nodes, one per private subnet (`10.40.0.0/19` and `10.40.32.0/19`, one
per AZ), no external IPs.

## 5. kubectl from the Mac (SSO role access entry)

The SSO `AdministratorAccess` role reached the cluster through the access
entry that failed in attempt 1, confirming the incident #5 fix:

```
$ aws eks update-kubeconfig --region us-east-1 --name self-hosted-llm-platform-demo
Added new context arn:aws:eks:us-east-1:…:cluster/self-hosted-llm-platform-demo to ~/.kube/config
$ kubectl get nodes -o wide
NAME                           STATUS   ROLES    AGE     VERSION               INTERNAL-IP    EXTERNAL-IP   OS-IMAGE                        KERNEL-VERSION                            CONTAINER-RUNTIME
ip-10-40-24-133.ec2.internal   Ready    <none>   3m13s   v1.37.1-eks-9adbfea   10.40.24.133   <none>        Amazon Linux 2023.12.20261118   6.18.62-127.179.amzn2023.x86_64 (amd64)   containerd://2.3.7+unknown
ip-10-40-36-184.ec2.internal   Ready    <none>   3m13s   v1.37.1-eks-9adbfea   10.40.36.184   <none>        Amazon Linux 2023.12.20261118   6.18.62-127.179.amzn2023.x86_64 (amd64)   containerd://2.3.7+unknown
```

## 6. Destroy and check

Destroy run 45288422080 succeeded (job 11m53s). Checked afterwards with the
fixed `whats-running.sh` (incident #6) and a valid SSO session:

```
$ make running
Checking us-east-1 as romeopeay

ok EKS clusters: none
ok NAT gateways: none
ok Running EC2 instances: none
ok Load balancers: none
ok Unattached EBS volumes: none
ok Unassociated Elastic IPs: none

Verified: nothing billable by the hour in us-east-1.
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

Estimated from run times at ~$0.23/hour (EKS control plane + one NAT gateway
+ 2 × t3.medium). Resources exist from shortly after an apply starts until
its destroy finishes.

| Item | Window (UTC) | Hours | Est. cost |
|---|---|---|---|
| Attempt 1: failed apply → destroy | 21:26 → 22:07 | 0.68 | $0.16 |
| Attempt 2: apply → destroy | 23:00 → 23:37 | 0.61 | $0.14 |
| Bootstrap (budget, S3, IAM) | ongoing | n/a | ~$0 |
| **Total** | | **1.29** | **~$0.30** |

To do: replace the estimate with the actual figure from Cost Explorer
(filter `Project = self-hosted-llm-platform`) once billing data lands.

## Phase 1 result

**Gate passed on 2026-11-23** after three incidents found during the phase
(#4 OIDC subject format, #5 access-entry ARN path, #6 false all-clear from the
cost check), each fixed and covered by a test or check.
