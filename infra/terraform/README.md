# Terraform: Phase 1 runbook

Two layers:

| Layer | What | Applied by | State |
|---|---|---|---|
| `bootstrap/` | $50/month budget alarm, S3 state bucket, GitHub OIDC provider, `plan` and `apply` IAM roles | You, once, from your Mac (SSO) | Local first, then moved into the bucket |
| `envs/demo/` | VPC, EKS with 2 CPU nodes, ECR repo for the gateway | GitHub Actions (manual run), or `make up` | `s3://self-hosted-llm-platform-tfstate-<account-id>/envs/demo/` |

`modules/`: `budget`, `github-oidc`, `ecr`, `cluster-admins` (written here);
the VPC and EKS come from the pinned community modules (ADR 0009).

**Cost:** `bootstrap` is effectively free. `envs/demo` costs about **$0.23/hour
(~$5.50/day)** while it exists. Bring it up for a session, then destroy it.

## 0. Prerequisites

```bash
brew tap hashicorp/tap && brew install hashicorp/tap/terraform   # needs >= 1.10
export AWS_PROFILE=llm-platform
aws sso login            # whenever the session has expired
aws sts get-caller-identity
```

## 1. Bootstrap (once)

```bash
cd infra/terraform/bootstrap
echo 'budget_alert_email = "you@example.com"' > local.auto.tfvars   # gitignored
terraform init
terraform apply
```

If apply fails with `EntityAlreadyExists` on the OIDC provider, the account
already has one: add `create_oidc_provider = false` to `local.auto.tfvars` and
apply again.

The `github_secrets` output lists two role ARNs. They are identifiers, not
credentials, but they contain the account ID, so they go in secrets (masked
in logs) rather than variables.

## 2. GitHub settings

```bash
gh secret set AWS_PLAN_ROLE_ARN  --body "$(terraform output -json github_secrets | jq -r .AWS_PLAN_ROLE_ARN)"
gh secret set AWS_APPLY_ROLE_ARN --body "$(terraform output -json github_secrets | jq -r .AWS_APPLY_ROLE_ARN)"
```

(Or paste them in Settings → Secrets and variables → Actions.) Then in
Settings → Environments, create **`aws-demo`**. Optionally add yourself as a
required reviewer, so every apply/destroy waits for a click.

## 3. Lock provider versions

Record provider checksums for both your Mac and the Linux CI runners, and
commit the lock files:

```bash
cd ../  # infra/terraform
for d in bootstrap envs/demo; do
  terraform -chdir=$d init -backend=false -input=false
  terraform -chdir=$d providers lock -platform=darwin_arm64 -platform=linux_amd64
done
```

## 4. Move the bootstrap state into the bucket

Local state on one laptop is a single point of failure for the roles CI
depends on. In `bootstrap/versions.tf`, uncomment the `backend "s3"` block,
then:

```bash
cd bootstrap
terraform init -migrate-state \
  -backend-config="bucket=$(terraform output -raw state_bucket)"
# answer "yes"; then confirm and delete the local copy:
terraform state list && rm terraform.tfstate terraform.tfstate.backup
```

## 5. The Phase 1 gate

1. On a branch, set `kubernetes_version` in `envs/demo/terraform.tfvars` to
   AWS's current default:
   `aws eks describe-cluster-versions --default-only --query 'clusterVersions[0].clusterVersion' --output text`
2. Commit it with the lock files and the bootstrap backend change, push, open
   a PR. The **terraform** workflow posts the plan as a PR comment.
3. Merge. Nothing is created yet (apply is manual, ADR 0008).
4. Actions → **terraform** → Run workflow → `apply`. The job summary shows
   `kubectl get nodes` from CI.
5. From your Mac: `aws eks update-kubeconfig --region us-east-1 --name self-hosted-llm-platform-demo && kubectl get nodes`
6. Run the workflow again with `destroy`, then `make running` to confirm
   nothing billable is left.

Record each step's output in `docs/evidence/phase-1.md`.

## Day to day

```bash
make up        # create envs/demo from your Mac (same as the workflow's apply)
make down      # destroy it, then list anything still billing
make running   # anything in us-east-1 that bills by the hour? exit 1 if so
make tf-check  # fmt + cluster-admins module tests, no AWS needed
```
