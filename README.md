# Fabric Pipeline Monitor & Auto-Rerun

A Python CLI that checks whether a Microsoft Fabric Data Pipeline in a given
workspace succeeded, and if it failed, relaunches it — rerunning only the
missing/failed part where possible.

## Goal

Given a Fabric **workspace** and a **pipeline**, the program must:

1. Authenticate against Microsoft Fabric (Microsoft Entra ID / OAuth2).
2. Locate the pipeline item in the workspace.
3. Fetch the latest pipeline run (job instance) and read its status.
4. Decide success vs. failure.
5. On failure, identify *which activity* failed (the "missing part").
6. Relaunch the pipeline — ideally only the failed part ("rerun from failed
   activity"), otherwise a full on-demand run.

## How it works (Fabric REST API)

Base URL: `https://api.fabric.microsoft.com/v1`

| Step | Endpoint | Method |
|------|----------|--------|
| Auth | MSAL token, scopes `Workspace.ReadWrite.All`, `Item.ReadWrite.All` | — |
| Find pipeline | `/workspaces/{workspaceId}/items` (filter `type=DataPipeline`, match `displayName`) | GET |
| List runs | `/workspaces/{workspaceId}/items/{itemId}/jobs/instances` | GET |
| Get one run | `/workspaces/{workspaceId}/items/{itemId}/jobs/instances/{jobInstanceId}` | GET |
| Relaunch (full) | `/workspaces/{workspaceId}/items/{itemId}/jobs/instances?jobType=Pipeline` | POST |
| Activity runs | `/workspaces/{workspaceId}/datapipelines/pipelineruns/{jobId}/queryactivityruns` | POST |

### `queryactivityruns` response shape (gotcha)

The `queryactivityruns` endpoint returns a **wrapper object**, not a bare
list:

```json
{ "value": [ ...activity runs... ], "continuationToken": null }
```

Some docs examples show a bare JSON array, but the live API wraps the runs in
`value`. The client unwraps `data["value"]` (and tolerates a bare list or
`null` body) before filtering. Note that `value` can be **empty** even for a
`Failed` run — activity-level detail is best-effort and not always available,
so the script reports the pipeline-level `Failed` status and degrades
gracefully rather than crashing.

### Run status values

`Completed`, `Failed`, `InProgress`, `Cancelled`, `NotStarted` (and others may
be added over time). The program treats `Completed` as success and `Failed` as
the trigger for a relaunch.

### "Rerun the missing part only" — important caveat

Fabric's UI has a **"Rerun from failed activity"** button, but the public REST
API does **not** currently expose a documented endpoint for it (unlike Azure
Data Factory, which uses `isRecovery` / `referencePipelineRunId` /
`startFromFailure` on `createRun`).

So the program implements a two-tier strategy:

1. **Detect the failed activity** via `queryactivityruns` (returns per-activity
   `status`, `error`, `activityName`, `activityRunId`).
2. **Relaunch**:
   - Primary: full on-demand run (`POST .../jobs/instances?jobType=Pipeline`).
   - The failed-activity list is reported so a human (or a future API) can
     target just that part. If/when Fabric exposes a recovery endpoint, the
     `run_on_demand()` method is the single place to add it.

### Two limitations to be aware of

1. **No partial rerun via the public API.** Even when the failed activity is
   known, the only programmatic relaunch is a **full pipeline run**. There is
   no "rerun only the failed subpipeline/activity" call in the public REST
   API today. The activity detail is *informational* (tells you *what* failed),
   not a mechanism to *target* a partial rerun.

2. **Activity detail can be empty even for a `Failed` run.** `queryactivityruns`
   may return `{"value": []}` — e.g. for older runs (activity-level data has a
   shorter retention window than the job-instance record) or runs that failed
   before any activity was recorded. An empty list does **not** mean nothing
   failed; it means the detail isn't available. The script reports the
   pipeline-level `Failed` status and degrades gracefully rather than crashing.

## Authentication modes

Three supported modes, chosen by `FABRIC_AUTH_MODE` (`spn` is the default):

- **Managed identity (`mi`)** — **preferred whenever the script runs on Azure**
  (VM, Function App, AKS, App Service, etc.). No client secret to store or
  rotate — Azure manages the credential. Needs no `FABRIC_TENANT_ID` or
  `FABRIC_CLIENT_SECRET`; set `FABRIC_CLIENT_ID` only for a *user-assigned*
  identity (omit for system-assigned). The identity must still be added to the
  workspace as a Contributor.
- **Service principal (`spn`)** — for automation outside Azure. Needs
  `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`. The SPN must
  be added to the workspace as a Contributor and Fabric REST APIs enabled in
  the tenant admin portal.
- **Device code (`device`)** — for local testing. Uses
  `FABRIC_TENANT_ID` + `FABRIC_CLIENT_ID` (a public client app registration)
  and prints a login URL/code.

### Scopes (SPN vs device-code)

The SPN and device-code modes request **different scopes**, and this matters:

| Mode | Scope requested | Why |
|------|-----------------|-----|
| SPN (client credentials) | `https://api.fabric.microsoft.com/.default` | `.default` resolves to the app registration's pre-configured, admin-consented permissions. |
| Device-code (public client) | `Item.ReadWrite.All` + `Workspace.ReadWrite.All` (explicit) | `.default` on a public client resolves to the app registration's *static* permissions, which often lack the Fabric delegated permissions — yielding a token with no Fabric scopes and an HTTP `403 InsufficientScopes`. Requesting the explicit delegated scopes avoids this. |
| Managed identity | `resource=https://api.fabric.microsoft.com` (IMDS) | The IMDS endpoint issues a token for the Fabric resource directly; no scope string is needed. |

If you hit `403 InsufficientScopes` on the device-code path, the app
registration is missing the Fabric delegated permissions; requesting the
explicit scopes (as the script now does) is the fix.

## Configuration

Copy `.env.example` to `.env` and fill in:

```
# Microsoft Fabric / Entra ID
#
# Auth mode: one of "spn" (default), "device", or "mi" (managed identity).
#   spn    -> service principal (client credentials); needs TENANT_ID, CLIENT_ID, CLIENT_SECRET.
#   device -> interactive device-code login; needs TENANT_ID, CLIENT_ID.
#   mi     -> Azure Managed Identity (IMDS); no secret. CLIENT_ID is optional
#             (only for a user-assigned identity; omit for system-assigned).

FABRIC_AUTH_MODE=spn            # spn | device | mi
FABRIC_TENANT_ID=...            # spn, device
FABRIC_CLIENT_ID=...            # spn, device; mi (user-assigned only)
FABRIC_CLIENT_SECRET=...        # spn only
FABRIC_WORKSPACE_ID=...
FABRIC_PIPELINE_NAME=...        # or FABRIC_PIPELINE_ID
```

## Usage

```
# create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# check + auto-rerun
python fabric_pipeline_monitor.py

# check only (no relaunch)
python fabric_pipeline_monitor.py --check-only

# poll until the relaunched run finishes
python fabric_pipeline_monitor.py --wait
```

## Files

- `fabric_pipeline_monitor.py` — the program.
- `requirements.txt` — `requests`, `msal`, `python-dotenv`.
- `.env.example` — config template.
- `.gitignore` — ignores `.env` and `.venv`.

## Exit codes

- `0` — pipeline succeeded (or relaunch accepted and completed).
- `1` — pipeline failed and relaunch was triggered (or check-only found failure).
- `2` — configuration / auth / API error.
