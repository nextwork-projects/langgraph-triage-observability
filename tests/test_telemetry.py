"""Metrics and scores, checked offline with an in-memory metric reader and a fake Langfuse."""
import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import specialists
import telemetry
from score import root_cause_correct, score_run

READER = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[READER]))


def points():
    data = READER.get_metrics_data()
    found = {}
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = list(metric.data.data_points)
    return found


class Message:
    def __init__(self, type):
        self.type = type


class FakeAgent:
    def __init__(self, error=None):
        self.error = error

    def invoke(self, payload, config=None):
        if self.error:
            raise self.error
        messages = [Message("human"), Message("ai"), Message("tool"), Message("tool"), Message("ai")]
        return {"messages": messages, "structured_response": {"summary": "ok"}}


def test_specialist_records_duration_and_tool_calls(monkeypatch):
    monkeypatch.setattr(specialists, "build_specialist", lambda name: FakeAgent())
    specialists.run_specialist("deploys", "brief")
    found = points()
    calls = [p for p in found["triage.specialist.tool_calls"] if p.attributes["specialist"] == "deploys"]
    assert calls[0].sum == 2 and calls[0].attributes["status"] == "ok"
    assert any(p.attributes["specialist"] == "deploys" for p in found["triage.specialist.duration"])


def test_failed_specialist_records_error_status(monkeypatch):
    error = RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted.")
    monkeypatch.setattr(specialists, "build_specialist", lambda name: FakeAgent(error))
    with pytest.raises(RuntimeError):
        specialists.run_specialist("metrics", "brief")
    statuses = {p.attributes["status"] for p in points()["triage.specialist.duration"] if p.attributes["specialist"] == "metrics"}
    assert statuses == {"429"}


def test_error_type_names_status_codes():
    assert telemetry.error_type(RuntimeError("504 DEADLINE_EXCEEDED.")) == "504"
    assert telemetry.error_type(RuntimeError("Error calling model (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED")) == "429"
    assert telemetry.error_type(TimeoutError("timed out")) == "TimeoutError"


def test_pending_gauge_drops_to_zero_after_a_team_decides():
    telemetry.record_pending("inc-1", ["payments", "platform-data"], ["payments", "platform-data"])
    telemetry.record_pending("inc-1", ["payments", "platform-data"], ["platform-data"])
    values = {p.attributes["team"]: p.value for p in points()["triage.approvals.pending"] if p.attributes["incident_id"] == "inc-1"}
    assert values == {"payments": 0, "platform-data": 1}


def test_root_cause_check():
    assert root_cause_correct("INC-2041", {"likely_cause": "Deploy d-1042 cut the pool from 50 to 5."})
    assert not root_cause_correct("INC-2041", {"likely_cause": "orders-db was slow."})
    assert root_cause_correct("INC-2042", {"likely_cause": "d-1039 lowered the cache TTL."})
    assert not root_cause_correct("INC-9999", {"likely_cause": "d-1042"})


def test_score_run_writes_a_boolean_score():
    class FakeLangfuse:
        def create_score(self, **kwargs):
            self.kwargs = kwargs

    langfuse = FakeLangfuse()
    assert score_run(langfuse, "a" * 32, "INC-2041", {"likely_cause": "d-1042"})
    assert langfuse.kwargs["name"] == "root_cause_correct"
    assert langfuse.kwargs["value"] == 1 and langfuse.kwargs["data_type"] == "BOOLEAN"
    assert langfuse.kwargs["trace_id"] == "a" * 32
