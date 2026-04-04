#!/usr/bin/env python3
"""
Patient Management System — AI Issue Fix Agent
-----------------------------------------------
Triggered when a GitHub Issue is labeled 'bug'.

Flow:
  1. Fetch the repo file tree from GitHub
  2. Ask GPT-4o which file is most likely affected by the issue
  3. Fetch that file's content
  4. Ask GPT-4o to generate a targeted fix
  5. Create branch fix/issue-{N}-{slug}
  6. Commit the fix
  7. Raise a PR referencing the issue (triggers PR Review Agent)
  8. Comment on the issue with the PR link

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
PAT_TOKEN       = os.environ.get("PAT_TOKEN", GITHUB_TOKEN)  # used for trigger commit to fire pull_request events
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

# File extensions the agent can fix
FIXABLE_EXTENSIONS = {".cs", ".py", ".yml", ".yaml", ".json", ".proto"}

# Paths to skip (generated/binary/noise)
SKIP_PREFIXES = ("obj/", "bin/", ".git/", "PMS.Tests/obj/", "PMS.Tests/bin/", "db-data/")

# ─────────────────────────────────────────────────────────────────────────────
# GitHub helpers
# ─────────────────────────────────────────────────────────────────────────────

def gh_get(path: str) -> requests.Response:
    r = requests.get(f"{GITHUB_API}{path}", headers=GH_HEADERS, timeout=30)
    r.raise_for_status()
    return r


def get_repo_file_tree(branch: str) -> list[str]:
    """Fetch all file paths in the repo (filtered to fixable extensions)."""
    r = gh_get(f"/repos/{REPO_FULL_NAME}/git/trees/{branch}?recursive=1")
    tree = r.json().get("tree", [])
    files = []
    for item in tree:
        if item["type"] != "blob":
            continue
        path = item["path"]
        if any(path.startswith(skip) for skip in SKIP_PREFIXES):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext in FIXABLE_EXTENSIONS:
            files.append(path)
    return files


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


def comment_on_issue(message: str):
    requests.post(
        f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{ISSUE_NUMBER}/comments",
        headers=GH_HEADERS,
        json={"body": message},
        timeout=30,
    ).raise_for_status()


def trigger_pr_review(fix_branch: str, pr_number: str, pr_title: str, base_ref: str):
    """Fire a repository_dispatch event to trigger the PR Review Agent workflow."""
    pat_headers = {
        "Authorization": f"Bearer {PAT_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.post(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/dispatches",
            headers=pat_headers,
            json={
                "event_type": "ai-fix-pr-review",
                "client_payload": {
                    "pr_number": pr_number,
                    "pr_title":  pr_title,
                    "head_ref":  fix_branch,
                    "base_ref":  base_ref,
                },
            },
            timeout=30,
        )
        r.raise_for_status()
        print(f"  Triggered PR Review Agent on PR #{pr_number} via repository_dispatch.")
    except Exception as e:
        print(f"  Warning: could not trigger PR Review Agent: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Issue parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_issue_body(body: str) -> dict:
    def extract_section(heading: str) -> str:
        pattern = rf"##\s+{heading}\s*\n(.*?)(?=\n##|\Z)"
        m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    return {
        "description": extract_section("Description"),
        "expected":    extract_section("Expected Behavior"),
        "actual":      extract_section("Actual Behavior"),
        "context":     extract_section("Additional Context"),
        "steps":       extract_section("Steps to Reproduce"),
    }

# ─────────────────────────────────────────────────────────────────────────────
# AI — Step 1: identify affected file
# ─────────────────────────────────────────────────────────────────────────────

FILE_DETECT_PROMPT = """
You are an expert .NET 8 engineer working on the Patient Management System (PMS).

Architecture: YARP API Gateway → [Auth | Patient | Billing(gRPC) | AI/LLM] services → PostgreSQL + Redis + Kafka
Tech: .NET 8, EF Core 8, Confluent.Kafka, gRPC/Protobuf, StackExchange.Redis, Serilog

You will receive a bug report and a list of all files in the repository.

Your task: identify the SINGLE most likely file that contains the bug.

Rules:
- Return the exact file path from the provided list
- Prefer service files (.cs) over config files unless the bug is clearly config-related
- If the bug mentions a specific class, method, or endpoint — map it to the correct file
- If genuinely unsure, pick the most likely candidate

Return ONLY valid JSON, no prose:
{
  "file": "<exact file path from the list>",
  "reasoning": "<1 sentence explaining why this file>"
}
"""

def identify_affected_file(issue: dict, file_tree: list[str]) -> tuple[str, str]:
    """Returns (file_path, reasoning)."""
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GH_MODELS_TOKEN,
    )

    file_list = "\n".join(file_tree)
    user_msg = f"""Bug report for the Patient Management System:

**Title:** {ISSUE_TITLE}
**Description:** {issue['description']}
**Expected:** {issue['expected']}
**Actual:** {issue['actual']}
**Steps to reproduce:** {issue['steps']}
**Additional context:** {issue['context']}

Repository files:
{file_list}

Which single file most likely contains this bug?
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=512,
        messages=[
            {"role": "system", "content": FILE_DETECT_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw = response.choices[0].message.content.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(m.group()) if m else {}

    file_path = data.get("file", "").strip()
    reasoning = data.get("reasoning", "")

    # Validate the returned file is actually in the tree
    if file_path not in file_tree:
        # Try fuzzy match
        for f in file_tree:
            if file_path and (file_path in f or f.endswith(file_path)):
                file_path = f
                break
        else:
            file_path = ""

    return file_path, reasoning

# ─────────────────────────────────────────────────────────────────────────────
# AI — Step 2: generate fix
# ─────────────────────────────────────────────────────────────────────────────

FIX_SYSTEM_PROMPT = """
You are an expert .NET 8 senior engineer working on the Patient Management System (PMS).

Architecture: YARP API Gateway → [Auth | Patient | Billing(gRPC) | AI/LLM] services → PostgreSQL + Redis + Kafka
Tech: .NET 8, EF Core 8, Confluent.Kafka, gRPC/Protobuf, StackExchange.Redis, Serilog, xUnit

You will receive a bug report and the full content of the affected file.

Your task:
1. Understand the bug
2. Apply a minimal, targeted fix — only change what is necessary
3. Do NOT rewrite the entire file

Return your response in this EXACT format with these exact markers — do not use JSON:

SUMMARY: <1-2 sentence explanation of what was changed and why>
CONFIDENCE: high|medium|low
FIXED_FILE_START
<complete fixed file content here>
FIXED_FILE_END
"""

def generate_fix(issue: dict, file_path: str, file_content: str) -> dict:
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

## Affected file: `{file_path}`
```csharp
{file_content[:12000]}
```

Apply a minimal, targeted fix. Use the exact format with SUMMARY, CONFIDENCE, FIXED_FILE_START and FIXED_FILE_END markers.
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

    # Parse using markers — avoids JSON escaping issues with C# code
    summary_m    = re.search(r"SUMMARY:\s*(.+)", raw)
    confidence_m = re.search(r"CONFIDENCE:\s*(high|medium|low)", raw, re.IGNORECASE)
    content_m    = re.search(r"FIXED_FILE_START\s*([\s\S]*?)\s*FIXED_FILE_END", raw)

    if not content_m:
        raise ValueError(f"Could not find FIXED_FILE_START/END markers in response:\n{raw[:400]}")

    return {
        "fixed_content": content_m.group(1),
        "summary":       summary_m.group(1).strip() if summary_m else "Fix applied.",
        "confidence":    confidence_m.group(1).lower() if confidence_m else "medium",
    }

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

    # Parse issue body
    issue = parse_issue_body(ISSUE_BODY)

    # Step 1 — Fetch repo file tree
    print(f"  Fetching repo file tree from {DEFAULT_BRANCH}...")
    file_tree = get_repo_file_tree(DEFAULT_BRANCH)
    print(f"  Found {len(file_tree)} fixable files")

    # Step 2 — Identify affected file
    print("  Identifying affected file with GPT-4o...")
    file_path, reasoning = identify_affected_file(issue, file_tree)
    print(f"  Identified : {file_path or 'UNKNOWN'}")
    print(f"  Reasoning  : {reasoning}")

    if not file_path:
        comment_on_issue(
            "⚠️ **AI Fix Agent** could not identify which file contains this bug.\n\n"
            "Please add more detail to the issue (mention the class name, method name, "
            "or endpoint that is failing) and re-apply the `bug` label to retry."
        )
        print("  Could not identify file — commented on issue. Exiting.")
        sys.exit(0)

    # Step 3 — Fetch file content
    print(f"  Fetching {file_path}...")
    try:
        file_content, blob_sha = get_file(file_path, DEFAULT_BRANCH)
    except Exception as e:
        comment_on_issue(
            f"⚠️ **AI Fix Agent** identified `{file_path}` as the affected file "
            f"but could not fetch it: `{e}`"
        )
        sys.exit(1)

    # Step 4 — Generate fix
    print("  Generating fix with GPT-4o...")
    result       = generate_fix(issue, file_path, file_content)
    fixed_content = result.get("fixed_content", "")
    summary      = result.get("summary", "No summary provided.")
    confidence   = result.get("confidence", "unknown")
    print(f"  Confidence : {confidence}")
    print(f"  Summary    : {summary}")

    if not fixed_content or fixed_content.strip() == file_content.strip():
        comment_on_issue(
            f"ℹ️ **AI Fix Agent** identified `{file_path}` as the affected file "
            f"but could not determine a fix.\n\n**Reason:** {summary}"
        )
        print("  No change produced — commented on issue.")
        sys.exit(0)

    # Step 5 — Create fix branch
    fix_branch = f"fix/issue-{ISSUE_NUMBER}-{slugify(ISSUE_TITLE)}"
    print(f"  Creating branch: {fix_branch}")
    base_sha = get_branch_sha(DEFAULT_BRANCH)
    create_branch(fix_branch, base_sha)

    # Step 6 — Commit fix
    print(f"  Committing fix to {fix_branch}...")
    commit_fix(
        file_path=file_path,
        content=fixed_content,
        blob_sha=blob_sha,
        branch=fix_branch,
        message=f"fix: #{ISSUE_NUMBER} — {ISSUE_TITLE}\n\n{summary}",
    )

    # Step 7 — Raise PR
    print("  Raising fix PR...")
    pr_url = raise_pr(fix_branch, file_path, summary)
    print(f"  Fix PR: {pr_url}")

    # Step 8 — Trigger PR Review Agent automatically via repository_dispatch
    fix_pr_number = pr_url.rstrip("/").split("/")[-1]
    trigger_pr_review(fix_branch, fix_pr_number, f"[ai-fix] #{ISSUE_NUMBER}: {ISSUE_TITLE}", DEFAULT_BRANCH)

    # Step 10 — Comment on issue
    comment_on_issue("\n".join([
        "## 🤖 AI Fix Agent — Fix PR Raised",
        "",
        f"Automatically identified **`{file_path}`** as the affected file.",
        f"> {reasoning}",
        "",
        f"👉 **[View Fix PR]({pr_url})**",
        "",
        "The **PR Review Agent** is now analysing the fix.",
        "Please review the PR and the AI review before merging.",
        "",
        f"*Confidence: `{confidence}`*",
        "",
        "*Raised by **PMS AI Fix Agent***",
    ]))
    print("  Commented on issue.")

    print("=" * 60)
    print(f"[DONE] Fix PR: {pr_url}")
    print("       PR Review Agent will analyse it automatically.")


if __name__ == "__main__":
    main()
