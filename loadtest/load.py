"""Staged closed-loop load against the gateway; one CSV row per request.

    python loadtest/load.py --profile 60:0,600:4,480:8,900:0 --out run.csv

A profile is duration_s:concurrency stages. Each of `concurrency` workers
sends a request, waits for the answer, thinks for --think seconds, repeats.
Stages at 0 send nothing (used to watch scale-to-zero). Credentials come from
local/.env.eks (written by scripts/deploy-gateway.sh).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import random
import sys
import time
from pathlib import Path

import httpx

PROMPTS = [
    "In two sentences, what does a Kubernetes readiness probe do?",
    "Explain what a NAT gateway is for, in plain words.",
    "What is the difference between a process and a thread?",
    "Give three tips for writing a clear commit message.",
    "What does an HTTP 429 status mean and how should a client react?",
    "Summarise what continuous batching does for LLM inference.",
]

FIELDS = ["t_start", "stage", "concurrency", "worker", "status", "client_s",
          "served_by", "fallback_reason", "latency_ms", "total_latency_ms",
          "output_tokens", "error"]


def parse_profile(text: str) -> list[tuple[int, int]]:
    stages = []
    for part in text.split(","):
        dur, conc = part.split(":")
        stages.append((int(dur), int(conc)))
    if not stages or any(d <= 0 or c < 0 for d, c in stages):
        raise ValueError("profile must be duration:concurrency pairs, duration > 0")
    return stages


def read_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


class Load:
    def __init__(self, args, creds):
        self.args = args
        self.creds = creds
        self.stage = 0
        self.concurrency = 0
        self.stopped = False
        self.rows: list[dict] = []
        self.token = ""
        self.client = httpx.AsyncClient(base_url=args.url, timeout=httpx.Timeout(args.timeout))

    async def login(self):
        r = await self.client.post("/token", json={
            "client_id": self.creds["CLIENT_ID"], "client_secret": self.creds["CLIENT_SECRET"]})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    async def worker(self, i: int, writer, fh):
        while not self.stopped:
            if i >= self.concurrency:
                await asyncio.sleep(0.25)
                continue
            stage, conc = self.stage, self.concurrency
            body = {"messages": [{"role": "user", "content": random.choice(PROMPTS)}],
                    "max_tokens": self.args.max_tokens}
            t0 = time.time()
            row = {"t_start": f"{t0:.3f}", "stage": stage, "concurrency": conc, "worker": i}
            try:
                r = await self.client.post("/v1/chat", json=body,
                                           headers={"authorization": f"Bearer {self.token}"})
                row["status"] = r.status_code
                if r.status_code == 401:
                    await self.login()
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                row.update(served_by=data.get("served_by", ""), fallback_reason=data.get("fallback_reason") or "",
                           latency_ms=data.get("latency_ms", ""), total_latency_ms=data.get("total_latency_ms", ""),
                           output_tokens=(data.get("usage") or {}).get("output_tokens", ""))
                if r.status_code != 200:
                    row["error"] = str(data.get("errors") or data.get("detail") or r.text[:120])
            except httpx.HTTPError as exc:
                row.update(status="", error=type(exc).__name__)
            row["client_s"] = f"{time.time() - t0:.3f}"
            self.rows.append(row)
            writer.writerow(row)
            fh.flush()
            await asyncio.sleep(self.args.think)

    async def run(self, stages):
        await self.login()
        max_c = max(c for _, c in stages)
        out = Path(self.args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            workers = [asyncio.create_task(self.worker(i, writer, fh)) for i in range(max_c)]
            t_begin = time.time()
            for n, (dur, conc) in enumerate(stages):
                self.stage, self.concurrency = n, conc
                print(f"[{time.strftime('%H:%M:%S')} +{time.time() - t_begin:5.0f}s] "
                      f"stage {n}: {conc} concurrent for {dur}s", flush=True)
                await asyncio.sleep(dur)
            self.stopped = True
            self.concurrency = 0
            await asyncio.gather(*workers)
        await self.client.aclose()


def pct(values, p):
    if not values:
        return float("nan")
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def summarize(rows, stages):
    print("\nstage conc  reqs  ok  self_hosted  claude  errors  p50_s  p95_s  max_s")
    for n, (_, conc) in enumerate(stages):
        rs = [r for r in rows if r["stage"] == n]
        if not rs:
            print(f"{n:5} {conc:4}     0")
            continue
        ok = [r for r in rs if r.get("status") == 200]
        lat = [float(r["client_s"]) for r in ok]
        sh = sum(1 for r in ok if r["served_by"] == "self_hosted")
        cl = sum(1 for r in ok if r["served_by"] == "anthropic")
        print(f"{n:5} {conc:4} {len(rs):5} {len(ok):3} {sh:12} {cl:7} {len(rs) - len(ok):7} "
              f"{pct(lat, 50):6.2f} {pct(lat, 95):6.2f} {max(lat) if lat else float('nan'):6.2f}")
    first_sh = next((r for r in rows if r.get("served_by") == "self_hosted"), None)
    if first_sh and rows:
        print(f"\nfirst self-hosted answer: {float(first_sh['t_start']) - float(rows[0]['t_start']):.0f}s "
              "after the first request")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:18080")
    p.add_argument("--profile", default="60:0,600:4,480:8,900:0")
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--think", type=float, default=2.0, help="seconds between a worker's requests")
    p.add_argument("--timeout", type=float, default=900.0, help="per request (wait policy can be long)")
    p.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / "local" / ".env.eks"))
    p.add_argument("--out", default=f"loadtest/results/{time.strftime('%Y%m%dT%H%M%S')}-requests.csv")
    args = p.parse_args(argv)
    stages = parse_profile(args.profile)
    load = Load(args, read_env(Path(args.env_file)))
    try:
        asyncio.run(load.run(stages))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
    summarize(load.rows, stages)
    print(f"\nper-request CSV: {args.out}")


if __name__ == "__main__":
    main()
