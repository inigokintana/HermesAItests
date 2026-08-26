#!/usr/bin/env python3
"""Fabric Pipeline Monitor & Auto-Rerun.

Checks whether a Microsoft Fabric Data Pipeline in a given workspace succeeded,
and if it failed, relaunches it (reporting the failed activity so the "missing
part" can be targeted).

See README.md for the full plan and API reference.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Optional

import msal
import requests
from dotenv import load_dotenv

FABRIC_API = "https://api.fabric.microsoft.com/v1"
# SPN (client credentials) uses the ".default" scope, which resolves to the
# app registration's pre-configured + admin-consented permissions.
SPN_SCOPES = ["https://api.fabric.microsoft.com/.default"]
# Device-code (public client) must request the explicit delegated scopes,
# because ".default" only resolves to the app registration's static
# permissions and often yields a token with no Fabric scopes at all
# (-> HTTP 403 "InsufficientScopes").
DELEGATED_SCOPES = [
    "https://api.fabric.microsoft.com/Item.ReadWrite.All",
    "https://api.fabric.microsoft.com/Workspace.ReadWrite.All",
]

# Statuses that mean "still running" (we should keep polling).
IN_PROGRESS_STATUSES = {"InProgress", "NotStarted", "Queued", "Running"}


class FabricError(Exception):
    """Raised for configuration, auth, or API errors."""


class FabricClient:
    """Thin wrapper around the Fabric REST API with token caching."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise FabricError(
                f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:500]}"
            )
        if not resp.content:
            return None
        return resp.json()

    # --- items ---
    def list_items(self, workspace_id: str) -> list[dict]:
        data = self._request(
            "GET", f"{FABRIC_API}/workspaces/{workspace_id}/items"
        )
        return data.get("value", []) if data else []

    def find_pipeline(self, workspace_id: str, name: Optional[str], item_id: Optional[str]) -> dict:
        if item_id:
            return self._request(
                "GET", f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}"
            )
        for item in self.list_items(workspace_id):
            if item.get("type") in ("DataPipeline", "pipeline") and item.get("displayName") == name:
                return item
        raise FabricError(f"Pipeline '{name}' not found in workspace {workspace_id}")

    # --- job instances (runs) ---
    def list_job_instances(self, workspace_id: str, item_id: str) -> list[dict]:
        data = self._request(
            "GET", f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/jobs/instances"
        )
        return data.get("value", []) if data else []

    def get_job_instance(self, workspace_id: str, item_id: str, job_instance_id: str) -> dict:
        return self._request(
            "GET",
            f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/jobs/instances/{job_instance_id}",
        )

    def run_on_demand(self, workspace_id: str, item_id: str, pipeline_name: str) -> dict:
        # NOTE: this is a FULL pipeline run. Fabric's public REST API does NOT
        # expose "rerun from failed activity" (unlike Azure Data Factory's
        # isRecovery / referencePipelineRunId / startFromFailure). So even when
        # we know which activity failed, the only programmatic relaunch is the
        # whole pipeline. If Fabric ever adds a recovery endpoint, add it here
        # (or in a sibling method) — this is the single place to change.
        payload = {
            "executionData": {
                "pipelineName": pipeline_name,
            }
        }
        return self._request(
            "POST",
            f"{FABRIC_API}/workspaces/{workspace_id}/items/{item_id}/jobs/instances?jobType=Pipeline",
            json=payload,
        )

    # --- activity runs (to find the failed part) ---
    def query_activity_runs(self, workspace_id: str, job_id: str) -> list[dict]:
        body = {
            "filters": [],
            "orderBy": [{"orderBy": "ActivityRunStart", "order": "DESC"}],
        }
        data = self._request(
            "POST",
            f"{FABRIC_API}/workspaces/{workspace_id}/datapipelines/pipelineruns/{job_id}/queryactivityruns",
            json=body,
        )
        # The endpoint returns a wrapper object {"value": [...], "continuationToken": ...},
        # not a bare list (despite what some docs examples show).
        if isinstance(data, dict):
            return data.get("value", []) or []
        return data or []


def acquire_token_managed_identity(client_id: Optional[str]) -> str:
    """Acquire a token via Azure Managed Identity (IMDS endpoint).

    Only works when running on Azure infrastructure (VM, Function App, AKS,
    App Service, etc.) with a system- or user-assigned managed identity.
    No client secret is involved — Azure rotates the credential for you.
    Prefer this over SPN whenever the script runs on Azure.
    """
    url = (
        "http://169.254.169.254/metadata/identity/oauth2/token"
        "?api-version=2018-02-01&resource=https://api.fabric.microsoft.com"
    )
    if client_id:  # user-assigned managed identity
        url += f"&client_id={client_id}"
    resp = requests.get(url, headers={"Metadata": "true"}, timeout=10)
    if resp.status_code != 200:
        raise FabricError(
            f"Managed Identity token request failed: HTTP {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json()
    if "access_token" not in data:
        raise FabricError(f"Managed Identity token missing access_token: {data}")
    return data["access_token"]


def acquire_token(
    tenant_id: Optional[str],
    client_id: Optional[str],
    client_secret: Optional[str],
    auth_mode: str,
) -> str:
    """Acquire a token via SPN, device-code, or managed identity."""
    if auth_mode == "mi":
        return acquire_token_managed_identity(client_id)

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    if auth_mode == "spn":
        app = msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=client_secret
        )
        result = app.acquire_token_for_client(scopes=SPN_SCOPES)
    else:  # device-code
        app = msal.PublicClientApplication(client_id, authority=authority)
        flow = app.initiate_device_flow(scopes=DELEGATED_SCOPES)
        if "user_code" not in flow:
            raise FabricError(f"Device flow failed: {flow}")
        print(f"Open {flow['verification_uri']} and enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise FabricError(f"Token acquisition failed: {result.get('error_description', result)}")
    return result["access_token"]


def latest_run(client: FabricClient, workspace_id: str, item_id: str) -> Optional[dict]:
    """Return the most recent job instance, or None if there are no runs."""
    instances = client.list_job_instances(workspace_id, item_id)
    if not instances:
        return None
    # Sort by start time descending; fall back to list order.
    def key(i: dict) -> str:
        return i.get("startTimeUtc") or i.get("createdDateTime") or ""
    return sorted(instances, key=key, reverse=True)[0]


def failed_activities(client: FabricClient, workspace_id: str, job_id: str) -> list[dict]:
    """Return the list of activities whose status is not Succeeded.

    Best-effort: activity-level detail may be empty even for a Failed run
    (the API can return no per-activity records, e.g. for older runs or runs
    that failed before any activity was recorded). An empty result does NOT
    mean nothing failed — it means the detail isn't available. The relaunch
    is always a full pipeline run regardless (see run_on_demand).
    """
    try:
        runs = client.query_activity_runs(workspace_id, job_id)
    except FabricError:
        return []  # activity-level detail is best-effort
    return [r for r in runs if r.get("status") not in ("Succeeded", "Skipped")]


def wait_for_completion(
    client: FabricClient,
    workspace_id: str,
    item_id: str,
    job_instance_id: str,
    timeout: int,
    interval: int,
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        inst = client.get_job_instance(workspace_id, item_id, job_instance_id)
        status = inst.get("status")
        if status not in IN_PROGRESS_STATUSES:
            return inst
        time.sleep(interval)
    raise FabricError(f"Timed out after {timeout}s waiting for run {job_instance_id}")


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Check a Fabric pipeline and relaunch on failure.")
    parser.add_argument("--check-only", action="store_true", help="Only report status, do not relaunch.")
    parser.add_argument("--wait", action="store_true", help="Poll until the relaunched run finishes.")
    parser.add_argument("--timeout", type=int, default=1800, help="Max seconds to wait (default 1800).")
    parser.add_argument("--interval", type=int, default=15, help="Poll interval seconds (default 15).")
    args = parser.parse_args()

    tenant_id = os.getenv("FABRIC_TENANT_ID")
    client_id = os.getenv("FABRIC_CLIENT_ID")
    client_secret = os.getenv("FABRIC_CLIENT_SECRET")
    # Auto-detect the auth mode when FABRIC_AUTH_MODE is unset, preserving the
    # original behaviour: a client secret -> SPN, otherwise device-code.
    # Explicit FABRIC_AUTH_MODE always wins.
    auth_mode = (os.getenv("FABRIC_AUTH_MODE") or "").lower()
    if not auth_mode:
        auth_mode = "spn" if client_secret else "device"
    workspace_id = os.getenv("FABRIC_WORKSPACE_ID")
    pipeline_name = os.getenv("FABRIC_PIPELINE_NAME")
    pipeline_id = os.getenv("FABRIC_PIPELINE_ID")

    if auth_mode not in ("spn", "device", "mi"):
        print(f"Invalid FABRIC_AUTH_MODE '{auth_mode}' (expected spn, device, or mi).", file=sys.stderr)
        return 2

    # Required config depends on the auth mode.
    required = {"FABRIC_WORKSPACE_ID": workspace_id}
    if auth_mode == "spn":
        required.update({
            "FABRIC_TENANT_ID": tenant_id,
            "FABRIC_CLIENT_ID": client_id,
            "FABRIC_CLIENT_SECRET": client_secret,
        })
    elif auth_mode == "device":
        required.update({
            "FABRIC_TENANT_ID": tenant_id,
            "FABRIC_CLIENT_ID": client_id,
        })
    # "mi" needs no tenant/secret; client_id is optional (user-assigned MI only).

    missing = [k for k, v in required.items() if not v]
    if not pipeline_name and not pipeline_id:
        missing.append("FABRIC_PIPELINE_NAME or FABRIC_PIPELINE_ID")
    if missing:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        token = acquire_token(tenant_id, client_id, client_secret, auth_mode)
        client = FabricClient(token)

        pipeline = client.find_pipeline(workspace_id, pipeline_name, pipeline_id)
        item_id = pipeline["id"]
        print(f"Pipeline: {pipeline.get('displayName')} (id={item_id})")

        run = latest_run(client, workspace_id, item_id)
        if run is None:
            print("No previous runs found for this pipeline.")
            return 0

        job_id = run.get("id")
        status = run.get("status")
        print(f"Latest run: id={job_id} status={status} start={run.get('startTimeUtc')}")

        if status == "Completed":
            print("Pipeline succeeded. Nothing to do.")
            return 0

        if status in IN_PROGRESS_STATUSES:
            print(f"Pipeline is still running (status={status}).")
            if args.wait:
                run = wait_for_completion(client, workspace_id, item_id, job_id, args.timeout, args.interval)
                status = run.get("status")
                print(f"Run finished with status={status}")
                return 0 if status == "Completed" else 1
            return 0

        # Failed (or Cancelled / other non-success terminal state).
        print(f"Pipeline failed (status={status}).")
        failed = failed_activities(client, workspace_id, job_id)
        if failed:
            print("Failed activities (the 'missing part'):")
            for a in failed:
                err = a.get("error") or {}
                print(f"  - {a.get('activityName')} [{a.get('activityType')}] "
                      f"status={a.get('status')} error={err.get('message') or err.get('errorCode')}")
        else:
            print("No per-activity detail available for this run (the API returned "
                  "no activity records). The pipeline failed, but the specific failing "
                  "activity cannot be identified via this endpoint.")

        if args.check_only:
            print("--check-only: not relaunching.")
            return 1

        print("Relaunching pipeline (full on-demand run)...")
        client.run_on_demand(workspace_id, item_id, pipeline.get("displayName", pipeline_name or ""))
        print("Relaunch accepted (202).")

        if args.wait:
            # Find the new run and wait for it.
            time.sleep(args.interval)
            new_run = latest_run(client, workspace_id, item_id)
            if new_run and new_run.get("id") != job_id:
                new_run = wait_for_completion(
                    client, workspace_id, item_id, new_run["id"], args.timeout, args.interval
                )
                print(f"Relaunched run finished with status={new_run.get('status')}")
                return 0 if new_run.get("status") == "Completed" else 1
        return 1

    except FabricError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
