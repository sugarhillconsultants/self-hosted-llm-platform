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
