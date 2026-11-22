# ADR 0007: S3 native state locking instead of a DynamoDB table

- **Status:** Accepted
- **Date:** 2026-11-22

## Context
The build plan called for an S3 bucket plus a DynamoDB lock table, the
long-standing pattern. Terraform 1.10 added locking in S3 itself
(`use_lockfile = true`, a conditional-write `.tflock` object), and later
releases deprecate the DynamoDB option.

## Options considered
- S3 bucket + DynamoDB table (the classic pattern)
- S3 bucket with `use_lockfile` (Terraform >= 1.10)

## Decision
`use_lockfile`. One fewer resource, one fewer IAM permission set, and no
dependency on a deprecated backend option. `required_version = ">= 1.10"`
enforces it.

## Consequences
Anyone running an older Terraform gets a clear version error instead of
running unlocked. The plan role needs `PutObject`/`DeleteObject` on the state
bucket even though it is otherwise read-only, because taking the lock writes
an object.
