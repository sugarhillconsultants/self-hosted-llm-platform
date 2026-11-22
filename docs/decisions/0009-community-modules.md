# ADR 0009: Pinned community modules for VPC and EKS

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
The scaffold had empty `modules/vpc` and `modules/eks` folders. A correct EKS
setup (access entries, add-on ordering, node IAM, security groups) is several
hundred lines that `terraform-aws-modules/eks` already maintains and that most
teams use.

## Decision
Use `terraform-aws-modules/vpc/aws` 6.8.0 and `terraform-aws-modules/eks/aws`
21.30.2, pinned to exact versions. Write our own modules only where the logic
is ours: `budget`, `github-oidc`, `ecr`, `cluster-admins`.

## Consequences
Upgrades are deliberate version bumps with a reviewed plan, never silent
drift. The tradeoff is less hand-written EKS code to show; the interesting
decisions are in the inputs (access entries, no customer KMS key, single NAT,
log retention) and are commented where they are set.
