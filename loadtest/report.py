"""Turn a Phase 3 run (recorder CSV + per-request CSV) into the evidence tables.

    python loadtest/report.py RUN-watch.csv RUN-requests.csv

Prints: the scaling timeline (0 -> 1 -> 2 -> 0) with seconds from the first
request; what users saw minute by minute (who answered, latency); vLLM CPU at
each demand level (is CPU a usable scaling signal?); and the scale-down
broken into its stages. Standard library only.
"""

from __future__ import annotations

import csv
import sys
import time
from statistics import mean, median


def load(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def utc(epoch):
    return time.strftime("%H:%M:%SZ", time.gmtime(epoch))


def val(r, key):
    """A recorder value, or None if that sample failed (blank cell).

    A failed curl or kubectl leaves the cell empty. Reading it as 0 made
    "demand back to 0" fire on a port-forward blip (54 s instead of ~120 s
    in the wait-policy run), so blanks never satisfy a milestone.
    """
    v = (r.get(key) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def is_(r, key, test):
    v = val(r, key)
    return v is not None and test(v)


def first(rows, pred, after=0.0):
    for r in rows:
        if num(r["epoch"]) >= after and pred(r):
            return num(r["epoch"])
    return None


def main(watch_path, req_path):
    w = load(watch_path)
    reqs = load(req_path)
    if not w or not reqs:
        sys.exit("empty input")
    t0 = num(reqs[0]["t_start"])
    t_last_req = max(num(r["t_start"]) + num(r["client_s"]) for r in reqs)
    sh = [r for r in reqs if r.get("served_by") == "self_hosted"]
    t_first_sh = num(sh[0]["t_start"]) + num(sh[0]["client_s"]) if sh else None

    def desired(r, test):
        v = val(r, "hpa_desired")
        if v is None:
            v = val(r, "vllm_spec")
        return v is not None and test(v)

    m = {}
    m["first request"] = t0
    m["demand > 0"] = first(w, lambda r: is_(r, "demand", lambda v: v > 0), t0 - 10)
    m["KEDA wants 1 replica"] = first(w, lambda r: desired(r, lambda v: v >= 1), t0 - 10)
    m["GPU NodeClaim 1 created"] = first(w, lambda r: is_(r, "gpu_nodeclaims", lambda v: v >= 1), t0 - 10)
    m["GPU node 1 Ready"] = first(w, lambda r: is_(r, "gpu_nodes_ready", lambda v: v >= 1), t0 - 10)
    m["vLLM replica 1 Ready"] = first(w, lambda r: is_(r, "vllm_ready", lambda v: v >= 1), t0 - 10)
    m["first self-hosted answer"] = t_first_sh
    m["KEDA wants 2 replicas"] = first(w, lambda r: desired(r, lambda v: v >= 2), t0)
    m["GPU node 2 Ready"] = first(w, lambda r: is_(r, "gpu_nodes_ready", lambda v: v >= 2), t0)
    m["vLLM replica 2 Ready"] = first(w, lambda r: is_(r, "vllm_ready", lambda v: v >= 2), t0)
    m["last request finished"] = t_last_req
    m["demand back to 0"] = first(w, lambda r: is_(r, "demand", lambda v: v == 0), t_last_req)
    m["KEDA wants 0 replicas"] = first(w, lambda r: desired(r, lambda v: v == 0), t_last_req)
    # Only after KEDA asked for zero: the earlier 2 -> 1 step also deletes a NodeClaim.
    t_zero = m["KEDA wants 0 replicas"] or t_last_req
    m["GPU NodeClaim deleting"] = first(w, lambda r: is_(r, "gpu_nodeclaims_deleting", lambda v: v > 0), t_zero)
    m["GPU NodeClaims gone"] = first(w, lambda r: is_(r, "gpu_nodeclaims", lambda v: v == 0), t_zero)

    print("== Scaling timeline (recorder samples every 10 s, so +/-10 s)")
    for name, t in m.items():
        print(f"  {name:28} {'—' if t is None else f'{utc(t)}  +{t - t0:6.0f}s'}")

    if t_first_sh:
        print(f"\n== User-visible cold start: {t_first_sh - t0:.0f}s from the first request to the first "
              "self-hosted answer")

    print("\n== What users saw, per minute")
    print("  minute  reqs  self_hosted  claude  errors  p50_s  p95_s")
    buckets = {}
    for r in reqs:
        buckets.setdefault(int((num(r["t_start"]) - t0) // 60), []).append(r)
    for k in sorted(buckets):
        rs = buckets[k]
        ok = [r for r in rs if r.get("status") == "200"]
        lat = sorted(num(r["client_s"]) for r in ok)
        p95 = lat[min(len(lat) - 1, int(0.95 * (len(lat) - 1)))] if lat else float("nan")
        print(f"  {k:6} {len(rs):5} {sum(r['served_by'] == 'self_hosted' for r in ok):12} "
              f"{sum(r['served_by'] == 'anthropic' for r in ok):7} {len(rs) - len(ok):7} "
              f"{median(lat) if lat else float('nan'):6.2f} {p95:6.2f}")

    print("\n== vLLM CPU vs demand (samples with vLLM Ready; is CPU a usable signal?)")
    by_demand = {}
    for r in w:
        if is_(r, "vllm_ready", lambda v: v >= 1) and val(r, "vllm_cpu_m") is not None \
                and val(r, "demand") is not None:
            by_demand.setdefault(int(num(r["demand"])), []).append(num(r["vllm_cpu_m"]) / max(1, num(r["vllm_ready"])))
    if by_demand:
        print("  demand  samples  CPU per replica (millicores): mean  min  max")
        for d in sorted(by_demand):
            v = by_demand[d]
            print(f"  {d:6} {len(v):8}  {mean(v):26.0f} {min(v):4.0f} {max(v):4.0f}")
    else:
        print("  no CPU samples (is metrics-server installed?)")

    blanks = sum(1 for r in w if val(r, "demand") is None)
    if blanks:
        print(f"\n  ({blanks} recorder samples had no demand reading and were skipped)")

    print("\n== Scale-down, stage by stage")
    stages = [
        ("last request -> demand 0 (gateway window)", "last request finished", "demand back to 0"),
        ("demand 0 -> KEDA wants 0 (cooldown)", "demand back to 0", "KEDA wants 0 replicas"),
        ("KEDA wants 0 -> NodeClaim deleting (Karpenter)", "KEDA wants 0 replicas", "GPU NodeClaim deleting"),
        ("NodeClaim deleting -> gone (drain + terminate)", "GPU NodeClaim deleting", "GPU NodeClaims gone"),
        ("total: last request -> no GPU", "last request finished", "GPU NodeClaims gone"),
    ]
    for label, a, b in stages:
        ta, tb = m.get(a), m.get(b)
        print(f"  {label:48} {'—' if not (ta and tb) else f'{tb - ta:6.0f}s'}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
