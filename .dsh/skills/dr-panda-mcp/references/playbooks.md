# Incident playbooks

Use these flows after `systems_status` has given you the environment key, the
target name, its `scope`, and its `capabilities`. Replace `<env>`, `<target>`,
and `<time>` with real values from the runtime response; never use the
placeholders literally.

Every flow starts narrow and widens one dimension at a time.

## 1. Error or 5xx spike

1. `systems_status(environment="<env>")` to find the CLS, GitLab, and data
   targets in the affected environment.
2. `cls_search(topic="<logsetId/topicId>", query="<trace-id or exception>",
   from="<time-30m>", to="<time>")`.
   - Use a trace id when available; otherwise search the service name and a
     short window.
   - Read `stats.next_context` before widening; pass it back as `context`
     instead of repeating the same window.
3. `gitlab_search_code(project="<project>", query="<exception class or stack
   fragment>")`; then `gitlab_get_file` and `gitlab_blame` for the hit.
4. Only if the evidence points to state: `mysql_query`, `mongo_find`, or
   `redis_get` with a specific key or filter.
5. Stop with a log slice, the code path, and the first failing condition. Do not
   claim a root cause from a single log line.

## 2. Slow SQL or lock wait

1. `mysql_processlist` only if the target's capabilities enable it. It may expose
   other sessions; treat the output as sensitive and summarize it.
2. `mysql_tables(db="<db>")` then `mysql_describe(table="<table>", db="<db>")`.
3. `mysql_explain(sql="SELECT ...")`; do not use `EXPLAIN ANALYZE`.
4. `mysql_query(sql="SELECT ... WHERE ... LIMIT 50")` for a bounded sample.
5. If the plan shows a full scan, state the table, filter, and row estimate; do
   not attempt to change indexes or settings.

## 3. Cache miss, hot key, or expired data

1. `redis_scan(pattern="<key_prefix>:*", count=50)` inside the target's
   `key_prefix`.
2. `redis_get(key="<key>")` for type, TTL, and a bounded value.
3. `redis_info(section="memory")` or `redis_slowlog(count=10)` if the symptom is
   pressure or latency.
4. If the value is large or the key is a collection, report the type, TTL, and
   size instead of dumping it.

## 4. Kafka consumer lag

1. `kafka_lag(group="<group>", topic="<topic>")`.
2. `kafka_offsets(topic="<topic>")` to see low/high watermarks per partition.
3. `kafka_peek(topic="<topic>", partition=<n>, offset=<offset>, limit=5)` to
   inspect a bounded sample. This never joins a consumer group or commits.
4. Report the lagging partition, the committed offset, the high watermark, and
   the timestamp of the sampled messages.

## 5. RabbitMQ backlog

1. `rabbit_queues(vhost="<vhost>")`; if the vhost is the only one, it may be
   inferred from scope.
2. `rabbit_queue(vhost="<vhost>", queue="<queue>")` for depth, consumers, and
   message rates.
3. Do not publish, purge, or change policies; this is read-only.

## 6. Failed deploy

1. `jenkins_jobs()` and pick an authorized job name.
2. `jenkins_job(job="<job>")`; read `last_failed_build` and
   `last_successful_build`.
3. `jenkins_builds(job="<job>")` then
   `jenkins_build(job="<job>", build_number=<n>)`.
4. `jenkins_console(job="<job>", build_number=<n>)` only if `allow_console` is enabled
   and the result is bounded. Quote the first actionable lines, not the whole log.
5. Correlate the failed build with the GitLab commit or CLS deploy logs.

## 7. Nacos config or discovery drift

1. `nacos_configs(namespace="<ns>", group="<group>", page_size=20)` to find the dataId.
2. `nacos_config(data_id="<dataId>", namespace="<ns>", group="<group>")`.
3. `nacos_services(namespace="<ns>", group="<group>")` and
   `nacos_instances(service="<service>", namespace="<ns>", group="<group>")`.
4. If a byte limit is hit, reduce `page_size` (1–20) or narrow the namespace;
   do not request a larger target limit yourself.

## 8. Elasticsearch search anomaly

1. `es_health()` for cluster status.
2. `es_mapping(index="<index>")` before writing a query.
3. `es_search(index="<index>", query="<query-json>", size=20)` with a bounded
   `size`, an explicit time range in the query, and no scripts. `from + size` must stay at or below 10000.
4. `es_index_stats(index="<index>")` when the symptom is index size or document
   count.

## 9. MongoDB data mismatch

1. `mongo_collections(db="<db>")`; `mongo_stats(db="<db>",
   collection="<collection>")` for counts and indexes.
2. `mongo_find(db="<db>", collection="<collection>", filter="{...}",
   projection="{...}", limit=20)`. A filter is required.
3. `mongo_aggregate` only with a preceding `$match` before `$group` or
   `$lookup`; the tool appends a bound.
4. Do not use `$out`, `$merge`, `$where`, `$function`, or `$accumulator`.

## 10. Code path or blame

1. `gitlab_search_code(project="<project>", query="<exception or symbol>")`.
2. `gitlab_get_file(project="<project>", path="<path>", ref="<branch>")`.
3. `gitlab_blame(project="<project>", path="<path>", ref="<branch>")`.
4. Stop when you can point to the file and line range; do not fabricate line
   numbers if the file was truncated.
