#!/usr/bin/env python3
"""
Patient Management System — AI Issue Fix Agent
-----------------------------------------------
Triggered when a GitHub Issue is labeled 'bug'.

Flow:
  1. Parse issue body to extract affected file + bug description
  2. Fetch file content from GitHub
  3. Ask GPT-4o to generate a targeted fix
  4. Create branch fix/issue-{N}-{slug}
  5. Commit the fix
  6. Raise a PR referencing the issue
  7. Comment on the issue with the PR link

The raised PR is automatically reviewed by the PR Review Agent.

Required env vars:
  GITHUB_TOKEN    — GitHub Actions token
  GH_MODELS_TOKEN — PAT with models:read (GitHub Models API)
  ISSUE_NUMBER    — set by GitHub Actions
  ISSUE_TITLE     — set by GitHub Actions
  ISSUE_BODY      — set by GitHub Actions
  REPO_FULL_NAME  — e.g. "Aishwarya-K-R/Test"
  DEFAULT_BRANCH  — e.g. "main"
"""

import os
import re
import sys
import json
import base64
import requests
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_TOKEN    = os.environ["GITHUB_TOKEN"]
GH_MODELS_TOKEN = os.environ["GH_MODELS_TOKEN"]
ISSUE_NUMBER    = os.environ["ISSUE_NUMBER"]
ISSUE_TITLE     = os.environ["ISSUE_TITLE"]
ISSUE_BODY      = os.environ.get("ISSUE_BODY", "")
REPO_FULL_NAME  = os.environ["REPO_FULL_NAME"]
DEFAULT_BRANCH  = os.environ.get("DEFAULT_BRANCH", "main")

GITHUB_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ─────────────────────────────────────────────────────────────────────────────
# GitHub helpers
# ─────────────────────────────────────────────────────────────────────────────

def gh_get(path: str) -> requests.Response:
    r = requests.get(f"{GITHUB_API}{path}", headers=GH_HEADERS, timeout=30)
    r.raise_for_status()
    return r


def get_file(file_path: str, ref: str) -> tuple[str, str]:
    """Returns (content, blob_sha) for a file at a given ref."""
    r = gh_get(f"/repos/{REPO_FULL_NAME}/contents/{file_path}?ref={ref}")
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def get_branch_sha(branch: str) -> str:
    r = gh_get(f"/repos/{REPO_FULL_NAME}/git/refs/heads/{branch}")
    return r.json()["object"]["sha"]


def create_branch(branch_name: str, sha: str):
    r = requests.post(
        f"{GITHUB_API}/repos/{REPO_FULL_NAME}/git/refs",
        headers=GH_HEADERS,
        json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        timeout=30,
    )
    if r.status_code == 422:
        # Branch already exists — reset to sha
        requests.patch(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/git/refs/heads/{branch_name}",
            headers=GH_HEADERS,
            json={"sha": sha, "force": True},
            timeout=30,
        ).raise_for_status()
    else:
        r.raise_for_status()


def commit_fix(file_path: str, content: str, blob_sha: str, branch: str, message: str):
    r = requests.put(
        f"{GITHUB_API}/repos/{REPO_FULL_NAME}/contents/{file_path}",
        headers=GH_HEADERS,
        json={
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "sha": blob_sha,
            "branch": branch,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def raise_pr(fix_branch: str, file_path: str, fix_summary: str) -> str:
    body = "\n".join([
        f"## 🤖 AI Fix for Issue #{ISSUE_NUMBER}",
        "",
        f"Closes #{ISSUE_NUMBER}",
        "",
        f"**Issue:** {ISSUE_TITLE}",
        "",
        "### What was fixed",
        fix_summary,
        "",
        f"**File changed:** `{file_path}`",
        "",
        "---",
        "> ⚠️ This PR was raised automatically by **PMS AI Fix Agent**.",
        "> The **PR Review Agent** will now analyse this fix — review both before merging.",
        "",
        "*Raised by **PMS AI Fix Agent***",
    ])

    r = requests.post(
        f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls",
        headers=GH_HEADERS,
        json={
            "title": f"[ai-fix] #{ISSUE_NUMBER}: {ISSUE_TITLE}",
            "body": body,
            "head": fix_branch,
            "base": DEFAULT_BRANCH,
        },
        timeout=30,
    )
    if r.status_code == 422:
        # PR already exists
        existing = requests.get(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls",
            headers=GH_HEADERS,
            params={"head": f"{REPO_FULL_NAME.split('/')[0]}:{fix_branch}", "state": "open"},
            timeout=30,
        ).json()
        if existing:
            return existing[0]["html_url"]
        r.raise_for_status()
    else:
        r.raise_for_status()
    return r.json()["html_url"]


def comment_on_issue(pr_url: str, file_path: str):
    body = "\n".join([
        "## 🤖 AI Fix Agent — Fix PR Raised",
        "",
        f"A fix has been automatically generated for this issue.",
        "",
        f"👉 **[View Fix PR]({pr_url})**",
        "",
        f"**File fixed:** `{file_path}`",
        "",
        "The **PR Review Agent** is now analysing the fix.",
        "Please review the PR and the AI review before merging.",
        "",
        "*Raised by **PMS AI Fix Agent***",
    ])
    r = requests.post(
        f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{ISSUE_NUMBER}/comments",
        headers=GH_HEADERS,
        json={"body": body},
        timeout=30,
    )
    r.raise_for_status()

# ─────────────────────────────────────────────────────────────────────────────
# Issue parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_issue_body(body: str) -> dict:
    """
    Extract structured fields from the bug report template.
    Returns: { file, description, expected, actual, context }
    """
    def extract_section(heading: str) -> str:
        pattern = rf"##\s+{heading}\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    # Extract file path from the File section — looks for `path/to/file.cs`
    file_section = extract_section("File")
    file_match = re.search(r"`([^`]+\.[a-zA-Z]+)`", file_section)
    file_path = file_match.group(1).strip() if file_match else None

    return {
        "file":        file_path,
        "description": extract_section("Description"),
        "expected":    extract_section("Expected Behavior"),
        "actual":      extract_section("Actual Behavior"),
        "context":     extract_section("Additional Context"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# AI fix generation
# ─────────────────────────────────────────────────────────────────────────────

FIX_SYSTEM_PROMPT = """
You are an expert .NET 8 senior engineer working on the Patient Management System (PMS).

Architecture: YARP API Gateway → [Auth | Patient | Billing(gRPC) | AI/LLM] services → PostgreSQL + Redis + Kafka
Tech: .NET 8, EF Core 8, Confluent.Kafka, gRPC/Protobuf, StackExchange.Redis, Serilog, xUnit

You will receive:
- A bug report (title, description, expected vs actual behavior)
- The full content of the affected file

Your task:
1. Understand the bug
2. Apply a minimal, targeted fix to the file
3. Do NOT rewrite the entire file — only change what is necessary
4. Return the complete fixed file content

Return ONLY valid JSON, no prose:
{
  "fixed_content": "<complete fixed file content as a string>",
  "summary": "<1-2 sentence explanation of what was changed and why>",
  "confidence": "high|medium|low"
}
"""

def generate_fix(issue: dict, file_content: str) -> dict:
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GH_MODELS_TOKEN,
    )

    user_msg = f"""Fix this bug in the Patient Management System.

## Bug Report
**Title:** {ISSUE_TITLE}
**Description:** {issue['description']}
**Expected:** {issue['expected']}
**Actual:** {issue['actual']}
**Additional context:** {issue['context']}

## File to fix: `{issue['file']}`
```csharp
{file_content[:12000]}
```

Apply a minimal fix and return the complete fixed file content as JSON.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": FIX_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Model response not valid JSON:\n{raw[:400]}")

# ─────────────────────────────────────────────────────────────────────────────
# Slug helper
# ─────────────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:40].strip("-")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n[PMS Issue Fix Agent] Issue #{ISSUE_NUMBER} — {REPO_FULL_NAME}")
    print("=" * 60)
    print(f"  Title : {ISSUE_TITLE}")

    # Parse issue
    issue = parse_issue_body(ISSUE_BODY)
    print(f"  File  : {issue['file'] or 'NOT FOUND in issue body'}")

    if not issue["file"] or issue["file"] == "path/to/file.cs":
        msg = (
            "⚠️ Could not determine which file to fix.\n\n"
            "Please update the issue and fill in the **File** field with the exact file path "
            "(e.g. `Services/PatientService.cs`)."
        )
        requests.post(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{ISSUE_NUMBER}/comments",
            headers=GH_HEADERS,
            json={"body": msg},
            timeout=30,
        )
        print("  No file specified — commented on issue. Exiting.")
        sys.exit(0)

    # Fetch file
    print(f"  Fetching {issue['file']} from {DEFAULT_BRANCH}...")
    try:
        file_content, blob_sha = get_file(issue["file"], DEFAULT_BRANCH)
    except Exception as e:
        print(f"  Error fetching file: {e}")
        requests.post(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{ISSUE_NUMBER}/comments",
            headers=GH_HEADERS,
            json={"body": f"⚠️ Could not fetch `{issue['file']}`: `{e}`\nPlease verify the file path in the issue."},
            timeout=30,
        )
        sys.exit(1)

    # Generate fix
    print("  Generating fix with GPT-4o...")
    result = generate_fix(issue, file_content)
    fixed_content = result.get("fixed_content", "")
    summary       = result.get("summary", "No summary provided.")
    confidence    = result.get("confidence", "unknown")
    print(f"  Confidence : {confidence}")
    print(f"  Summary    : {summary}")

    if not fixed_content or fixed_content.strip() == file_content.strip():
        requests.post(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{ISSUE_NUMBER}/comments",
            headers=GH_HEADERS,
            json={"body": f"ℹ️ AI Fix Agent could not determine a fix for this issue.\n\n**Reason:** {summary}"},
            timeout=30,
        )
        print("  No change produced — commented on issue.")
        sys.exit(0)

    # Create fix branch
    fix_branch = f"fix/issue-{ISSUE_NUMBER}-{slugify(ISSUE_TITLE)}"
    print(f"  Creating branch: {fix_branch}")
    base_sha = get_branch_sha(DEFAULT_BRANCH)
    create_branch(fix_branch, base_sha)

    # Commit fix
    print(f"  Committing fix to {fix_branch}...")
    commit_fix(
        file_path=issue["file"],
        content=fixed_content,
        blob_sha=blob_sha,
        branch=fix_branch,
        message=f"fix: #{ISSUE_NUMBER} — {ISSUE_TITLE}\n\n{summary}",
    )

    # Raise PR
    print("  Raising fix PR...")
    pr_url = raise_pr(fix_branch, issue["file"], summary)
    print(f"  Fix PR: {pr_url}")

    # Comment on issue
    comment_on_issue(pr_url, issue["file"])
    print("  Commented on issue.")

    print("=" * 60)
    print(f"[DONE] Fix PR raised: {pr_url}")
    print("       PR Review Agent will now analyse the fix automatically.")


if __name__ == "__main__":
    main()
