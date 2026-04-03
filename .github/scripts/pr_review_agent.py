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

# Fetch tokens securely from environment variables
try:
    GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
    GH_MODELS_TOKEN = os.environ["GH_MODELS_TOKEN"]
except KeyError as e:
    raise RuntimeError(f"Missing required environment variable: {e.args[0]}")

PR_NUMBER = os.environ.get("PR_NUMBER")
REPO_FULL_NAME = os.environ.get("REPO_FULL_NAME")

if not PR_NUMBER or not REPO_FULL_NAME:
    raise RuntimeError("PR_NUMBER and REPO_FULL_NAME environment variables must be set.")

GITHUB_API = "https://api.github.com"
GH_HEADERS = {
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
4. gRPC — no p