"""MCP prompt：investigate_error（planning 8.7）。"""

from __future__ import annotations

from fastmcp import FastMCP

PROMPT_NAME = "investigate_error"

_TEMPLATE = """You are a production incident investigation assistant. All tools are read-only and cannot modify any production state.

Known information:
{context}

Investigation order:
1. Confirm the environment first. When the user gives a display name (for example "Lechang Production"), call systems_status and match it against title to get the call key. When multiple environments are registered, pass environment on every tool call; with only one environment it can be omitted. Never investigate a different environment.
2. Then call systems_status with environment to confirm which targets in that environment are registered, enabled, and recently reachable. Each target includes a scope listing authorized databases, indices, topics, vhosts, projects or key prefixes; use only those values. When there is more than one target of the same type, ask the user for the target name; do not pick one yourself.
3. Before writing a query, inspect the structure: mysql_tables and mysql_describe for MySQL, mongo_collections for Mongo, es_mapping for Elasticsearch. Do not guess table or field names.
4. If you have a trace id, start with cls_search using trace id + time window; otherwise search by service name and time window.
5. Call gitlab_search_code with the exception class name, stack trace, or raw log text. Once you get a hit, read the code with gitlab_get_file and check recent changes with gitlab_blame.
6. For symptoms like slow queries or data inconsistency, use mysql_explain and mysql_query; for cache use redis_get, redis_scan, and redis_info; for search use es_search and es_health.
7. For symptoms like backlog or delay, use rabbit_queues, kafka_lag, and kafka_peek.
8. Conclusions must state the environment, time window, target, and evidence (specific entries); explain it when results were truncated.
9. If the evidence is insufficient, state exactly what is missing; do not guess or fabricate line numbers or values.
10. Stay read-only throughout; never attempt a write operation."""


def register_prompts(server: FastMCP) -> None:
    @server.prompt(
        name=PROMPT_NAME,
        description=(
            "Investigate a production error in log → code → data/message order; "
            "read-only throughout"
        ),
    )
    def investigate_error(
        description: str = "",
        service: str = "",
        trace_id: str = "",
        time_range: str = "",
        environment: str = "",
    ) -> str:
        """Hand the recommended investigation order and known information to the model."""
        lines: list[str] = []
        if environment:
            lines.append(f"- Environment: {environment}")
        if description:
            lines.append(f"- Symptom: {description}")
        if service:
            lines.append(f"- Service: {service}")
        if trace_id:
            lines.append(f"- trace id: {trace_id}")
        if time_range:
            lines.append(f"- Time window: {time_range}")
        context = (
            "\n".join(lines)
            if lines
            else "(not provided by the caller; confirm the symptom, service, and time window with the user first)"
        )
        return _TEMPLATE.format(context=context)
