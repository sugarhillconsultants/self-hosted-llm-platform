# Real Incidents Encountered Building This Platform

Same rationale as every other project in this portfolio: an honest account of
what actually broke, found from real failure output, is more useful than a
platform that "just worked." This is the first project in the portfolio on
AWS, on Kubernetes, and serving a model on a GPU I provisioned myself — so the
expectation is that it hits failure categories none of the Azure projects
could.

<!--
HOW TO WRITE AN ENTRY (match the existing portfolio logs):

## N. <What happened, stated as a finding — not "Bug in X">

Narrative paragraph(s), in this order, without sub-headings:
  - Symptom: what I actually saw. Quote the real error / status / log line.
  - How I found the cause: the command that revealed it
    (kubectl describe, kubectl logs --previous, terraform plan, CloudTrail…).
  - Root cause: the real mechanism, explained so someone could recognize it
    on a different project.
  - Fix: what changed, in which file, and how I confirmed it held.
  - Category, in **bold**, when it's a first: e.g. **the first GPU-scheduling
    failure in this portfolio**, or **a lesson from Project N that transferred**.

Multiple compounding bugs in one effort → one entry with **Na — …**, **Nb — …**
bold-led paragraphs, then an "**After all four**, …" paragraph.

Rules:
  - Write it the same day, from the real output, not from memory.
  - Positive outcomes count: a prior lesson that genuinely prevented a repeat
    gets its own entry (see log-anomaly-platform #1–2).
  - Process failures count (fix verified but never committed).
  - Honest limitations that aren't bugs count, stated plainly, and also go
    into the README's "What I'd add next".
  - Never smooth over a step that took several attempts.
-->

## 1. Request models defined inside the app factory were silently treated as query parameters

The first run of the gateway's test suite failed 9 of 33 tests, and every
failure was a `422` where a `200` or `401` was expected. Calling `POST /token`
directly showed why: `{"type":"missing","loc":["query","body"],"msg":"Field
required"}`. FastAPI thought the JSON body was a missing **query** parameter
named `body`. The cause was a combination of two individually reasonable
choices: the Pydantic request models (`TokenRequest`, `ChatRequest`) were
defined *inside* `create_app()`, and `main.py` uses `from __future__ import
annotations`, so every annotation is stored as a string. FastAPI resolves those
strings against the module's globals, where local classes don't exist; when
resolution fails it falls back to treating the parameter as a plain query
value, with no error at startup. Fixed by moving the models to module level,
with a comment explaining why. **Found before anything was deployed**, by the
tests, which is the argument for writing them first. A route that silently
misreads its own input would have looked like a client bug from the outside.

## 2. The fallback backend rejected a parameter the gateway added, and the client was told its own request was bad

The first real `make smoke` on a Mac (kind, Docker 29.1.3, Apple Silicon)
passed the self-hosted half: a real completion from Qwen2.5-0.5B through the
gateway in 253 ms. The fallback half returned **HTTP 400** with
`{"backend":"anthropic","reason":"upstream_4xx"}`. Two things pointed away from
the obvious suspects: the API key had just worked in a direct `curl` with the
same model, and a bad key returns 401, not 400. The one difference between that
`curl` and the gateway's request was `temperature`. Repeating the `curl` with
`"temperature":0.2` reproduced it: `invalid_request_error: "`temperature` is
deprecated for this model."` The provider adapter had been written to the
long-standing shape of the Messages API, and the default fallback model
(`claude-haiku-5-5`) no longer accepts that field. Unit tests couldn't catch
this: they mock the API, and the mock accepted whatever it was sent.

The incident also exposed two gaps in the gateway itself. **(a)** It recorded
only the short reason `upstream_4xx`; Anthropic's actual message, which named
the problem exactly, was thrown away, so diagnosis needed a manual `curl`.
**(b)** It passed the fallback's 400 through to the client, telling a caller
whose request was perfectly valid that it had sent a bad request. Fixes:
`temperature` is no longer sent to the Claude API unless
`ANTHROPIC_SEND_TEMPERATURE=true`; every backend failure is logged with its
full upstream message, status and elapsed time; and only the *first* backend's
4xx is passed through as a client error, while a 4xx from the fallback after a
primary failure becomes a 502. Regression tests cover all three. Reproduced
before and after against a fake API that rejects `temperature` the same way:
the old code returned 400, the fixed code returns 200 from the fallback.

## 3. With the model scaled to zero, the gateway waited for the full 30-second timeout instead of failing over at once

The same smoke run showed the self-hosted failure as `timeout`, not the
expected `connect_error`. A Service whose only pod is gone *should* refuse
connections quickly, but this request hung until the 30-second limit. The
likely cause is the gap between `kubectl wait --for=delete` returning and the
cluster's routing catching up: for a moment the Service still points at the
deleted pod's IP, and packets to an IP with nothing behind it are dropped
silently rather than refused, so the connection attempt just hangs. **Confirmed
on the Mac after the fix:** the rerun failed with `connect_timeout` after
exactly 2.00 s, meaning the TCP connection was never established and never
refused. That is the silent-drop behavior, not a slow model. (Whether the
drop comes from a stale endpoint or from the empty Service itself wasn't
isolated; the fix doesn't depend on which.)
Whatever the exact trigger, the design flaw is the same: **one
30-second timeout covered both "never connected" and "connected, still
generating."** Generation can legitimately take 30 s on a CPU model; failing to
open a TCP connection should be known in about 2 s. Fixed by giving each backend
a separate connect timeout (2 s self-hosted, 5 s Claude API) and a separate
`connect_timeout` failure reason. Reproduced in a sandbox with a listener whose
accept queue is full (Linux then drops new SYNs, the same symptom): the old code
took 5.0 s (with a 5 s timeout) and failed, the fixed code fell back and
answered in 2.0 s. On the Mac, the fixed gateway answered from the fallback in
3.08 s end to end (2.00 s connect timeout + 1.07 s Claude API), where the
first run had waited ~30 s and then failed. Evidence:
[`docs/evidence/phase-0.md`](evidence/phase-0.md).

## 4. GitHub sent an immutable OIDC subject; the AWS trust policy expected the name-based one

The first real `terraform plan` from a pull request never reached Terraform.
`aws-actions/configure-aws-credentials` retried for 30 seconds, then failed:
`Could not assume role with OIDC: Not authorized to perform
sts:AssumeRoleWithWebIdentity`. This failure was predicted in
`docs/BUILD_PLAN.md` ("OIDC trust-policy `sub` claim mismatch, the same class
of bug as the Azure `AADSTS700213` incident"). The prediction was right about
the category and wrong about the cause: no typo this time.

Rather than guess, I compared the two sides. The role's trust policy
(`aws iam get-role`) expected exactly
`repo:sugarhillconsultants/self-hosted-llm-platform:pull_request`. CloudTrail
records rejected web-identity calls, and `aws cloudtrail lookup-events
--lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity`
showed five `AccessDenied` attempts presenting
`repo:sugarhillconsultants@12613063/self-hosted-llm-platform@142…:pull_request`.
The repository's OIDC settings (`gh api repos/…/actions/oidc/customization/sub`)
explained the difference: `"use_immutable_subject": true`. GitHub now embeds
the owner's and repository's numeric IDs in the subject, and the
long-documented `repo:owner/repo` pattern, which my module was written to,
no longer matches.

The fix keeps the immutable format rather than switching it off, because it
is the stronger one. A name-based subject would let anyone who later creates
a repository with the same name, after a rename or deletion, assume these
roles; numeric IDs are never reused. The `github-oidc` module now takes the
exact `subject_prefix` from GitHub's API instead of building one from the
repository name, validates its shape, and exposes the subjects each role
trusts as an output. Three mocked `terraform test` cases now run in CI. **The
lesson that transferred from multi-cloud-mlops-showcase** was the diagnosis,
not the fix: compare what the identity provider actually sent with what the
trust policy expects, from logs on both sides, before changing anything.

## 5. The SSO role's access entry was rejected as an "invalid principal" because I had stripped its IAM path

The first manual `apply` from CI created most of the 56 planned resources
(VPC, NAT gateway, EKS control plane, node group) and then failed on one:
`CreateAccessEntry ... InvalidParameterException: The specified principalArn
is invalid: invalid principal`, for
`arn:aws:iam::…:role/AWSReservedSSO_AdministratorAccess_…`. That ARN was built
by my `cluster-admins` module, which deliberately removed the role's
`/aws-reserved/sso.amazonaws.com/` path, on the stated belief that "EKS access
entries take a role ARN without its IAM path."

That belief came from the older way of granting cluster access. AWS's own
troubleshooting guidance for the `aws-auth` ConfigMap says to remove
`/aws-reserved/sso.amazonaws.com/` from SSO role ARNs, because ConfigMap
entries can't include a path. Access entries, the newer API this cluster uses
(`authentication_mode = "API"`), work the other way. The [EKS user guide](https://docs.aws.amazon.com/eks/latest/userguide/creating-access-entries.html)
says an access entry names an *existing* IAM principal, and that a role ARN
there can include a path. Without the path, the ARN names a role that doesn't
exist, so EKS rejects it.

**Why the tests didn't catch it:** the `cluster-admins` module had five
passing `terraform test` cases, and one of them asserted that the path was
removed. The tests faithfully checked the wrong rule. Mocked tests verify
logic against my understanding of an API, not against the API, and the PR
plan couldn't catch it either, since EKS only validates the principal at
creation. The fix uses the ARNs exactly as IAM returns them
(`data.aws_iam_roles.sso_admin.arns`) and never rebuilds an ARN from a name.
The module now validates that its inputs are full role ARNs, and the test
that encoded the wrong rule now asserts the right one. The half-built
environment was destroyed 23 minutes after the failure (about 41 minutes
of running time, roughly $0.16).

## 6. The cost check reported "nothing billable" when it hadn't checked anything

After destroying the half-built environment from incident #5, `make running`
printed `ok EKS clusters: none` and five more `none`s, then `Nothing billable
by the hour in us-east-1.` Every one of those lines was false comfort. Directly
above each `ok` line, the AWS CLI had printed `Error when retrieving token from
sso: Token has expired and refresh failed`. The SSO session had expired, every
API call failed, and `whats-running.sh` treated a failed call's empty output
exactly like an empty result.

The script was written as the safety net for ADR 0008 ("forgetting to destroy
is still possible; mitigations: … `make running`"), so this was the worst
possible failure: a false all-clear from the tool whose only job is to say
whether money is being spent. It was caught only because the user pasted the
full output, not just the last line. The bug class is old and general:
**a check that cannot distinguish "found nothing" from "couldn't look" will
eventually report the second as the first.**

The script now verifies credentials before anything else and exits 2 with
the login command if they don't work. It checks each call's exit status, so a
failed check prints `?? CHECK FAILED` with the error, never `ok … none`. It
exits 0 only when every check actually ran, and says `Verified:`. Exit codes
are 0 (verified clean), 1 (billable resources found) and 2 (could not
verify). All four paths (expired token, clean, resources running, one check
denied) were exercised against a stubbed `aws` command.

## 7. The Karpenter controller's IAM policy was too long for IAM

The first Phase 2 apply stopped partway with `LimitExceeded: Cannot exceed
quota for PolicySize: 6144`, creating `module.karpenter.aws_iam_policy.controller`.
The VPC, NAT gateway and EKS cluster had already been created, so the
environment was destroyed straight away and the fix shipped through a PR.

IAM caps a managed policy at 6,144 characters (whitespace excluded). The
Karpenter sub-module's controller policy refers to the cluster name, the node
role and the interruption queue about 17 times, and this project's naming
(`self-hosted-llm-platform-demo-karpenter-node` and so on) is long enough to
push it over. Nothing before apply could see this: `validate` and `plan` don't
check policy size, and IAM enforces it only at creation. The module's own
variable documentation names this exact error and the remedy,
`enable_inline_policy = true`, which attaches the same statements as an inline
role policy, whose limit is 10,240 characters.

**Tradeoff accepted:** an inline policy can't be reused or attached elsewhere,
which doesn't matter for a role that exists only for this controller.
Shortening every name would have kept a managed policy but touched the
cluster, roles, scripts and manifests for no other benefit. **What
transferred:** the pattern from incident #5. A cloud API's validation is the
only test of some rules, so a first apply in a disposable environment is part
of the test plan, and the teardown has to be ready before it.

## 8. Kubernetes named an environment variable after the Service, and vLLM read it as its own setting

The first Phase 2 smoke test got further than any earlier attempt: Karpenter
launched a `g6.xlarge` from zero in 4 minutes, the 10 GB vLLM image pulled in
2 m 48 s, and then the pod never became ready. `vllm-smoke.sh` waited its full
30 minutes. The pod log's last 20 lines showed only `RuntimeError: Engine core
initialization failed. See root cause above`, with the cause cut off above the
tail.

The full log (`kubectl logs --previous`) showed that every part I had been
worried about worked. The weights loaded in 36.6 s (14.29 GiB), 4.31 GiB was
left for KV cache, and CUDA graphs captured, which also settled the open
question from ADR 0003: the AMI's driver runs vLLM's CUDA 13 build. Then, at
the very end of startup:
`ValueError: VLLM_PORT 'tcp://172.20.253.250:8000' appears to be a URI. This may
be caused by a Kubernetes service discovery issue`. Kubernetes injects
Docker-link-style variables for every Service in a pod's namespace,
`<NAME>_PORT=tcp://<cluster-ip>:<port>` among them. I had named the Service
`vllm`, so every pod got `VLLM_PORT`, which is also the name of one of vLLM's
own configuration variables. The pod crashed 8 times, about 2 minutes each.

Fixed with `enableServiceLinks: false` on the vLLM pod, which turns the
injected variables off; services are reached by DNS name. Renaming the
Service would also have worked, but would leave the same trap for any future
Service whose name collides with an application's settings. Two changes
came out of the same run. `vllm-smoke.sh` now stops at the second crash and
prints the error lines instead of waiting out the timeout with a GPU billing.
And the vLLM pod is annotated `karpenter.sh/do-not-disrupt`: Karpenter had been
trying every 5 minutes to replace the On-Demand GPU node with a cheaper Spot
one ("savings: $0.28"). Each attempt failed with `UnfulfillableCapacity`
because no `g6.xlarge` Spot capacity was available, but had one succeeded it
would have evicted vLLM mid-startup and thrown away the cold start.

## 9. A leaked VPC CNI network interface held a subnet and a security group, and the destroy failed after 35 minutes

After the incident #8 session, the destroy workflow's cleanup step succeeded
(no Karpenter nodes left), then `terraform destroy` ran for 35 minutes and
failed on two resources: `DeleteSecurityGroup ... DependencyViolation: resource
sg-… has a dependent object` and `DeleteSubnet ... has dependencies and cannot
be deleted`. `make running` confirmed nothing billable remained (cluster, NAT
gateway and instances were all gone), so the failure cost time, not money.

Listing the network interfaces in that subnet and security group found
exactly one: `eni-08e3a2e1bc1c42a18`, status `available`, description
`aws-K8S-i-01353f90111fa957b`. That description is the Amazon VPC CNI's: it
creates extra interfaces on each node to give pods VPC IP addresses, names them
after the instance, and normally deletes them itself. When a node terminates
before the CNI can clean up, the interface detaches and stays behind, owned
by no instance and unknown to Terraform, still occupying the subnet and still
a member of the node security group. Terraform retried the deletions until
its timeout. Deleting the interface by hand let a second destroy finish in
42 seconds.

**The fix makes the destroy order explicit** (`scripts/destroy-demo.sh`, used
by both `make down` and the workflow): first destroy only the cluster and
its nodes (`-target=module.eks -target=module.karpenter`); then wait for any
`aws-K8S-*` interfaces in the project's VPC to detach and delete them; then
destroy everything else. Waiting for the nodes to be gone before deleting
the network is what removes the race, whichever node (a Karpenter GPU node
or a system node) leaked the interface. The script stops with an error, rather
than carrying on, if it can't look up the VPC or the interfaces (the incident
#6 rule). Tested against stubs for a leaked interface, one still detaching, a
VPC already gone, and a failing AWS call.

---

## After all fixes: a genuine, verified end-to-end pass

```
<paste the real final run: terraform apply, kubectl get pods -o wide,
 self-hosted completion, fallback under fault injection, quota 429,
 KEDA 0→N→0, eval gate blocking a bad PR, dashboard numbers>
```

<One paragraph stating, claim by claim, what is genuinely verified — and any
caveat attached to each, linking the incident that explains it.>

## The throughline

<How this project's failure categories differ from the Azure projects:
infrastructure-as-code on a new cloud, GPU scheduling and cold starts,
autoscaling signals, LLM evaluation reliability, cost accounting. Which
lessons transferred from earlier projects, which didn't, and which
predictions in docs/BUILD_PLAN.md turned out right vs. which failures were
genuinely new.>
