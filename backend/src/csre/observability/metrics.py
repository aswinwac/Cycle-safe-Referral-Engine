from prometheus_client import Counter, Histogram

REFERRALS_TOTAL = Counter(
    "csre_referrals_total",
    "Total referrals handled by the platform.",
    labelnames=["status"],
)

CYCLE_DETECTIONS_TOTAL = Counter(
    "csre_cycle_detections_total",
    "Total cycle detection events.",
)

API_LATENCY_SECONDS = Histogram(
    "csre_api_latency_seconds",
    "API latency by endpoint and method.",
    labelnames=["endpoint", "method"],
)

