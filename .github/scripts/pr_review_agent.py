#!/usr/bin/env python3
"""
Patient Management System — AI PR Review Agent v2
--------------------------------------------------
Multi-pass AI review using GitHub Models (GPT-4o).

Features:
  • Two-pass review — Pass 1: PHI/Security scan, Pass 2: Full quality review
  • PR Health Score (0–100) with visual badge
  • One-click code fix suggestions (GitHub suggestion blocks)
  • Microservice impact map
  • EF Core migration safety detection (DROP/ALTER)
  • Related file context enrichment for better accuracy

Required env vars:
  GITHUB_TOKEN    — GitHub Actions token (PR comments)
  GH_MODELS_TOKEN — PAT with models:read (GitHub Models API)
  PR_NUMBER       — set by GitHub Actions
  REPO_FULL_NAME  — e.g. "Aishwarya-K-R/Test"
"""

import os
import re
import sys
import json
import requests
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_TOKEN    = os.environ["GITHUB_TOKEN"]
GH_MODELS_TOKEN = os.environ["GH_MODELS_TOKEN"]
PR_NUMBER       = os.environ["PR_NUMBER"]
REPO_FULL_NAME  = os.environ["REPO_FULL_NAME"]

GITHUB_API  = "https://api.github.com"
GH_HEADERS  = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
MAX_DIFF_CHARS = 16_000   # GitHub Models free tier: 8k token limit per request

# ─────────────────────────────────────────────────────────────────────────────
# Microservice impact map
# Maps file path prefixes → affected service name
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_MAP = {
    "Controllers/Patient":    "patient-service",
    "Controllers/Auth":       "auth-service",
    "Controllers/AI":         "ai-service",
    "Controllers/Health":     "api-gateway",
    "Services/PatientService":"patient-service",
    "Services/AuthService":   "auth-service",
    "Services/BillingGrpc":   "billing-service",
    "Services/LLMService":    "ai-service",
    "Services/RedisService":  "all-services",
    "Services/ContextService":"ai-service",
    "Kafka/":                 "event-streaming",
    "Protos/":                "grpc-contracts",
    "Migrations/":            "database",
    "Kubernetes/":            "infrastructure",
    "Dockerfile.patient":     "patient-service",
    "Dockerfile.auth":        "auth-service",
    "Dockerfile.billing":     "billing-service",
    "Dockerfile.llm":         "ai-service",
    "Dockerfile.api-gateway": "api-gateway",
    "docker-compose":         "all-services",
    "appsettings":            "configuration",
    "Program.cs":             "startup/DI",
    "Config/":                "rate-limiting",
    "Exceptions/":            "error-handling",
}

SKIP_PATTERNS = re.compile(
    r"(\.Designer\.cs$|ModelSnapshot\.cs$|Migrations/\d+_.*\.cs$"
    r"|\.http$|db-data/|zookeeper|bin/|obj/)",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# AI Prompts
# ─────────────────────────────────────────────────────────────────────────────

SECURITY_PASS_PROMPT = """
You are a healthcare security specialist reviewing code for the Patient Management System (PMS).
This system handles Protected Health Information (PHI) — patient names, emails, addresses, dates of birth.

Scan ONLY for:
1. PHI exposure — patient.Name/Email/Address/DateOfBirth appearing in log messages, error responses, or returned without auth
2. Missing [Authorize] — any endpoint touching patient or billing data without authorization attribute
3. JWT issues — token validation bypasses, weak secrets
4. Raw SQL — any FromSqlRaw/ExecuteSqlRaw with unparameterized input
5. Hardcoded secrets — API keys, passwords, connection strings in code

Return ONLY valid JSON, no prose:
{
  "phi_risks": [
    {"description": "...", "file": "path/to/file.cs", "line": <int or null>, "severity": "critical"}
  ],
  "auth_gaps": [
    {"description": "...", "file": "path/to/file.cs", "line": <int or null>}
  ],
  "other_security": [
    {"description": "...", "file": "path/to/file.cs", "line": <int or null>}
  ],
  "is_clean": <true if no issues found, else false>
}
"""

FULL_REVIEW_PROMPT = """
You are an expert .NET 8 senior engineer reviewing the Patient Management System (PMS).

Architecture: YARP API Gateway → [Auth | Patient | Billing(gRPC) | AI/LLM] services → PostgreSQL + Redis + Kafka

Tech: .NET 8, EF Core 8 + Npgsql, Confluent.Kafka, gRPC/Protobuf, StackExchange.Redis,
      Serilog, Prometheus, Docker Compose, Kubernetes, xUnit + Moq + FluentAssertions

Review priorities:
1. Async patterns — no .Result/.Wait() blocking; CancellationToken must be propagated to DB/Kafka/gRPC calls
2. EF Core — no N+1 (use .Include()), always use AppDbContext, model changes need EF migration
3. Kafka — consumers must catch DeserializeException + log via Serilog; new topics need KafkaTopicCreator
4. gRPC — no proto field removals, no field number reuse in Billing_Service.proto / Patient_Event.proto
5. Docker/K8s — new services need Dockerfile + docker-compose entry with health check + K8s YAMLs
6. Logging — Serilog only (no Console.WriteLine), no PHI in structured log properties
7. Tests — new controllers/services must have tests in PMS.Tests/
8. Code quality — use custom exceptions from /Exceptions/, no magic strings

For issues where a fix is obvious, include the corrected code in the "fix" field.

Return ONLY valid JSON, no prose:
{
  "summary": "<2-3 sentence overall assessment>",
  "verdict": "approved|changes_requested|commented",
  "critical_issues": [
    {
      "title": "<short title>",
      "description": "<specific, actionable>",
      "file": "<path or null>",
      "line": <int or null>,
      "fix": "<corrected code snippet, or null>"
    }
  ],
  "suggestions": [
    {
      "title": "<short title>",
      "description": "<specific, actionable>",
      "file": "<path or null>",
      "line": <int or null>,
      "fix": "<corrected code snippet, or null>"
    }
  ],
  "test_coverage_notes": "<assessment>",
  "inline_comments": [
    {
      "path": "<exact file path from diff>",
      "line": <diff line number of an added line>,
      "body": "<markdown comment>",
      "fix": "<1-3 lines of corrected code, or null>"
    }
  ]
}
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
    files, page = [], 1
    while True:
        batch = gh_get(f"/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/files?per_page=100&page={page}").json()
        if not batch:
            break
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files


def get_pr_diff() -> str:
    return gh_get(
        f"/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}",
        accept="application/vnd.github.v3.diff"
    ).text


def get_file_content(path: str, ref: str) -> str:
    """Fetch current content of a file for additional context."""
    try:
        r = gh_get(f"/repos/{REPO_FULL_NAME}/contents/{path}?ref={ref}")
        import base64
        return base64.b64decode(r.json()["content"]).decode("utf-8")
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# Diff processing
# ─────────────────────────────────────────────────────────────────────────────

def filter_diff(diff: str, files: list) -> str:
    skip_files = {f["filename"] for f in files if SKIP_PATTERNS.search(f["filename"])}
    if not skip_files:
        return diff
    parts = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    kept, skipped = [], 0
    for part in parts:
        if not part.strip():
            continue
        m = re.match(r"diff --git a/(.+?) b/", part)
        if m and m.group(1) in skip_files:
            skipped += 1
            continue
        kept.append(part)
    result = "".join(kept)
    if skipped:
        result = f"# NOTE: {skipped} auto-generated file(s) omitted.\n\n" + result
    return result


def trim_diff(diff: str) -> str:
    if len(diff) <= MAX_DIFF_CHARS:
        return diff
    head = diff[:MAX_DIFF_CHARS // 2]
    tail = diff[-(MAX_DIFF_CHARS // 4):]
    omitted = len(diff) - len(head) - len(tail)
    return head + f"\n\n... [{omitted:,} chars omitted] ...\n\n" + tail

# ─────────────────────────────────────────────────────────────────────────────
# Microservice impact analysis
# ─────────────────────────────────────────────────────────────────────────────

def get_impacted_services(files: list) -> list:
    impacted = set()
    for f in files:
        path = f["filename"]
        for prefix, service in SERVICE_MAP.items():
            if prefix.lower() in path.lower():
                impacted.add(service)
    return sorted(impacted)


def get_risk_level(files: list) -> tuple:
    """Returns (risk_label, risk_emoji) based on what files changed."""
    filenames = [f["filename"] for f in files]
    has_migration  = any("Migrations/" in fn for fn in filenames)
    has_proto      = any(".proto" in fn for fn in filenames)
    has_controller = any("Controllers/" in fn for fn in filenames)
    has_auth       = any("Auth" in fn for fn in filenames)
    has_k8s        = any("Kubernetes/" in fn for fn in filenames)

    if has_migration or has_proto or has_auth:
        return "HIGH", "🔴"
    elif has_controller or has_k8s:
        return "MEDIUM", "🟡"
    else:
        return "LOW", "🟢"

# ─────────────────────────────────────────────────────────────────────────────
# EF Core migration safety check
# ─────────────────────────────────────────────────────────────────────────────

DESTRUCTIVE_PATTERNS = re.compile(
    r"\.(DropTable|DropColumn|AlterColumn|DropIndex|DropForeignKey|DropPrimaryKey)\(",
    re.IGNORECASE,
)

def check_migration_safety(files: list, pr_head_sha: str) -> list:
    """Scan EF Core migration files for destructive operations."""
    warnings = []
    migration_files = [
        f for f in files
        if "Migrations/" in f["filename"]
        and f["filename"].endswith(".cs")
        and "Designer" not in f["filename"]
        and "Snapshot" not in f["filename"]
    ]
    for mf in migration_files:
        content = get_file_content(mf["filename"], pr_head_sha)
        if not content:
            patch = mf.get("patch", "")
            added_lines = "\n".join(
                l[1:] for l in patch.splitlines() if l.startswith("+")
            )
            content = added_lines
        matches = DESTRUCTIVE_PATTERNS.findall(content)
        if matches:
            ops = ", ".join(set(matches))
            warnings.append(
                f"**`{mf['filename']}`** contains destructive operation(s): `{ops}` — "
                f"verify data loss is intentional and a backup plan exists."
            )
    return warnings

# ─────────────────────────────────────────────────────────────────────────────
# Related file context enrichment
# ─────────────────────────────────────────────────────────────────────────────

CONTEXT_PAIRS = {
    "Controllers/PatientController.cs": "Services/PatientService.cs",
    "Controllers/AuthController.cs":    "Services/AuthService.cs",
    "Controllers/AIController.cs":      "Services/LLMService.cs",
    "Kafka/KafkaConsumer.cs":           "Kafka/KafkaProducer.cs",
}

def enrich_with_context(files: list, pr_head_sha: str) -> str:
    """Fetch related files to give the AI better context."""
    changed = {f["filename"] for f in files}
    context_blocks = []
    for changed_file, related_file in CONTEXT_PAIRS.items():
        if changed_file in changed and related_file not in changed:
            content = get_file_content(related_file, pr_head_sha)
            if content:
                context_blocks.append(
                    f"### Related file (not in diff): `{related_file}`\n```csharp\n{content[:3000]}\n```"
                )
    return "\n\n".join(context_blocks)

# ─────────────────────────────────────────────────────────────────────────────
# PR Health Score
# ─────────────────────────────────────────────────────────────────────────────

def calculate_score(security: dict, review: dict, migration_warnings: list) -> int:
    score = 100
    score -= len(security.get("phi_risks") or []) * 25
    score -= len(security.get("auth_gaps") or []) * 20
    score -= len(security.get("other_security") or []) * 10
    score -= len(review.get("critical_issues") or []) * 15
    score -= len(review.get("suggestions") or []) * 3
    score -= len(migration_warnings) * 10
    notes = (review.get("test_coverage_notes") or "").lower()
    if any(w in notes for w in ["no test", "missing test", "no new test", "not provided"]):
        score -= 10
    return max(0, min(100, score))


def score_badge(score: int) -> str:
    if score >= 90:
        color, label = "brightgreen", "Excellent"
    elif score >= 70:
        color, label = "green", "Good"
    elif score >= 50:
        color, label = "yellow", "Needs+Work"
    else:
        color, label = "red", "Major+Issues"
    bar_filled = round(score / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    return (
        f"![PR Score](https://img.shields.io/badge/PR%20Score-{score}%2F100-{color}?style=for-the-badge)  \n"
        f"`{bar}` **{score}/100 — {label}**"
    )

# ─────────────────────────────────────────────────────────────────────────────
# AI calls
# ─────────────────────────────────────────────────────────────────────────────

def call_model(system: str, user: str) -> dict:
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GH_MODELS_TOKEN,
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
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
        raise ValueError(f"Model response not valid JSON:\n{raw[:600]}")


def extract_added_lines(diff: str) -> str:
    """Extract only added (+) lines from diff to minimize token usage."""
    lines = []
    current_file = ""
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            m = re.search(r"b/(.+)$", line)
            if m:
                current_file = m.group(1)
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append(f"{current_file}: {line[1:].strip()}")
    return "\n".join(lines[:400])   # cap at 400 added lines


def run_security_pass(diff: str) -> dict:
    print("  [Pass 1] Security & PHI scan...")
    added_only = extract_added_lines(diff)
    return call_model(SECURITY_PASS_PROMPT, f"Scan these added lines for security issues:\n\n{added_only}")


def run_full_review(pr: dict, files: list, diff: str, context: str, security: dict) -> dict:
    print("  [Pass 2] Full quality review...")
    files_summary = "\n".join(
        f"  {f['status']:8s}  +{f['additions']:<4} -{f['deletions']:<4}  {f['filename']}"
        for f in files
    )
    # Keep security summary compact to save tokens
    security_summary = json.dumps({
        "phi_risks":      security.get("phi_risks") or [],
        "auth_gaps":      security.get("auth_gaps") or [],
        "other_security": security.get("other_security") or [],
    })
    user_msg = f"""Review this pull request for the Patient Management System.

## PR
- Title: {pr['title']}
- Author: {pr['user']['login']}
- Base ← Head: {pr['base']['ref']} ← {pr['head']['ref']}
- Description: {pr.get('body') or '*(none)*'}

## Files Changed ({len(files)})
{files_summary}

## Security Pre-scan Results (Pass 1)
```json
{security_summary}
```

## Additional Context (related files)
{context or '*(none)*'}

## Diff
```diff
{diff}
```
"""
    return call_model(FULL_REVIEW_PROMPT, user_msg)

# ─────────────────────────────────────────────────────────────────────────────
# Build review body
# ─────────────────────────────────────────────────────────────────────────────

def build_review_body(
    pr: dict,
    review: dict,
    security: dict,
    migration_warnings: list,
    impacted_services: list,
    risk_label: str,
    risk_emoji: str,
    score: int,
) -> str:
    verdict = review.get("verdict", "commented")
    verdict_emoji = {"approved": "✅", "changes_requested": "🔴", "commented": "💬"}.get(verdict, "💬")

    lines = [
        f"## {verdict_emoji} AI Code Review — Patient Management System",
        "",
        score_badge(score),
        "",
        f"**{review.get('summary', '')}**",
        "",
    ]

    # Impact map
    if impacted_services:
        services_str = " · ".join(f"`{s}`" for s in impacted_services)
        lines += [
            f"### 🗺️ Microservice Impact  {risk_emoji} Risk: {risk_label}",
            f"{services_str}",
            "",
        ]

    # Migration warnings
    if migration_warnings:
        lines += ["### ⚠️ Migration Safety", ""]
        for w in migration_warnings:
            lines.append(f"- {w}")
        lines.append("")

    # PHI / Auth issues from security pass
    phi  = security.get("phi_risks") or []
    auth = security.get("auth_gaps") or []
    other_sec = security.get("other_security") or []
    if phi or auth or other_sec:
        lines += ["### 🔒 Security & PHI", ""]
        for item in phi + auth + other_sec:
            loc = f" (`{item['file']}:{item['line']}`)" if item.get("file") and item.get("line") else \
                  f" (`{item['file']}`)" if item.get("file") else ""
            lines.append(f"- 🚨 {item['description']}{loc}")
        lines.append("")

    # Critical issues
    critical = review.get("critical_issues") or []
    if critical:
        lines += ["### 🚨 Critical Issues", ""]
        for i in critical:
            loc = f" (`{i['file']}:{i['line']}`)" if i.get("file") and i.get("line") else \
                  f" (`{i['file']}`)" if i.get("file") else ""
            lines.append(f"- **{i['title']}**{loc}  \n  {i['description']}")
            if i.get("fix"):
                lines.append(f"  <details><summary>Suggested fix</summary>\n\n  ```csharp\n  {i['fix']}\n  ```\n  </details>")
        lines.append("")

    # Suggestions
    suggestions = review.get("suggestions") or []
    if suggestions:
        lines += ["### 💡 Suggestions", ""]
        for s in suggestions:
            loc = f" (`{s['file']}:{s['line']}`)" if s.get("file") and s.get("line") else \
                  f" (`{s['file']}`)" if s.get("file") else ""
            lines.append(f"- **{s['title']}**{loc}  \n  {s['description']}")
            if s.get("fix"):
                lines.append(f"  <details><summary>Suggested fix</summary>\n\n  ```csharp\n  {s['fix']}\n  ```\n  </details>")
        lines.append("")

    # Test coverage
    test_notes = (review.get("test_coverage_notes") or "").strip()
    if test_notes:
        lines += ["### 🧪 Test Coverage", "", test_notes, ""]

    lines += [
        "---",
        "*Automated review by **PMS AI Agent v2** · GitHub Models (GPT-4o) · "
        "[View workflow](../../actions/workflows/pr-review.yml)*",
    ]
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Auto-fix engine
# ─────────────────────────────────────────────────────────────────────────────

def fetch_file_for_fix(path: str, ref: str) -> tuple:
    """Returns (content, sha) for a file at a given ref."""
    import base64
    r = gh_get(f"/repos/{REPO_FULL_NAME}/contents/{path}?ref={ref}")
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def ai_apply_fix(file_content: str, issue_title: str, issue_description: str, suggested_fix: str) -> str:
    """Ask GPT-4o to apply a specific fix to the full file. Returns fixed file content."""
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GH_MODELS_TOKEN,
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=6000,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise .NET code editor. Apply the requested fix to the file. "
                    "Return ONLY the complete fixed file content — no explanation, no markdown, "
                    "no code fences. Preserve all existing code exactly except for the fix."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Issue: {issue_title}\n"
                    f"Description: {issue_description}\n"
                    f"Fix to apply: {suggested_fix}\n\n"
                    f"File content:\n{file_content[:5000]}\n\n"
                    "Return the complete fixed file content only."
                ),
            },
        ],
    )
    return response.choices[0].message.content.strip()


def commit_fix(path: str, content: str, sha: str, message: str, branch: str):
    """Commit a single file update to the PR branch via GitHub Contents API."""
    import base64
    url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": branch,
    }
    r = requests.put(url, headers=GH_HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def create_fix_branch(base_sha: str, fix_branch: str):
    """Create a new branch from base_sha for the fix PR. If it already exists, reset it to base_sha."""
    url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/git/refs"
    r = requests.post(url, headers=GH_HEADERS, json={
        "ref": f"refs/heads/{fix_branch}",
        "sha": base_sha,
    }, timeout=30)
    if r.status_code == 422:
        # Branch already exists — force-update it to the current base SHA
        patch_url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/git/refs/heads/{fix_branch}"
        r2 = requests.patch(patch_url, headers=GH_HEADERS, json={"sha": base_sha, "force": True}, timeout=30)
        r2.raise_for_status()
        print(f"  Fix branch '{fix_branch}' already existed — reset to base SHA.")
    else:
        r.raise_for_status()


def raise_fix_pr(pr: dict, fix_branch: str, applied_fixes: list) -> str:
    """Raise a PR from fix_branch → original PR branch."""
    critical = [f for f in applied_fixes if f["severity"] == "critical"]
    suggestions = [f for f in applied_fixes if f["severity"] == "suggestion"]

    body_lines = [
        f"## 🤖 AI Auto-fix for PR #{PR_NUMBER} — {pr['title']}",
        "",
        f"This PR was automatically generated by **PMS AI Agent v2** to fix issues found in "
        f"[PR #{PR_NUMBER}](https://github.com/{REPO_FULL_NAME}/pull/{PR_NUMBER}).",
        "",
        "### Fixes Applied",
        "",
    ]
    if critical:
        body_lines.append("**Critical:**")
        for f in critical:
            body_lines.append(f"- ✅ `{f['file']}` — {f['title']}")
        body_lines.append("")
    if suggestions:
        body_lines.append("**Suggestions:**")
        for f in suggestions:
            body_lines.append(f"- ✅ `{f['file']}` — {f['title']}")
        body_lines.append("")

    body_lines += [
        "---",
        "> ⚠️ Review each change carefully before merging — AI-generated fixes should always be verified.",
        "",
        "*Raised by **PMS AI Agent v2***",
    ]

    url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls"
    r = requests.post(url, headers=GH_HEADERS, json={
        "title": f"[auto-fix] Fixes for PR #{PR_NUMBER}: {pr['title']}",
        "body": "\n".join(body_lines),
        "head": fix_branch,
        "base": pr["head"]["ref"],   # fix PR targets the feature branch, not main
    }, timeout=30)
    if r.status_code == 422:
        # PR already exists — find and return its URL
        existing = requests.get(
            f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls",
            headers=GH_HEADERS,
            params={"head": f"{REPO_FULL_NAME.split('/')[0]}:{fix_branch}", "state": "open"},
            timeout=30,
        ).json()
        if existing:
            print(f"  Fix PR already exists: {existing[0]['html_url']}")
            return existing[0]["html_url"]
        r.raise_for_status()
    else:
        r.raise_for_status()
    return r.json()["html_url"]


def apply_auto_fixes(review: dict, security: dict, pr: dict) -> list:
    """
    Create a dedicated fix branch, apply fixes there, and raise a separate PR.
    Never commits directly to the original PR branch.
    """
    import base64

    def is_valid_file(f):
        return (f and isinstance(f, str)
                and f.lower() not in ("none", "null", "")
                and (f.endswith(".cs") or "/" in f))

    candidates = []
    for issue in (review.get("critical_issues") or []):
        if issue.get("fix") and is_valid_file(issue.get("file")):
            candidates.append({"title": issue["title"], "description": issue["description"],
                                "file": issue["file"], "fix": issue["fix"], "severity": "critical"})
    for issue in (review.get("suggestions") or []):
        if issue.get("fix") and is_valid_file(issue.get("file")):
            candidates.append({"title": issue["title"], "description": issue["description"],
                                "file": issue["file"], "fix": issue["fix"], "severity": "suggestion"})

    if not candidates:
        print("  Auto-fix: no fixable issues found.")
        return []

    # Create a dedicated fix branch off the PR head
    fix_branch = f"auto-fix/pr-{PR_NUMBER}"
    pr_head_sha = pr["head"]["sha"]
    try:
        create_fix_branch(pr_head_sha, fix_branch)
        print(f"  Created fix branch: {fix_branch}")
    except Exception as e:
        print(f"  Warning: could not create fix branch: {e}")
        return []

    # Group candidates by file
    by_file: dict = {}
    for c in candidates:
        by_file.setdefault(c["file"], []).append(c)

    applied = []
    current_sha = pr_head_sha

    for file_path, issues in by_file.items():
        try:
            content, sha = fetch_file_for_fix(file_path, fix_branch)
            working_content = content

            for issue in issues:
                print(f"  Preparing fix [{issue['severity']}]: {issue['title']} → {file_path}")
                try:
                    fixed = ai_apply_fix(
                        working_content,
                        issue["title"],
                        issue["description"],
                        issue["fix"],
                    )
                    if fixed and fixed.strip() != working_content.strip():
                        orig_lines  = working_content.splitlines()
                        fixed_lines = fixed.splitlines()
                        changed     = sum(1 for a, b in zip(orig_lines, fixed_lines) if a != b)
                        changed    += abs(len(fixed_lines) - len(orig_lines))
                        print(f"    → Applying fix ({changed} lines changed) — goes to fix PR for human review")
                        working_content = fixed
                        applied.append({"file": file_path, "title": issue["title"],
                                        "severity": issue["severity"]})
                    else:
                        print(f"    → No change produced")
                except Exception as e:
                    print(f"    → Skipped: {e}")

            if working_content.strip() != content.strip():
                titles = ", ".join(
                    i["title"] for i in issues
                    if any(a["file"] == file_path and a["title"] == i["title"] for a in applied)
                )
                result = commit_fix(
                    file_path, working_content, sha,
                    f"[auto-fix] {titles or file_path}",
                    fix_branch,
                )
                current_sha = result["commit"]["sha"]

        except Exception as e:
            print(f"  Warning: Could not process {file_path}: {e}")

    return applied


def post_autofix_comment(pr: dict, fix_pr_url: str, applied_fixes: list):
    """Post a comment on the original PR linking to the fix PR."""
    critical    = [f for f in applied_fixes if f["severity"] == "critical"]
    suggestions = [f for f in applied_fixes if f["severity"] == "suggestion"]

    lines = [
        "## 🤖 Auto-fix PR Raised by PMS AI Agent",
        "",
        f"The agent found **{len(applied_fixes)} fixable issue(s)** and raised a dedicated fix PR for your review:",
        "",
        f"👉 **[View Fix PR]({fix_pr_url})**",
        "",
    ]
    if critical:
        lines.append("**Critical fixes included:**")
        for f in critical:
            lines.append(f"- `{f['file']}` — {f['title']}")
        lines.append("")
    if suggestions:
        lines.append("**Suggestion fixes included:**")
        for f in suggestions:
            lines.append(f"- `{f['file']}` — {f['title']}")
        lines.append("")
    lines += [
        "> Review the fix PR, merge it into this branch, then re-run the AI review to confirm the score improves.",
        "",
        "*Raised by **PMS AI Agent v2***",
    ]

    url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{PR_NUMBER}/comments"
    r = requests.post(url, headers=GH_HEADERS, json={"body": "\n".join(lines)}, timeout=30)
    r.raise_for_status()
    print(f"  Auto-fix comment posted.")


# ─────────────────────────────────────────────────────────────────────────────
# Post GitHub review
# ─────────────────────────────────────────────────────────────────────────────

def post_github_review(pr: dict, review: dict, security: dict,
                       migration_warnings: list, impacted_services: list,
                       risk_label: str, risk_emoji: str,
                       score: int, files: list):

    body  = build_review_body(pr, review, security, migration_warnings,
                               impacted_services, risk_label, risk_emoji, score)
    event = {"approved": "APPROVE", "changes_requested": "REQUEST_CHANGES"}.get(
        review.get("verdict", "commented"), "COMMENT"
    )

    # Build inline comments with one-click suggestion blocks
    valid_paths = {f["filename"] for f in files}
    inline = []
    for c in (review.get("inline_comments") or []):
        path      = c.get("path", "")
        line      = c.get("line")
        body_text = c.get("body", "").strip()
        fix       = c.get("fix", "")
        if path not in valid_paths or not isinstance(line, int) or line <= 0 or not body_text:
            continue
        comment_body = body_text
        if fix:
            comment_body += f"\n\n```suggestion\n{fix}\n```"
        inline.append({"path": path, "line": line, "body": comment_body, "side": "RIGHT"})

    url     = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/reviews"
    payload = {"body": body, "event": event, "comments": inline}

    r = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)
    if not r.ok:
        print(f"  Warning: inline comments failed ({r.status_code}), retrying without them...")
        payload["comments"] = []
        r = requests.post(url, headers=GH_HEADERS, json=payload, timeout=30)

    if not r.ok:
        # Bot-raised PRs (e.g. from Issue Fix Agent) don't allow formal reviews
        # Fall back to a plain issue comment so the review is still visible
        print(f"  Warning: review API failed ({r.status_code}), falling back to issue comment...")
        comment_url = f"{GITHUB_API}/repos/{REPO_FULL_NAME}/issues/{PR_NUMBER}/comments"
        rc = requests.post(comment_url, headers=GH_HEADERS, json={"body": body}, timeout=30)
        rc.raise_for_status()
        print(f"  Review posted as issue comment.")
        return {}

    print(f"  Review posted: {r.json().get('html_url', 'N/A')}")
    return r.json()

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n[PMS PR Review Agent v2] PR #{PR_NUMBER} — {REPO_FULL_NAME}")
    print("=" * 60)

    pr       = get_pr_details()
    files    = get_pr_files()
    raw_diff = get_pr_diff()

    print(f"  Title         : {pr['title']}")
    print(f"  Author        : {pr['user']['login']}")
    print(f"  Files changed : {len(files)}")
    print(f"  Raw diff      : {len(raw_diff):,} chars")

    # Process diff
    diff = filter_diff(raw_diff, files)
    diff = trim_diff(diff)
    print(f"  Processed diff: {len(diff):,} chars")

    # Microservice impact analysis
    impacted_services          = get_impacted_services(files)
    risk_label, risk_emoji     = get_risk_level(files)
    print(f"  Impacted      : {', '.join(impacted_services) or 'unknown'}")
    print(f"  Risk level    : {risk_label}")

    # Migration safety check
    migration_warnings = check_migration_safety(files, pr["head"]["sha"])
    if migration_warnings:
        print(f"  Migrations    : {len(migration_warnings)} destructive operation(s) found!")

    # Related file context
    context = enrich_with_context(files, pr["head"]["sha"])
    if context:
        print(f"  Context       : enriched with related file(s)")

    # Pass 1 — Security & PHI
    security = run_security_pass(diff)
    phi_count  = len(security.get("phi_risks") or [])
    auth_count = len(security.get("auth_gaps") or [])
    print(f"  PHI risks     : {phi_count}")
    print(f"  Auth gaps     : {auth_count}")

    # Pass 2 — Full review
    review = run_full_review(pr, files, diff, context, security)
    print(f"  Verdict       : {review.get('verdict')}")
    print(f"  Critical      : {len(review.get('critical_issues') or [])}")
    print(f"  Suggestions   : {len(review.get('suggestions') or [])}")
    print(f"  Inline        : {len(review.get('inline_comments') or [])}")

    # Score
    score = calculate_score(security, review, migration_warnings)
    print(f"  Health Score  : {score}/100")

    # Save artifact
    output = {
        "score": score,
        "verdict": review.get("verdict"),
        "impacted_services": impacted_services,
        "risk_level": risk_label,
        "migration_warnings": migration_warnings,
        "security": security,
        "review": review,
    }
    with open("pr_review_output.json", "w") as f:
        json.dump(output, f, indent=2)

    # Post review comment
    post_github_review(
        pr, review, security, migration_warnings,
        impacted_services, risk_label, risk_emoji, score, files
    )

    # Update output artifact
    with open("pr_review_output.json", "w") as f:
        json.dump(output, f, indent=2)

    print("=" * 60)

    # Exit 1 if critical issues exist (marks check red on PR)
    has_critical = (
        review.get("critical_issues")
        or security.get("phi_risks")
        or security.get("auth_gaps")
        or migration_warnings
    )
    if has_critical:
        print("[FAIL] Critical issues found — address the suggestions in the review comment above.")
        sys.exit(1)

    print(f"[PASS] Score: {score}/100 — PR looks good!")


if __name__ == "__main__":
    main()
