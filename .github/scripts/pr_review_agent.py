#!/usr/bin/env python3
"""
Patient Management System — AI PR Review Agent
-----------------------------------------------
Fetches a GitHub PR diff, sends it to GitHub Models (gpt-4o) — free, no API key needed.
Uses GITHUB_TOKEN which is automatically provided by GitHub Actions.

Required env vars:
  GITHUB_TOKEN   — automatically provided by GitHub Actions
  PR_NUMBER      — PR number (set by GitHub Actions)
  REPO_FULL_NAME — e.g. "yourorg/patient-management-system"
"""

import os
import re
import sys
import json
import requests
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_TOKEN    = os.environ["GITHUB_TOKEN"]
GH_MODELS_TOKEN = os.environ["GH_MODELS_TOKEN"]
PR_NUMBER       = os.environ["PR_NUMBER"]
REPO_FULL_NAME  = os.environ["REPO_FULL_NAME"]

GITHUB_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Max diff size sent to Claude (chars). Large diffs are intelligently trimmed.
MAX_DIFF_CHARS = 80_000

# ─────────────────────────────────────────────────────────────────────────────
# Project context (system prompt for Claude)
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_SYSTEM_PROMPT = """
You are an expert senior engineer performing automated code review for the
**Patient Management System (PMS)** — a production-grade, .NET 8 microservices
application that handles Protected Health Information (PHI).

━━━ ARCHITECTURE ━━━
• API Gateway    — YARP reverse proxy (port 4004), routes to downstream services
• Auth Service   — JWT Bearer (HS256), rate limiting via RateLimiterConfig
• Patient Service— Core CRUD via AppDbContext → PostgreSQL (port 5244)
• Billing Service— gRPC (Billing_Service.proto) + Kafka consumer (port 9001)
• AI/LLM Service — Ollama (llama3) via OpenAI SDK, Kafka consumer (port 5000)

━━━ KEY TECH STACK ━━━
• .NET 8.0 / ASP.NET Core / C#
• Entity Framework Core 8 + Npgsql (PostgreSQL 16)
• Apache Kafka (Confluent.Kafka 2.13) — topics: patient-created, patient-updated,
  patient-deleted, billing-created
• gRPC with Protobuf (Billing_Service.proto, Patient_Event.proto)
• Redis (StackExchange.Redis) — caching layer
• Serilog — structured logging to file + console (NO Console.WriteLine)
• Prometheus + Grafana — metrics scraping
• Docker Compose + Kubernetes — deployment targets
• xUnit + Moq + FluentAssertions + coverlet — testing

━━━ REVIEW PRIORITIES (in order) ━━━
1. PHI/Security — Patient data is PHI. Flag immediately if: logged in plain text,
   returned in unauthorized responses, stored outside DB, or exposed in errors.
2. Auth gaps     — All /patient and /billing endpoints must have [Authorize].
3. Async safety  — No .Result/.Wait() blocking on async. CancellationToken must
   be propagated to DB/gRPC/Kafka calls.
4. EF Core safety— No raw SQL. Use AppDbContext. Include .Include() to avoid N+1.
   Model changes need a matching EF migration.
5. Kafka reliability — Consumers must catch DeserializeException and log via
   Serilog. New topics must be registered in KafkaTopicCreator.
6. gRPC compat   — No proto field removals. No reuse of field numbers.
7. Docker/K8s    — Multi-stage Dockerfiles. No secrets in Dockerfiles/manifests.
   New services need docker-compose entry with health check + K8s YAMLs.
8. Observability — New services need /health endpoint + Prometheus scrape target
   in prometheus.yml.
9. Tests         — New controllers/services need tests in PMS.Tests/.
10. Code quality — No magic strings. Exceptions use custom types from /Exceptions/.

━━━ OUTPUT FORMAT ━━━
Respond with ONLY a valid JSON object — no prose before or after. Schema:
{
  "summary": "<2-3 sentence overall assessment>",
  "verdict": "approved | changes_requested | commented",
  "critical_issues": [
    { "title": "<short>", "description": "<specific>", "file": "<path or null>", "line": <int or null> }
  ],
  "suggestions": [
    { "title": "<short>", "description": "<specific>", "file": "<path or null>", "line": <int or null> }
  ],
  "security_notes": "<PHI / auth / injection findings, or 'No security concerns found'>",
  "test_coverage_notes": "<assessment of whether new code is tested>",
  "inline_comments": [
    { "path": "<exact file path from diff>", "line": <diff line number>, "body": "<markdown comment>" }
  ]
}

Rules:
• verdict = "approved" ONLY if critical_issues is empty.
• inline_comments: max 5. Only reference files present in the diff.
  line must be the line number of an ADDED (+) line in the diff.
• Be specific to THIS codebase — reference class names, file paths, patterns used here.
• Never invent issues. Base findings strictly on the diff content.
"""

# ─────────────────────────────────────────────────────────────────────────────
# GitHub helpers
# ─────────────────────────────────────────────────────────────────────────────

def gh_get(path: str, accept: str = None) -> requests.Response:
    headers = dict(GH_HEADERS)
    if accept:
        headers["Accept"] = accept
    r = requests.get(f"{GITHUB_API}{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r


def get_pr_details() -> dict:
    return gh_get(f"/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}").json()


def get_pr_files() -> list:
    """Returns list of changed file objects (filename, status, additions, deletions, patch)."""
    files = []
    page = 1
    while True:
        page_data = gh_get(
            f"/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/files?per_page=100&page={page}"
        ).json()
        if not page_data:
            break
        files.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return files


def get_pr_diff() -> str:
    return gh_get(
        f"/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}",
        accept="application/vnd.github.v3.diff"
    ).text


# ─────────────────────────────────────────────────────────────────────────────
# Diff processing
# ─────────────────────────────────────────────────────────────────────────────

# Files that are unlikely to need deep review
SKIP_PATTERNS = re.compile(
    r"(\.Designer\.cs$|ModelSnapshot\.cs$|Migrations/\d+_|\.http$|db-data/|zookeeper)",
    re.IGNORECASE,
)


def filter_diff(diff: str, files: list) -> str:
    """
    Remove migration designer files and large data files from the diff
    to focus Claude on meaningful code changes.
    """
    skip_files = {
        f["filename"] for f in files if SKIP_PATTERNS.search(f["filename"])
    }
    if not skip_files:
        return diff

    # Split diff by file boundary
    parts = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    kept = []
    skipped_count = 0
    for part in parts:
        if not part.strip():
            continue
        # Extract filename from diff header
        m = re.match(r"diff --git a/(.+?) b/", part)
        if m and m.group(1) in skip_files:
            skipped_count += 1
            continue
        kept.append(part)

    result = "".join(kept)
    if skipped_count:
        result = (
            f"# NOTE: {skipped_count} auto-generated file(s) omitted from diff "
            f"(migrations, designers, data volumes).\n\n" + result
        )
    return result


def trim_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """Keep the diff under max_chars by trimming from the middle."""
    if len(diff) <= max_chars:
        return diff
    head = diff[:max_chars // 2]
    tail = diff[-(max_chars // 4):]
    omitted = len(diff) - len(head) - len(tail)
    return (
        head
        + f"\n\n... [{omitted:,} chars omitted — diff too large] ...\n\n"
        + tail
    )


# ─────────────────────────────────────────────────────────────────────────────
# GitHub Models review (free — uses GITHUB_TOKEN)
# ─────────────────────────────────────────────────────────────────────────────

def run_ai_review(pr: dict, files: list, diff: str) -> dict:
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GH_MODELS_TOKEN,
    )

    files_summary = "\n".join(
        f"  {f['status']:8s}  +{f['additions']:<4} -{f['deletions']:<4}  {f['filename']}"
        for f in files
    )

    user_message = f"""Please review this pull request.

## PR Metadata
- Title       : {pr['title']}
- Author      : {pr['user']['login']}
- Base branch : {pr['base']['ref']} ← {pr['head']['ref']}
- Description :
{pr.get('body') or '*(no description provided)*'}

## Files Changed ({len(files)} files)
{files_summary}

## Unified Diff
```diff
{diff}
```
"""

    print("Sending diff to GitHub Models (gpt-4o) for review...")
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": PROJECT_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Parse JSON — handle cases where model wraps it in a code block
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Model response is not valid JSON:\n{raw[:800]}")


# ─────────────────────────────────────────────────────────────────────────────
# GitHub review posting
# ─────────────────────────────────────────────────────────────────────────────

VERDICT_EMOJI = {
    "approved":           "✅",
    "changes_requested":  "🔴",
    "commented":          "💬",
}

GITHUB_EVENT_MAP = {
    "approved":           "APPROVE",
    "changes_requested":  "REQUEST_CHANGES",
    "commented":          "COMMENT",
}


def build_review_body(review: dict) -> str:
    verdict = review.get("verdict", "commented")
    emoji   = VERDICT_EMOJI.get(verdict, "💬")

    lines = [
        f"## {emoji} AI Code Review — Patient Management System",
        "",
        f"**{review.get('summary', 'No summary provided.')}**",
        "",
    ]

    # Critical issues
    critical = review.get("critical_issues") or []
    if critical:
        lines += ["### 🚨 Critical Issues", ""]
        for i in critical:
            loc = f" (`{i['file']}:{i['line']}`)" if i.get("file") and i.get("line") else ""
            lines.append(f"- **{i['title']}**{loc}  \n  {i['description']}")
        lines.append("")

    # Suggestions
    suggestions = review.get("suggestions") or []
    if suggestions:
        lines += ["### 💡 Suggestions", ""]
        for s in suggestions:
            loc = f" (`{s['file']}:{s['line']}`)" if s.get("file") and s.get("line") else ""
            lines.append(f"- **{s['title']}**{loc}  \n  {s['description']}")
        lines.append("")

    # Security
    sec = review.get("security_notes", "").strip()
    if sec:
        lines += [f"### 🔒 Security & PHI", "", sec, ""]

    # Test coverage
    tests = review.get("test_coverage_notes", "").strip()
    if tests:
        lines += [f"### 🧪 Test Coverage", "", tests, ""]

    lines += [
        "---",
        "*Automated review by GitHub Models (gpt-4o) · "
        "[View workflow](../../actions/workflows/pr-review.yml)*",
    ]
    return "\n".join(lines)


def post_github_review(pr: dict, review: dict, files: list):
    body    = build_review_body(review)
    verdict = review.get("verdict", "commented")
    event   = GITHUB_EVENT_MAP.get(verdict, "COMMENT")

    # Build inline comments — only for valid files/lines in the diff
    valid_paths = {f["filename"] for f in files}
    inline = []
    for c in (review.get("inline_comments") or []):
        path = c.get("path", "")
        line = c.get("line")
        body_text = c.get("body", "").strip()
        if path in valid_paths and isinstance(line, int) and line > 0 and body_text:
            inline.append({"path": path, "line": line, "body": body_text, "side": "RIGHT"})

    payload = {"body": body, "event": event, "comments": inline}
    url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/reviews"

    r = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)
    if not r.ok:
        print(f"Warning: review with inline comments failed ({r.status_code}). Retrying without inline comments.")
        payload["comments"] = []
        r = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)
        r.raise_for_status()

    review_url = r.json().get("html_url", "N/A")
    print(f"Review posted: {review_url}")
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"[PMS PR Review Agent] PR #{PR_NUMBER} in {REPO_FULL_NAME}")

    pr    = get_pr_details()
    files = get_pr_files()
    raw_diff = get_pr_diff()

    print(f"  Title         : {pr['title']}")
    print(f"  Files changed : {len(files)}")
    print(f"  Raw diff size : {len(raw_diff):,} chars")

    diff = filter_diff(raw_diff, files)
    diff = trim_diff(diff)
    print(f"  Processed diff: {len(diff):,} chars")

    review = run_ai_review(pr, files, diff)

    # Persist output for the artifact upload step
    with open("pr_review_output.json", "w") as f:
        json.dump(review, f, indent=2)

    print(f"  Verdict        : {review.get('verdict')}")
    print(f"  Critical issues: {len(review.get('critical_issues') or [])}")
    print(f"  Suggestions    : {len(review.get('suggestions') or [])}")
    print(f"  Inline comments: {len(review.get('inline_comments') or [])}")

    post_github_review(pr, review, files)

    # Fail the workflow step if critical issues were found
    # (this marks the check red on the PR without blocking merge by default)
    critical = review.get("critical_issues") or []
    if critical:
        print(f"\n[FAIL] {len(critical)} critical issue(s) found — marking check as failed.")
        sys.exit(1)

    print("\n[PASS] Review complete — no critical issues.")


if __name__ == "__main__":
    main()
