# 发布候选 PR 描述

## 标题

```text
docs(release): prepare reproducible session manager demo
```

## Summary

- add Windows PowerShell scripts for development, tests, smoke verification, security checks, and cleanup;
- add a production Compose override with loopback binding, read-only API filesystem, resource hardening, graceful shutdown, restart policies, and log rotation;
- replace the upstream-oriented README with project architecture, setup, API, evidence, security, and known limitations;
- document API examples, concurrency proof, remote deployment boundaries, troubleshooting, and the five-minute demo;
- extend CI with dependency, JavaScript, Compose, and secret/large-file checks.

## Verification

```text
.\scripts\test.ps1
.\scripts\security-check.ps1
.\scripts\smoke.ps1
docker compose -f compose.yaml -f compose.production.yaml config --quiet
```

## Evidence

- Phase 2: persistent session/run/message APIs and restart recovery;
- Phase 3: PostgreSQL-first SSE, heartbeat, live fan-out, and Last-Event-ID replay;
- Phase 4: per-session sandbox, cross-token rejection, concurrent runs, runtime recovery;
- Phase 5: real browser workflow with embedded noVNC and responsive frontend.

## Known limitations

- deterministic Fake Agent is used for the release-candidate execution path;
- the upstream Anthropic callback adapter is tested, but a real model-to-remote-sandbox tool bridge is not yet wired;
- authentication, ownership, audit, rate limiting, and the production same-origin VNC proxy remain future work;
- the local API has trusted access to the Docker socket and is not a hostile multi-tenant boundary.

## Reviewer checklist

- [ ] README clean-start commands work in PowerShell;
- [ ] frontend creates, runs, restores, and stops a session without terminal interaction;
- [ ] SSE events are ordered and replay correctly;
- [ ] two sessions have different runtime IDs and VNC channels;
- [ ] test, security, and smoke scripts pass;
- [ ] no secret or private data appears in commits or screenshots.
