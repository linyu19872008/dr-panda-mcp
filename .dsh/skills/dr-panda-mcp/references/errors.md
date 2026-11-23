# Error recovery

DrPanda returns tool errors as `CODE: message`. Read the code first, then the
message and any `allowed:` list. Change one dimension of the request; do not
repeat the same call.

| Code | Meaning | Action |
|---|---|---|
| `ENVIRONMENT_REQUIRED` | More than one environment is registered and the call omitted one | Call `systems_status()` and pass the environment `key` |
| `ENVIRONMENT_NOT_FOUND` | The environment key is not registered | Use the key from `systems_status()`; do not use the display title |
| `ENVIRONMENT_DISABLED` | The environment exists but is disabled | Report it and ask the operator; do not retry |
| `TARGET_NOT_FOUND` | The target name is not registered in that environment | Call `systems_status(environment=...)`; do not guess |
| `TARGET_DISABLED` | The target exists but is disabled | Report it; do not retry |
| `TARGET_TYPE_MISMATCH` | The tool does not match the target's component type | Use a tool for the target's actual `type` |
| `SECRET_UNAVAILABLE` | The target's secret cannot be decrypted | Ask the operator to re-enter it; do not guess |
| `SCOPE_DENIED` | A selector, tool, or capability is outside the target scope | Use a value from `allowed: …`; if a tool is disabled, choose an allowed tool |
| `INVALID_ARGUMENT` | A parameter is missing, malformed, or out of range | Fix the named parameter using the hint |
| `GUARD_REJECTED` | The request is not on the read-only whitelist | Rewrite as a read-only request; do not try to bypass |
| `DANGEROUS_OPERATION` | The request is too costly, unsafe, or state-changing | Narrow the range/window/limit; do not retry the same request |
| `UPSTREAM_TIMEOUT` | The tool deadline expired, including queue time | Shrink the time window or row count; tell the user the target may be busy |
| `UPSTREAM_NOT_FOUND` | The upstream object does not exist | Discover the database, index, topic, queue, project, job, or collection first |
| `UPSTREAM_UNAVAILABLE` | The upstream is unreachable or returned an unexpected response | Report the target and request id; ask the operator; do not invent data |
| `UPSTREAM_QUERY_ERROR` | The upstream rejected the query or payload | Correct the query/selector; check schema or mapping first |
| `UPSTREAM_AUTH` | The upstream rejected the registered credentials | Ask the operator to update the target secret; do not retry blindly |
| `STORAGE_UNAVAILABLE` | The DrPanda config store is unavailable | Report it; retry once only if the user asks; do not fabricate results |
| `INTERNAL` | An unexpected DrPanda error | Report the error and request id; do not fabricate a conclusion |

## Retry rules

1. A rejected call is not a transient error. Read the hint before changing
   anything.
2. For `SCOPE_DENIED`, the error usually contains `allowed: …`; use one of those
   values or a different tool.
3. For `DANGEROUS_OPERATION`, make the request smaller: a shorter window, a
   narrower filter, a lower limit, or a less expensive aggregation.
4. For `UPSTREAM_TIMEOUT`, reduce one dimension at a time. Do not retry the same
   request without a change.
5. For `UPSTREAM_UNAVAILABLE` or `UPSTREAM_AUTH`, retrying usually repeats the
   same failure. Report and hand off.
6. Never turn an error into “no data found”. Say the call failed and why.

## Useful distinctions

- `truncated: true` is not an error; it means the result was cut by a row or
  byte limit. Report it and page or narrow.
- `SCOPE_DENIED` for a disabled tool lists the tools you may use. The tool can
  still appear in the schema; that does not mean it is enabled.
- `DANGEROUS_OPERATION` is the server protecting the upstream; it is not a
  challenge to work around.
