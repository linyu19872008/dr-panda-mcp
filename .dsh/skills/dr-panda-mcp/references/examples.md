# Short transcripts

These are examples of the expected level of evidence, not scripts to paste
verbatim. Replace target names, windows, and selectors with values from
`systems_status`.

## 1. 5xx spike with a trace id

```text
User: Orders API is returning 502s since about 10:05 UTC. Trace id is abc123.

Agent:
1. systems_status()
   -> environments: [{key: "prod", title: "Production", ...}]
2. systems_status(environment="prod")
   -> targets: orders-cls (cls), orders-gitlab (gitlab), orders-mysql (mysql)
      scope.allowed_topics = ["<logsetId>/<topicId>"] on orders-cls
3. cls_search(
     target="orders-cls",
     topic="<logsetId>/<topicId>",
     query="trace_id:abc123",
     from="2026-11-23T09:50:00Z",
     to="2026-11-23T10:20:00Z",
     limit=50
   )
   -> 12 rows; stats.next_context = "<cursor>"; truncated=false
   -> one error row: NullPointerException in OrderMapper.toDto
4. gitlab_search_code(
     target="orders-gitlab",
     project="group/orders",
     query="NullPointerException OrderMapper.toDto"
   )
   -> 1 hit: src/main/java/.../OrderMapper.java
5. gitlab_get_file(
     target="orders-gitlab",
     project="group/orders",
     path="src/main/java/.../OrderMapper.java",
     ref="main"
   )
   -> file content; truncated=false

Agent report:
Environment: prod (Production)
Target: orders-cls / orders-gitlab
Window: 2026-11-23T09:50:00Z to 2026-11-23T10:20:00Z
Evidence: 12 matching log rows; one NPE at OrderMapper.toDto; code path confirmed.
Assessment: fact = NPE in the mapper; hypothesis = null shippingAddress is not
guarded. Missing: the upstream request payload.
Next: check the request payload or the caller that builds ShippingAddress.
```

## 2. Slow SQL

```text
User: The order list endpoint is slow since the deploy.

Agent:
1. systems_status(environment="prod") -> orders-mysql scope:
   allowed_dbs=["orders"], default_db="orders"
2. mysql_tables(target="orders-mysql", db="orders")
   -> orders, order_items, ...
3. mysql_describe(target="orders-mysql", table="orders", db="orders")
   -> columns and indexes
4. mysql_explain(
     target="orders-mysql",
     sql="SELECT id, status FROM orders WHERE user_id = 42 ORDER BY created_at DESC LIMIT 20"
   )
   -> type=ALL, key=NULL, rows=~1,200,000
5. mysql_query(
     target="orders-mysql",
     sql="SELECT id, status FROM orders WHERE user_id = 42 ORDER BY created_at DESC LIMIT 20",
     limit=20
   )
   -> 20 rows; truncated=false

Agent report:
Evidence: the plan shows a full scan on orders for user_id; the bounded sample
returns 20 rows.
Assessment: the predicate has no usable index; this is a fact from the plan.
Missing: whether a new index was removed in the deploy.
Next: compare the migration history or ask the owner; do not change the schema.
```

## 3. Kafka lag

```text
User: The billing consumer is behind.

Agent:
1. systems_status(environment="prod") -> billing-kafka scope:
   allowed_topics=["billing.events"]
2. kafka_lag(target="billing-kafka", group="billing-worker", topic="billing.events")
   -> partitions 0..5; partition 3 lag=182,340; others < 100
3. kafka_offsets(target="billing-kafka", topic="billing.events")
   -> partition 3 low=..., high=...
4. kafka_peek(
     target="billing-kafka",
     topic="billing.events",
     partition=3,
     offset=<committed>,
     limit=5
   )
   -> 5 records; timestamps and keys; truncated=false

Agent report:
Evidence: lag is isolated to partition 3; the sampled records are from the
expected topic and carry normal keys.
Assessment: one partition is stuck or slow, not the whole topic.
Missing: consumer instance logs for partition 3.
Next: inspect the consumer's logs for that partition; do not commit offsets.
```
