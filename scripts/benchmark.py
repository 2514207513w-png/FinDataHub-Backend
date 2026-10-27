"""Run repeated authenticated GETs; educational benchmarking only.
Usage:
  python scripts/benchmark.py --token YOUR_TOKEN --code DEMO001 --requests 100
Use stable hardware/config and repeat both cache-enabled and cache-disabled baselines.
"""
import argparse
import statistics
import time
import httpx


def percentile(values, p):
    values = sorted(values)
    rank = (len(values) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--code", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()
    if args.requests <= 0:
        parser.error("--requests must be positive")
    samples = []
    with httpx.Client(timeout=15.0, headers={"Authorization": f"Bearer {args.token}"}) as client:
        for _ in range(args.requests):
            start = time.perf_counter()
            response = client.get(f"{args.url}/api/v1/products/{args.code}")
            response.raise_for_status()
            samples.append((time.perf_counter() - start) * 1000)
    print(f"requests={len(samples)}; mean_ms={statistics.mean(samples):.2f}; P50_ms={percentile(samples,0.5):.2f}; P95_ms={percentile(samples,0.95):.2f}")
    print("Note: sequential client timings, not a concurrency/load test.")


if __name__ == "__main__":
    main()
