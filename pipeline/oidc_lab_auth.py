"""Exchange GitHub-signed OIDC workload identity for scoped Neon LAB access.

The private connection is masked by GitHub and handed ONLY to the current job.
Never include connection details in output, reports, stdout or artifacts.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


OIDC_AUDIENCE = "classroom-neon-lab-v1"
PREVIEW = (
    "https://tiktok-shop-mlops-dashboard-git-feature-classroom-"
    "dea39b-newja.vercel.app/api/lab-oidc"
)


def main():
    request_url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    request_token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    url = request_url + ("&" if "?" in request_url else "?") + urllib.parse.urlencode(
        {"audience": OIDC_AUDIENCE}
    )
    identity_req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + request_token}
    )
    with urllib.request.urlopen(identity_req, timeout=20) as response:
        identity = json.load(response)["value"]
    # The OIDC JWT proves repository, workflow, ref and runner identity.
    exchange_req = urllib.request.Request(
        PREVIEW,
        method="POST",
        headers={"Authorization": "Bearer " + identity,
                 "Content-Type": "application/json"},
        data=b"{}",
    )
    with urllib.request.urlopen(exchange_req, timeout=30) as response:
        result = json.load(response)
    connection = result["database_url"]
    if not (connection.startswith("postgres://classroom_lab_writer:") or
            connection.startswith("postgresql://classroom_lab_writer:")):
        raise RuntimeError("OIDC credential is not scoped to the isolated lab role")
    if "\n" in connection or "\r" in connection:
        raise RuntimeError("Invalid credential encoding")
    # Protect the credential before any other step uses it.
    print("::add-mask::" + connection, flush=True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
        env.write("NEON_DEMO_DATABASE_URL=" + connection + "\n")
    print("Authenticated GitHub Actions to isolated Neon Lab using short-lived OIDC identity")


if __name__ == "__main__":
    main()
