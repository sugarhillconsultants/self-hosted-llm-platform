# ADR 0008: Apply and destroy by manual workflow run, not on merge

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
The build plan said "plan on PR, apply on merge." That fits long-lived
infrastructure. This environment is the opposite: an EKS cluster plus NAT
gateway plus nodes costs about $0.23/hour (~$5.50/day), against a $50/month
budget. Apply-on-merge would create it on any infra change and leave it
running.

## Options considered
- Apply on merge to `main`
- Apply/destroy via manual `workflow_dispatch`, in a protected GitHub environment
- A scheduled nightly destroy (rejected for now: a scheduled job can't pass a
  required-reviewer gate, so it would need a second, weaker trust path to the
  admin role)

## Decision
Plan runs automatically on every PR, with a read-only role. Apply and destroy
run only when started by hand, in the `aws-demo` environment. The apply role's
trust policy accepts exactly `repo:sugarhillconsultants/self-hosted-llm-platform:environment:aws-demo`.

The apply role has `AdministratorAccess`: creating a VPC, an EKS cluster and
the cluster's own IAM roles needs broad rights, and a hand-tuned least-privilege
policy for EKS is long and brittle. The control is *who* can assume it (one
environment in one repo, optionally behind a required reviewer), not what it
can do.

## Consequences
- Merging an infra PR changes nothing in AWS until someone runs apply.
- The plan comment is produced by the plan role, so it lists the plan role as
  the cluster creator; the real apply makes the apply role the creator. The
  SSO admin role gets an access entry either way (`modules/cluster-admins`).
- Forgetting to destroy is still possible. Mitigations: the forecast budget
  alert, `make running`, and the cost reminder in every apply's job summary.
