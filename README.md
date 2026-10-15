# Incident Triage Observability: Demo

The author's working proof for the NextWork Project **Observe a Multi-Agent Triage Workflow with Langfuse**. The repo is public, and the Starter Repo is its `main` branch.

It starts from the finished code of **Build a Multi-Agent Incident Triage System with LangGraph** (Published v6: `timeout=180`, specialist `recursion_limit=25`) and adds:

- **Traces** in Langfuse Cloud (US region): a `CallbackHandler` on every `start` and `resume`, one Langfuse session per thread (`langfuse_session_id`), the owning team as the user (`langfuse_user_id`), tags for the command, alert, and any held-back specialist, and the environment from `LANGFUSE_TRACING_ENVIRONMENT`. Each command prints a link to its trace.
- **Scores**: a deterministic `root_cause_correct` check (did the synthesis name the planted deploy?) written as a `BOOLEAN` score on the trace that produced the analysis. `start --skip deploys` makes it go `False`.
- **Secret Mission, prompt management**: the analyst prompt is served from Langfuse (`triage-analyst`, label `production`). Each analyst generation links to the prompt version it used.

## What's in the repo

| Path | What it is |
|---|---|
| `app.py` | The triage workflow from the triage Project, plus tracing, the score, and a flush on exit |
| `specialists.py` | The specialist agents (unchanged from the Starter Repo) |
| `telemetry.py` | Langfuse handler, session/user/tags, trace links, flush |
| `score.py` | Answer key and `create_score` |
| `prompts.py` | Secret Mission: fetch the analyst prompt from Langfuse; `python3 prompts.py` uploads v1 |
| `status.py` | Read-only status board from the triage Project's Secret Mission (unchanged) |
| `data/` | Fixtures: `INC-2041` (planted cause `d-1042`) and `INC-2042` (planted cause `d-1039`) |
| `tests/` | Offline tests with fake models and a fake Langfuse |

## Set up

You need a Google Cloud project with billing, a Langfuse Cloud account (Hobby is free), Python 3.12, and Application Default Credentials (`gcloud auth application-default login`, or Cloud Shell).

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env   # then fill in the project ID and the Langfuse keys
```

## Run

```bash
set -a && . ./.env && set +a
python3 app.py start --thread obs-001 --alert INC-2041
python3 app.py resume --thread obs-001            # retry after a 429 or timeout
python3 app.py resume --thread obs-001 --team payments --decision approve
python3 app.py resume --thread obs-001 --team platform-data --decision approve
```

To see the score catch a weak run, hold a specialist back: `python3 app.py start --thread obs-005 --alert INC-2041 --skip deploys`. Without the deploy list, the analysis finds the pool symptom but can't name `d-1042`, so it scores `False` (2 of 2 live runs).

Each command prints a link to its Langfuse trace. The command that produces the analysis also prints `Score root_cause_correct: True|False`. Run `python3 prompts.py` once to put the analyst prompt in Langfuse; until then the analyst uses the local copy.

Runs take 1 to 7 minutes, and Vertex often returns `429 RESOURCE_EXHAUSTED` or times out. Retry with `resume --thread <id>` and no decision.

## Tests

```bash
python3 -m pip install pytest && python3 -m pytest
```

All tests are offline. Tracing is on only when `LANGFUSE_PUBLIC_KEY` is set.

## Cost

- Model calls: about $0.02 per INC-2041 run with `gemini-3.7-flash` (Langfuse's own cost figures), more when a retry repeats a specialist.
- Langfuse Cloud Hobby: free (50k units a month; each trace, observation, and score is a unit).

## Tear down

```bash
gcloud projects delete YOUR_PROJECT_ID
```

In Langfuse, delete the project (Project Settings > Delete) or at least revoke the API key.
