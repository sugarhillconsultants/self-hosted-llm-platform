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

## 1. <title>

<narrative>

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
