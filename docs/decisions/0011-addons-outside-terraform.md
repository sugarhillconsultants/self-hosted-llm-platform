# ADR 0011: Cluster add-ons installed by script, not Terraform providers

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
Karpenter's controller, the NVIDIA device plugin and the NodePool live inside
the cluster. Terraform could install them with the `helm` and `kubernetes`
providers in the same configuration that creates the cluster.

## Options considered
- `helm`/`kubernetes` providers in `envs/demo`, configured from the cluster
  the same apply creates
- A script (`scripts/k8s-platform.sh up|down`) run after apply and before
  destroy, by `make up/down` and by the CI workflow

## Decision
The script. Providers configured from a resource in the same apply are a
known source of plan-time errors on the first apply, and on destroy Terraform
would remove the Helm release (the Karpenter controller) before Karpenter had
terminated its nodes, leaving a GPU instance billing outside Terraform's
knowledge. Teardown order matters here, and a script makes it explicit and
testable: nodes first, then add-ons, then infrastructure.

## Consequences
- Two steps instead of one (`terraform apply`, then `k8s-platform.sh up`);
  both `make up` and the workflow run them together.
- Chart versions are pinned in the script, not in Terraform state; changing
  one is a reviewed diff like any other.
