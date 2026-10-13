# Incident Triage Observability: Demo

The author's working proof for the NextWork Project **Observe a Multi-Agent Triage Workflow with OpenTelemetry** (working title). Learners never see this repo unless it is pushed and linked as a Resource.

It starts from the finished code of **Build a Multi-Agent Incident Triage System with LangGraph** (Published v6: `timeout=180`, specialist `recursion_limit=25`) and adds:

- **Traces** in Langfuse Cloud (US region): a `CallbackHandler` on every `start` and `resume`, grouped into one Langfuse session per thread with `langfuse_session_id`.
- **Metrics** in Google Cloud Monitoring: the OpenTelemetry SDK exports OTLP straight to the Telemetry API (`telemetry.googleapis.com`), queried with PromQL.
- **Secret Mission**: a deterministic `root_cause_correct` check (did the synthesis name the planted deploy?) written as a `BOOLEAN` score on the trace that produced the analysis.

## What's in the repo

| Path | What it is |
|---|---|
| `app.py` | The triage workflow from the triage Project, plus telemetry setup, the score, and a flush on exit |
| `specialists.py` | The specialist agents; `run_specialist` now records duration and tool calls |
| `telemetry.py` | Langfuse handler, `MeterProvider` and OTLP exporter (gRPC or HTTP), the 4 instruments, optional GenAI instrumentation |
| `score.py` | The Secret Mission: answer key and `create_score` |
| `status.py` | Read-only status board from the triage Project's Secret Mission (unchanged) |
| `data/` | Fixtures: `INC-2041` (planted cause `d-1042`) and `INC-2042` (planted cause `d-1039`) |
| `tests/` | Offline tests with fake models, an in-memory metric reader, and a fake Langfuse |

## Metrics

| Name | Kind | Attributes | PromQL example |
|---|---|---|---|
| `triage.specialist.duration` | histogram, `s` | `specialist`, `status` | `sum by (specialist) (max_over_time({"triage.specialist.duration_sum"}[1h]))` |
| `triage.specialist.tool_calls` | histogram | `specialist`, `status` | `sum by (specialist) (max_over_time({"triage.specialist.tool_calls_sum"}[1h]))` |
| `triage.model.errors` | counter | `error.type` (`429`, `504`, `ReadTimeout`, ...) | `sum by ("error.type") (max_over_time({"triage.model.errors"}[1h]))` |
| `triage.approvals.pending` | gauge | `team`, `incident_id` | `{"triage.approvals.pending"}` |

Names keep their dots, so PromQL needs braces and quotes. Counters have no `_total` suffix. Each CLI command is a short process, so use a time window (`max_over_time(...[1h])`) rather than an instant query, which only looks back 5 minutes. The `instance` label is the thread ID, so every command on one incident writes the same series.

## Set up

You need a Google Cloud project with billing, a Langfuse Cloud account (Hobby is free), Python 3.12, and Application Default Credentials (`gcloud auth application-default login`, or Cloud Shell).

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com telemetry.googleapis.com monitoring.googleapis.com
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env   # then fill in the project ID and the Langfuse keys
```

## Run

```bash
set -a && . ./.env && set +a
export TRIAGE_METRICS=grpc            # or http; leave unset for no metrics
python3 app.py start --thread obs-001 --alert INC-2041
python3 app.py resume --thread obs-001            # retry after a 429 or timeout
python3 app.py resume --thread obs-001 --team payments --decision approve
python3 app.py resume --thread obs-001 --team platform-data --decision approve
```

To see the score catch a weak run, hold a specialist back: `python3 app.py start --thread obs-005 --alert INC-2041 --skip deploys`. Without the deploy list, the analysis finds the pool symptom but can't name `d-1042`, so it scores `False` (2 of 2 live runs).

Each command prints its Langfuse trace ID. The command that produces the analysis also prints `Score root_cause_correct: True|False`. Set `TRIAGE_GENAI_INSTRUMENT=1` to add the standard `gen_ai.client.*` metrics from `opentelemetry-instrumentation-google-genai` (install it first: `pip install opentelemetry-instrumentation-google-genai==1.2b0`). Its spans are switched off on purpose, because they double every generation in Langfuse.

Runs take 1 to 7 minutes, and Vertex often returns `429 RESOURCE_EXHAUSTED` or times out. Retry with `resume --thread <id>` and no decision.

## Tests

```bash
python3 -m pip install pytest && python3 -m pytest
```

All tests are offline. Tracing is on only when `LANGFUSE_PUBLIC_KEY` is set, and metrics only when `TRIAGE_METRICS` is set.

## Cost

- Model calls: about $0.02 per INC-2041 run with `gemini-3.7-flash` (Langfuse's own cost figures), more when a retry repeats a specialist.
- Metrics: $0.06 per million samples; a learner's runs are well under a cent.
- Langfuse Cloud Hobby: free (50k units a month; each trace, observation, and score is a unit).

## Tear down

```bash
gcloud projects delete YOUR_PROJECT_ID
```

In Langfuse, delete the project (Project Settings > Delete) or at least revoke the API key.
