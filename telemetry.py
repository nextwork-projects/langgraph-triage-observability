"""Traces (Langfuse) and metrics (Google Cloud Monitoring) for the triage workflow.

Tracing turns on when LANGFUSE_PUBLIC_KEY is set. Metrics turn on when
TRIAGE_METRICS is "grpc" or "http". With neither, every helper is a no-op,
so the offline tests run without network access.
"""
import os
import time
from contextlib import contextmanager

from opentelemetry import metrics

SERVICE_NAME = "incident-triage"
TELEMETRY_ENDPOINT = "telemetry.googleapis.com"
METRICS_REGION = "us-central1"
DURATION_BUCKETS = [1, 2, 5, 10, 20, 30, 60, 120, 180, 300, 600]
TOOL_CALL_BUCKETS = [0, 1, 2, 3, 5, 8, 12, 20, 50]

_meter_provider = None
_langfuse = None


def tracing_enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))


def langfuse_client():
    global _langfuse
    if _langfuse is None:
        from langfuse import get_client

        _langfuse = get_client()
    return _langfuse


def trace_config(thread_id: str, command: str) -> tuple[dict, object | None]:
    """Return extra graph config and the Langfuse handler (None when tracing is off)."""
    if not tracing_enabled():
        return {}, None
    from langfuse.langchain import CallbackHandler

    langfuse_client()
    handler = CallbackHandler()
    return {
        "callbacks": [handler],
        "run_name": f"triage {command}",
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_tags": [command],
        },
    }, handler


def _grpc_exporter(project_id: str):
    import google.auth
    import google.auth.transport.grpc
    import google.auth.transport.requests
    import grpc
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    credentials, _ = google.auth.default()
    plugin = google.auth.transport.grpc.AuthMetadataPlugin(
        credentials=credentials, request=google.auth.transport.requests.Request()
    )
    channel = grpc.composite_channel_credentials(
        grpc.ssl_channel_credentials(), grpc.metadata_call_credentials(plugin)
    )
    return OTLPMetricExporter(
        endpoint=f"{TELEMETRY_ENDPOINT}:443",
        credentials=channel,
        headers={"x-goog-user-project": project_id},
    )


def _http_exporter(project_id: str):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    credentials, _ = google.auth.default()
    session = AuthorizedSession(credentials)
    session.headers["x-goog-user-project"] = project_id
    return OTLPMetricExporter(
        endpoint=f"https://{TELEMETRY_ENDPOINT}/v1/metrics", session=session
    )


def setup_metrics(instance_id: str):
    """Send metrics to Cloud Monitoring through the Telemetry API (OTLP).

    instance_id becomes the series' instance label. Using the thread ID makes
    every command on one incident write the same series, so a gauge's latest
    value is the incident's current state.
    """
    global _meter_provider
    mode = os.environ.get("TRIAGE_METRICS", "").lower()
    if mode not in ("grpc", "http") or _meter_provider is not None:
        return
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
    exporter = _grpc_exporter(project_id) if mode == "grpc" else _http_exporter(project_id)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    # The Telemetry API rejects points without a location (cloud.region here).
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "gcp.project_id": project_id,
            "cloud.region": METRICS_REGION,
            "service.instance.id": instance_id,
        }
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_meter_provider)


meter = metrics.get_meter("triage")
specialist_duration = meter.create_histogram(
    "triage.specialist.duration",
    unit="s",
    description="Time one specialist agent takes to return a finding.",
    explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
)
specialist_tool_calls = meter.create_histogram(
    "triage.specialist.tool_calls",
    unit="{call}",
    description="Tool calls one specialist made before answering.",
    explicit_bucket_boundaries_advisory=TOOL_CALL_BUCKETS,
)
model_errors = meter.create_counter(
    "triage.model.errors",
    unit="{error}",
    description="Workflow runs that stopped on a model or agent error.",
)
approvals_pending = meter.create_gauge(
    "triage.approvals.pending",
    unit="{approval}",
    description="Team approvals an incident is waiting on, after each command.",
)


def error_type(error: Exception) -> str:
    text = str(error)
    for code in ("429", "504", "503", "500", "403", "404"):
        if f"{code} " in text or f"({code})" in text or text.startswith(code):
            return code
    return type(error).__name__


@contextmanager
def time_specialist(name: str):
    """Time one specialist and record its tool calls. Yields a dict to fill."""
    outcome = {"tool_calls": 0, "status": "ok"}
    started = time.monotonic()
    try:
        yield outcome
    except Exception as error:
        outcome["status"] = error_type(error)
        raise
    finally:
        attributes = {"specialist": name, "status": outcome["status"]}
        specialist_duration.record(time.monotonic() - started, attributes)
        specialist_tool_calls.record(outcome["tool_calls"], attributes)


def record_pending(incident_id: str, teams: list[str], pending: list[str]):
    for team in teams:
        approvals_pending.set(
            pending.count(team), {"team": team, "incident_id": incident_id}
        )


def instrument_genai():
    """Optional: standard gen_ai.* metrics from the google-genai SDK.

    Its spans are switched off: Langfuse's CallbackHandler already records each
    model call, and keeping both doubles every generation and its cost.
    """
    if os.environ.get("TRIAGE_GENAI_INSTRUMENT") != "1":
        return
    from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
    from opentelemetry.trace import NoOpTracerProvider

    GoogleGenAiSdkInstrumentor().instrument(tracer_provider=NoOpTracerProvider())


def shutdown():
    """Flush traces and metrics before the CLI exits."""
    if _langfuse is not None:
        _langfuse.flush()
    if _meter_provider is not None:
        _meter_provider.shutdown()
