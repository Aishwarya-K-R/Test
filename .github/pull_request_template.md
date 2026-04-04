## Description
<!-- What does this PR do? Why is it needed? -->


## Type of Change
- [ ] Bug fix
- [ ] New feature / service
- [ ] Refactoring (no functional change)
- [ ] Configuration / infrastructure change
- [ ] Documentation

---

## Checklist

### Code Quality
- [ ] Code compiles without warnings (`dotnet build`)
- [ ] No `Console.WriteLine` — use Serilog structured logging
- [ ] No hardcoded secrets, connection strings, or API keys
- [ ] Async methods use `await` correctly (no `.Result` / `.Wait()` blocking calls)
- [ ] New public methods have appropriate XML doc comments

### Security & PHI
- [ ] Patient data (PHI) is not logged, exposed in error messages, or returned in unauthorized responses
- [ ] New endpoints are protected with `[Authorize]` where required
- [ ] No raw SQL queries — all DB access goes through `AppDbContext`
- [ ] Rate limiting is applied to any new public-facing endpoints

### Security Checks
- [ ] No PHI exposure or hardcoded secrets
- [ ] [Authorize] added to new endpoints where required

### Database / EF Core
- [ ] Model changes include a new EF Core migration (`dotnet ef migrations add`)
- [ ] Migration has been reviewed for unintended schema changes
- [ ] No N+1 query patterns (use `.Include()` / projections)

### Kafka
- [ ] New consumers handle deserialization errors and log via Serilog
- [ ] Consumer group IDs are unique per service
- [ ] New topics are registered in `KafkaTopicCreator.cs`

### gRPC / Protos
- [ ] Proto changes are backward compatible (no field removals, no reused field numbers)
- [ ] Both client and server stubs are regenerated if `.proto` files changed

### Docker / Kubernetes
- [ ] New service has a `Dockerfile.*` with multi-stage build
- [ ] New service is added to `docker-compose.yml` with health check
- [ ] New service has K8s Deployment + Service YAML in `/Kubernetes/`
- [ ] No secrets hardcoded in Dockerfiles or K8s manifests (use ConfigMap/Secrets)

### Observability
- [ ] New service exposes `/health` endpoint
- [ ] Prometheus scrape target added to `prometheus.yml` if applicable
- [ ] New service is added to Serilog file sink config

### Tests
- [ ] New business logic has unit tests in `PMS.Tests/`
- [ ] Tests pass locally (`dotnet test`)
- [ ] No tests are skipped without a `// TODO:` explanation

---

## Screenshots / Evidence
<!-- For API changes: attach .http file test results or Swagger screenshots -->