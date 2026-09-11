---
name: fabric-pipeline-monitor
description: "Check & auto-rerun a Microsoft Fabric Data Pipeline via the local fabric_pipeline_monitor.py CLI."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [fabric, azure, pipeline, data, monitoring]
---

# Fabric Pipeline Monitor & Auto-Rerun

Hermes can check whether a Microsoft Fabric Data Pipeline succeeded, and if it
failed, relaunch it. This is done by running the **standalone Python CLI**
`fabric_pipeline_monitor.py` in the project repo, NOT by any Hermes plugin.

## Refs (single source of truth)
- Script: `/home/inigokintana/urai/developer/HermesAItests/fabric_pipeline_monitor.py`
- Details/API notes: `/home/inigokintana/urai/developer/HermesAItests/README.md`
- Config template: `/home/inigokintana/urai/developer/HermesAItests/.env.example`
- Project/system metadata & operating constraints: `/home/inigokintana/urai/developer/HermesAItests/CMDB.md`

## When to use
- The user asks to check whether a Fabric pipeline succeeded.
- The user asks to relaunch/rerun a failed Fabric pipeline.
- The user asks to monitor a pipeline (check-only, or check+rerun).

## Setup (first time)
The repo already has a venv (`.venv`) with `requests`, `msal`, `python-dotenv`.
Activate it and confirm credentials exist before running:

```bash
HOME='Put your home path here'
cd $HOME/$HermesAItests
source .venv/bin/activate
# credentials live in .env (copy .env.example to .env, fill in)
python fabric_pipeline_monitor.py --check-only
```

If `.venv` is missing: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.

## Environment config (in `.env`, NOT in code)
| Var | Required for | Notes |
|---|---|---|
| `FABRIC_AUTH_MODE` | — | optional: `spn` \| `device` \| `mi`. Auto-detected if unset (client_secret → `spn`, else `device`). |
| `FABRIC_TENANT_ID` | spn, device | |
| `FABRIC_CLIENT_ID` | spn, device; mi (user-assigned only) | |
| `FABRIC_CLIENT_SECRET` | spn only | |
| `FABRIC_WORKSPACE_ID` | always | |
| `FABRIC_PIPELINE_NAME` | or | provide name OR `FABRIC_PIPELINE_ID` |

Auth mode notes:
- `mi` — preferred on Azure (VM / Function App / AKS / App Service). No secret. Identity must be Contributor in the workspace.
- `spn` — automation outside Azure. SPN must be Contributor + Fabric REST APIs enabled in tenant admin.
- `device` — local testing only. Prints a login URL/code.

## Usage (run from repo root)
```bash
python fabric_pipeline_monitor.py                     # check + auto-rerun on failure
python fabric_pipeline_monitor.py --check-only        # report only, never relaunch
python fabric_pipeline_monitor.py --wait --timeout 3600 --interval 15  # poll until relaunched run finishes
```
Note: the relaunch is always a **full on-demand pipeline run** — the public
Fabric REST API has no "rerun from failed activity" variant. Activity-level
detail is informational (tells you WHAT failed), not a partial-rerun trigger.

## Exit codes (map these in your reply and in any cron logic)
| Code | Meaning |
|---|---|
| `0` | Pipeline succeeded (or relaunch completed successfully) |
| `1` | Pipeline failed and relaunch was triggered (or check-only found failure) |
| `2` | Config / auth / API error — inspect stderr |

Run it and capture exit code to decide the message, e.g.
```bash
python fabric_pipeline_monitor.py --check-only; echo "exit=$?"
```

## What to report to the user
- Latest run status (`Completed` / `Failed` / `InProgress` / ...).
- If failed: the failed activity name(s) + error, if the API returned them
  (activity detail may be empty for older runs — that does NOT mean nothing
  failed; report the pipeline-level `Failed` and say detail is unavailable).
- Whether a relaunch was triggered/accepted (HTTP 202), or skipped under
  `--check-only`.

## Pitfalls
- **First run should be `--check-only`.** The no-flag default AUTO-RELAUNCHES the
  pipeline on failure (a side-effecting action). Report status first with
  `--check-only`; only relaunch once the user has confirmed.
- **`device` auth blocks silently in the foreground.** When `.env` has no client
  secret, auth mode auto-detects to `device`, which waits for a human to finish
  a browser sign-in. A foreground call with a timeout will hang and return NO
  output (it looks broken). Run it in the background and poll the log; the
  device-code prompt ("Open https://login.microsoft.com/device and enter code:
  XXXX") appears in the streamed output. That human step can never be automated
  away — hand the URL+code to the user and wait.
- **Never hardcode credentials or the workspace/pipeline IDs into this skill,
  SOUL.md, or any config committed to git.** They live in `.env` (gitignored)
  and in CMDB.md / env. Secrets stay out of code and prompt context.
- Exit code `2` means auth/config issue, not a failed pipeline — don't report a
  business failure; instead surface the config error.
- `device` auth is interactive (requires a human at a browser). For cron or
  unattended use, prefer `spn` or `mi`.
- **403 `InsufficientScopes` on the relaunch POST even when GETs work** — reads
  (list/get runs) can succeed while the relaunch
  (`POST .../items/{id}/jobs/instances?jobType=Pipeline`) returns 403
  `InsufficientScopes`. Relaunching a run is governed by **run permission** on
  the pipeline item/workspace (e.g. Contributor role), NOT by the OAuth scopes
  (`Item.ReadWrite.All` + `Workspace.ReadWrite.All`) that authorize reads. Fix:
  grant the identity (user or SPN, by auth mode) a workspace role that allows
  pipeline execution; for SPN also enable Fabric REST APIs in tenant admin.
  This is the same class of issue the README documents for the device-code
  path — a token that reads fine but can't execute.
  matching creds in `.env`).
- For scheduled/unattended monitoring, do NOT run `--wait` in a long-running
  foreground process that will die with the session — prefer a Hermes cron job
  (see cronjob tool) that runs the script and delivers the outcome.
