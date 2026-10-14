# LangGraph Triage Observability: Starter Repo

Starting code for the NextWork Project **Observe a Multi-Agent Triage Workflow with OpenTelemetry**.

This repo is the finished multi-agent incident triage system from the NextWork Project [Build a Multi-Agent Incident Triage System with LangGraph](https://nextwork.ai/projects/99102f24-d8e5-4201-add1-8b6e97e75030), included unchanged. A router picks specialist agents (logs, deploys, metrics), they investigate in parallel, a synthesis step proposes fixes, and each owning team approves its own fix from a separate command. You don't need to have done that Project first: this repo gives you the same starting point either way.

The system works, but from the terminal you can't tell which specialist was slow, what a run cost, or which approvals are still waiting. In this Project you make it observable: traces in Langfuse, one session per incident, and OpenTelemetry metrics in Google Cloud Monitoring, queried with PromQL.

## What's in the repo

| Path | What it is |
|---|---|
| `app.py` | The triage workflow: `start` and `resume` commands, router, parallel specialists, synthesis, per-team approval gates |
| `specialists.py` | The specialist agents and the tools that read `data/` |
| `status.py` | A read-only status board for a thread |
| `requirements.txt` | Pinned packages from the triage Project. You add the Langfuse and OpenTelemetry pins in Step 1 |
| `.env.example` | The Google Cloud project ID and Langfuse keys you fill in during Step 1 |
| `data/alerts.json` | Two alerts to triage: `INC-2041` (checkout errors) and `INC-2042` (search latency) |
| `data/logs.jsonl`, `data/deploys.json`, `data/metrics.json`, `data/services.json` | Logs, recent deploys, metric time series, and the service catalog the specialists read |
| `tests/` | Offline tests with fake models |

The data is made up and small on purpose, so runs are cheap and the answers can be checked.

## Set up (Google Cloud Shell)

You need a Google Cloud project with billing enabled.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com telemetry.googleapis.com monitoring.googleapis.com
git clone https://github.com/nextwork-projects/langgraph-triage-observability.git ~/langgraph-triage-observability
cd ~/langgraph-triage-observability
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

If the first model call returns `403 PERMISSION_DENIED`, the API was enabled only moments ago. Wait a few minutes and try again.

## Check that it runs

```bash
python3 app.py start --thread smoke-001 --alert INC-2042
```

It takes about 2 to 3 minutes. You should see the `Router:` line, each specialist finishing, then `WORKFLOW COMPLETE` and `Runbook: runbooks/smoke-001.md`. The `LangChainBetaWarning` about the v3 streaming protocol is expected. If the run stops on `429 RESOURCE_EXHAUSTED` or a timeout, retry it with `python3 app.py resume --thread smoke-001`.

## Cost

Each triage run makes a few Gemini 3.7 Flash calls, about $0.01 to $0.02. Cloud Shell is free.

## Branches

- `main` is the starting point for the Project. Clone it and follow the Project's steps from here.
- `solution` is the finished build, with offline tests (`python3 -m pip install pytest && python3 -m pytest`). Use it to check your work if you get stuck.
