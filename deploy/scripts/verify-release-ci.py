"""Accept only the latest complete main push CI for the exact release commit."""
import json
import os
import re
import subprocess


REQUIRED_JOBS = {"repository", "server", "admin-web", "miniprogram", "containers"}


def verify_ci(api, repository, revision):
    endpoint = f"repos/{repository}/actions"
    runs = api(
        f"{endpoint}/workflows/ci.yml/runs?event=push&branch=main"
        f"&head_sha={revision}&per_page=100"
    )["workflow_runs"]
    matching = [run for run in runs if run["head_sha"] == revision
                and run["head_branch"] == "main" and run["event"] == "push"]
    if not matching:
        raise ValueError("No main push CI exists for this commit; wait for main CI.")
    run = max(matching, key=lambda item: item["id"])
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("The latest main CI for this commit has not passed.")
    jobs = api(f"{endpoint}/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
    successful = {job["name"] for job in jobs
                  if job["status"] == "completed" and job["conclusion"] == "success"}
    if not REQUIRED_JOBS.issubset(successful):
        raise ValueError("Main CI is missing successful required jobs.")
    return run["id"]


def github_api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


if __name__ == "__main__":
    version = os.environ["GITHUB_REF_NAME"]
    revision = os.environ["GITHUB_SHA"]
    if (os.environ["GITHUB_REF_TYPE"] != "tag"
            or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?", version)
            or not re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise SystemExit("A fixed version tag and exact commit are required.")
    try:
        run_id = verify_ci(github_api, os.environ["GITHUB_REPOSITORY"], revision)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f"Verified main CI run {run_id}: {version} {revision}")
