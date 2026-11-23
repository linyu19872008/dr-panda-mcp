# Connector rules

Use the runtime `scope` and `capabilities` from `systems_status` as the source
of truth. The names below explain what the fields mean; never assume a
selector is authorized just because a tool accepts it.

## MySQL

- Scope: `default_db`, `allowed_dbs`; an empty `allowed_dbs` means “default_db
  only”.
- Discover with `mysql_tables` then `mysql_describe` before `mysql_query`.
- `mysql_query` accepts one read-only statement and adds a LIMIT; it rejects
  system schemas, writes, DDL, locking reads, `EXPLAIN ANALYZE`, and dangerous
  functions.
- `mysql_processlist` is opt-in through `allow_processlist`; it can expose other
  sessions and SQL text. Summarize, do not dump.
- `mysql_explain` is for a plan only; it does not execute the query.

## MongoDB

- Scope: `allowed_dbs` (explicit list).
- `mongo_collections` then `mongo_find`; a filter is required.
- Allowed aggregation stages: `$match`, `$project`, `$group`, `$sort`, `$limit`,
  `$lookup`. `$group`/`$lookup` require a preceding `$match`.
- No `$out`, `$merge`, `$where`, `$function`, `$accumulator`, `allowDiskUse`,
  or index hints.
- Use `mongo_stats` for collection/database stats and index information.

## Elasticsearch

- Scope: `allowed_indices`; wildcards and `_all` are rejected.
- `es_mapping` before `es_search`; use `es_health` for cluster state.
- `es_search` takes a JSON `query` string, a bounded `size`, optional `sort` and
  `search_after`. `from + size` must not exceed 10000.
- No scripts, `script_fields`, `runtime_mappings`, or `track_total_hits=true`.
- Aggregations are restricted to bounded `terms` aggregations.

## Redis

- Scope: `key_prefix`; every key and scan pattern must start with it.
- `redis_scan` is cursor-based and `COUNT` must be at most 200.
- `redis_get` returns type, TTL, and bounded content; large strings and
  collections are rejected rather than dumped.
- `redis_info` accepts an optional section; `redis_slowlog` returns a bounded
  number of entries.
- No `KEYS`, no unbounded `LRANGE`/`ZRANGE`, no write commands.

## GitLab

- Scope: `allowed_projects` and authorized branches; `GET` only.
- `gitlab_search_code` searches blobs; then `gitlab_get_file` and
  `gitlab_blame` for the hit.
- Use the project path or ID exactly as returned in scope; do not invent a
  namespace.

## CLS (Tencent Cloud Log Service)

- Scope: `allowed_topics`; entries are `logsetId/topicId` UUIDs, not friendly
  topic names.
- `cls_search` requires `query`, `topic`, `from`, and `to`; use a short window
  (30–60 minutes) and `sort=desc` by default.
- `stats.next_context` is passed back as `context` for the next page; do not
  combine `context` with `offset`.
- A full window is at most 24 hours. A `| SELECT` query returns analysis rows
  and `stats.mode=analysis`.
- `cls_context` uses identifiers from a search hit; do not invent them.

## RabbitMQ

- Scope: `allowed_vhosts`; use only queues and vhosts visible in that scope.
- Management API `GET` only: `rabbit_queues` and `rabbit_queue`.
- Do not publish, purge, or change policies.

## Kafka

- Scope: `allowed_topics` (and authorized partitions).
- `kafka_lag` reads a consumer group's committed offsets; `kafka_offsets`
  reads low/high watermarks; `kafka_peek` fetches a bounded sample from one
  partition.
- DrPanda never joins a consumer group, commits offsets, or produces messages.
- `kafka_peek` is capped at 10 records per call; page with a later offset if
  needed.

## Nacos

- Scope: `allowed_namespaces`, `allowed_groups`, `allowed_data_ids`,
  `allowed_services`, plus `data_scope` and `service_scope`.
- `nacos_configs` lists metadata; `nacos_config` reads one dataId.
- `nacos_services` lists services; `nacos_instances` lists instances for one
  service.
- Pass `namespace` and `group` when more than one is authorized. Keep
  `page_size` small (1–20) when a list is large.

## Jenkins

- Scope: `allowed_jobs`, `allowed_nodes`, and the opt-in `allow_console`.
- `jenkins_jobs` lists jobs; `jenkins_job` gives the job and its last builds,
  including `last_failed_build` and `last_successful_build`.
- `jenkins_builds` lists recent builds; `jenkins_build` needs
  `build_number`; `jenkins_console` also needs `build_number` and the target's
  console permission.
- `jenkins_nodes` and `jenkins_queue` are read-only summaries. An empty
  `allowed_nodes` means node reads are denied.
