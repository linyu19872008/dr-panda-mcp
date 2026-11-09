# Changelog

[English](CHANGELOG.md) · [简体中文](CHANGELOG.zh-CN.md)

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.9.1] - 2026-11-10

### Fixed

- Nacos connector facade: `nacos_configs` / `nacos_config` / `nacos_services` / `nacos_instances` no longer raise `AttributeError` at runtime.
- MySQL empty `allowed_dbs` now means "default_db only", matching the web form help text.
- Nacos form validation aligns legacy missing scope modes with connector defaults; `api_version=v3` rejects `data_scope`/`service_scope=all`.
- Target list endpoint/scope summaries now cover Nacos and Jenkins; scope-only edits skip probe for those types.

### Changed

- Jenkins tools now call connector facades (`connector.jobs(...)` etc.), matching the other connectors.
- Added a contract test so tools `connector.*` calls must exist on real connectors.

## [1.9.0] - 2026-11-10

### Added

- Nacos `data_scope` and `service_scope` modes: `all` or `selected`.
- New Nacos targets default to `all` within authorized namespaces/groups; legacy targets without a mode remain `selected`.
- Multi-namespace/group Nacos probes now select an authorized scope instead of failing with "namespace is required".
- v1 config/service listing supports all-scope mode; Nacos 3 all-scope listing reports its OpenAPI limitation explicitly.

## [1.8.0] - 2026-11-09

### Added

- Per-target `operator_notes` (up to 512 characters), exposed in full by `systems_status` and target-specific tool results.
- Advisory-only semantics: notes never change authorization scope, read-only rules, or guard decisions.
- Web form field with length validation and secret-handling warning; migration adds `targets.operator_notes`.

### Verified

- Store create/get/update, bounded length validation, migration, `systems_status`, and tool envelope coverage.

## [1.7.0] - 2026-11-09

### Added

- New read-only `jenkins` target type using the Jenkins REST API.
- Tools for jobs, job details, recent builds, build details, bounded console logs, nodes and queue.
- API token authentication, TLS CA, exact job/node allowlists, optional console access and bounded build/log sizes.
- Real Jenkins 2.541.3 Docker verification (Basic auth, API token, job, build, console, node, queue).

## [1.6.0] - 2026-11-09

### Added

- Nacos 3.x support through a v3 client adapter; v1 and v3 endpoints are selected automatically or via `api_version`.
- v3 config reads, scope-derived config listing, scope-derived service listing and v3 instance discovery.
- `api_version` (`auto` / `v1` / `v3`) target option.
- Nacos 3.0.2 Docker verification and Nacos 2.2.3 regression coverage.

## [1.5.1] - 2026-11-09

### Fixed

- Nacos accessToken caching no longer exceeds short server TTLs; the refresh margin is capped below the issued token lifetime.

### Verified

- Nacos 2.2.3 auth: default and custom users, namespace/group ACL, wrong-password classification.
- Nacos 1.4.2 auth.
- TLS termination + Nacos auth.
- Nacos 3.0.2 v3 auth/API differences; v3 is documented as unsupported by the current v1 connector.

## [1.5.0] - 2026-11-09

### Added

- New read-only `nacos` target type: config metadata/content, service list and instance discovery through Nacos OpenAPI.
- Scope is expressed as `allowed_namespaces`, `allowed_groups`, `allowed_data_ids` and `allowed_services`; empty data/service scopes deny access.
- Nacos username/password login, accessToken caching, TLS CA and health probe support.
- `systems_status`, the web form and MCP instructions expose the Nacos scope.
- Real Docker Nacos 2.2.3 integration verification and E2E checklist entries.

## [1.4.0] - 2026-11-08

### Added

- CLS form validation requires `logsetId/topicId` UUIDs; friendly topic names are rejected at save time.
- CLS probe now runs a one-minute `SearchLog` against each authorized topic after `DescribeLogsets`.
- `cls_search` supports analysis queries (`| SELECT`), returns `stats.mode` / `stats.next_context`, and accepts optional `sort`, `context`, `merge_packages`, and `compact`.
- Wide-window `cls_search` (desc, >2h) adds a newest-first note so agents shrink the window around an incident time.
- Tool annotations now include `destructiveHint=false`, `idempotentHint=true`, and `openWorldHint=true`.
- Upstream E2E checklist: `docs/zh-CN/verify/upstream-e2e-checklist.md`.

### Changed

- MCP `SERVER_INSTRUCTIONS` and CLS tool docs spell out TopicId UUIDs, narrow windows, paging via `context`, and analysis mode.
- `systems_status` notes remind that CLS `allowed_topics` are UUID pairs.
- `INTERNAL` tool errors (including `systems_status`) now include a short redacted exception message for agents.

## [1.3.3] - 2026-11-08

### Fixed

- CLS `SearchLog` result content now prefers `LogJson`/`RawLog`. Reading only `Log`/`Content` left `cls_search` rows with empty `content`.

## [1.3.2] - 2026-11-08

### Fixed

- CLS search result `Time`/`BTime` values in milliseconds are converted to seconds before formatting. Previously `datetime.fromtimestamp` overflowed and `cls_search` failed with an internal `ValueError`.

## [1.3.1] - 2026-11-08

### Fixed

- CLS `SearchLog` now sends `From`/`To` as Unix timestamps in milliseconds, matching the Tencent Cloud API contract. The previous seconds values were interpreted as 1970 and returned zero logs.
- Updated the fake CLS SDK and regression assertion for the 13-digit millisecond request values.

## [1.3.0] - 2026-11-08

### Added

- `systems_status` target rows now include a non-secret `scope` object with authorized selectors:
  - MySQL/Mongo: `allowed_dbs`, `default_db`
  - Elasticsearch: `allowed_indices`
  - Redis: `key_prefix`
  - RabbitMQ: `allowed_vhosts`
  - Kafka/CLS: `allowed_topics`
  - GitLab: `allowed_projects`
- MCP instructions and the investigation prompt now require using scope values when choosing database/index/topic/vhost/project/key arguments.

## [1.2.5] - 2026-11-07

### Fixed

- CLS client construction no longer passes the unsupported `timeout` keyword to `ClsClient`; it configures `HttpProfile.reqTimeout` through `ClientProfile`, compatible with the current Tencent Cloud SDK.
- CLS probe/search/context initialization errors are wrapped as upstream failures with the exception type and message.
- Added the Tencent region example hint (`ap-shanghai`) to the CLS form.

## [1.2.4] - 2026-11-07

### Fixed

- HTTP connector responses with `Content-Encoding: gzip` (notably Elasticsearch) were decompressed by httpx and then decompressed again when the sanitized `httpx.Response` was rebuilt, producing `Error -3 while decompressing data: incorrect header check`.
- The sanitized response now drops `content-encoding`, `content-length`, and `transfer-encoding`, while preserving decoded content and other headers.
- Added gzip regression coverage for `stream_http` and Elasticsearch ping.

## [1.2.3] - 2026-11-07

### Fixed

- The target form's Install client button was bound to the external hidden install form's button lookup, so `doInstall()` returned early and no request was sent. The button is now looked up from the main form.

## [1.2.2] - 2026-11-07

### Fixed

- `setup.sh service` now ensures the current `uv` binary is copied to `/usr/local/bin` before writing the unit, including when `uv` is only under `/root/.local/bin`.

## [1.2.1] - 2026-11-07

### Fixed

- One-click client installation could not run from the hardened systemd service: the service did not have `uv` on PATH, had no writable uv cache, and `ProtectSystem=strict` blocked `.venv` updates.
- The generated unit now copies `uv` to `/usr/local/bin`, sets `UV_CACHE_DIR` under `data/`, and allows writes to the existing `.venv`/`uv.lock` only.

## [1.2.0] - 2026-11-07

### Added

- New/edit target forms now offer the same one-click client installation as the target list, for every optional target client (`mysql`, `mongo`, `redis`, `kafka`, `cls`).
- Probe responses expose a structured `install_extra`; the form shows an install action, installs the fixed extra, and automatically retries the connection.
- New `POST /targets/install-client` endpoint for unsaved target forms; it accepts only a target type and derives the fixed extra server-side.
- Install failures are surfaced without exposing the raw `uv sync` command.

## [1.1.3] - 2026-11-07

### Fixed

- Login page language/theme switches were blocked by authentication when logged out, redirecting to `/login?next=/language`; after login the browser then issued `GET /language` and received 405.
- `/language` and `/theme` are now public cookie-only routes.
- Login `next` no longer accepts POST-only routes, and unauthenticated non-GET requests do not preserve their POST path as the post-login landing page.

## [1.1.2] - 2026-11-07

### Fixed

- MySQL migration 0007 failed at `batch.alter_column` because MySQL requires the existing column type for `CHANGE/MODIFY COLUMN`. The migration now passes `existing_type` and `existing_nullable`.
- Added a real MySQL/PostgreSQL first-install integration check that runs the full SetupApp flow, pages, schema checks and an idempotent re-migration.
- Added a CI job with MySQL 8.0 and PostgreSQL 16 service containers.

## [1.1.1] - 2026-11-07

### Fixed

- MySQL first-install migration failed because `key` is a reserved word in migration `0007_environments`. The migration now uses SQLAlchemy expressions, so identifiers are quoted per dialect.
- Added regression tests that compile the environment lookup/insert for the MySQL dialect.

## [1.1.0] - 2026-11-06

### Added

- Deployment helper `scripts/setup.sh` with `check`, `install`, `service`, `start`, `status` and `upgrade`.
- Source (`git + uv sync`) and PyPI (`uv tool install`) installation methods.
- systemd unit for a dedicated `drpanda` user, with sandboxing and health-checked startup.
- Automatic Python selection (system Python >=3.11 first; shared `/opt/uv-python` fallback), `--no-dev` production installs, and optional PyPI/python mirrors.
- Preflight and post-install checks for interpreter accessibility, service-user execution and systemd unit validity.

### Changed

- Repository renamed from `DrPanda` to `dr-panda-mcp` for consistency with the package and CLI.
- Documentation defaults to English under `docs/`; Chinese docs live under `docs/zh-CN/`.

### Fixed

- systemd unit path directives no longer use quotes.
- Service startup failures are reported instead of being treated as success.

## [1.0.0] - 2026-11-06

### Added

- Read-only MCP service for MySQL, MongoDB, Elasticsearch, Redis, GitLab, RabbitMQ, Kafka and CLS.
- Web console for target registration, connection tests, encrypted secrets, environments and MCP tokens.
- First-run setup wizard, login sessions, CSRF protection, login lockout and MCP bearer tokens.
- Audit log with outcome/failure details, filters and retention cleanup.
- System settings for target defaults, concurrency, audit maintenance, session/token limits and backup retention.
- Automatic loading of `./.env`, strict permission/format validation and environment-variable precedence.
- English is the default language for the web UI, MCP, CLI and documentation; Chinese docs live under `docs/zh-CN/`.
- GitHub open-source documentation: bilingual README, contribution/security/conduct policies, issue/PR templates and CI.

### Security

- Absolute read-only guards plus dangerous/high-cost operation rules; target scope limits.
- Encrypted target secrets and hashed MCP tokens; no credentials in logs or audit.
- Configurable Cookie Secure policy and optional MCP host allowlist.

### Notes

- Kafka, CLS and GitLab tools are implemented and unit-tested but not end-to-end verified against real upstreams.
- Reverse-proxy HTTPS/TLS deployment still requires environment-specific validation.
