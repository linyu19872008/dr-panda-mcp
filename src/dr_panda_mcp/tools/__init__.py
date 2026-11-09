"""MCP 排查工具。"""

from __future__ import annotations

from fastmcp import FastMCP

from dr_panda_mcp.runtime import Runtime
from dr_panda_mcp.tools.data import register_data_tools
from dr_panda_mcp.tools.jenkins import register_jenkins_tools
from dr_panda_mcp.tools.logs import register_logs_tools
from dr_panda_mcp.tools.messages import register_message_tools
from dr_panda_mcp.tools.nacos import register_nacos_tools
from dr_panda_mcp.tools.system import register_systems_status


def register_tools(server: FastMCP, runtime: Runtime) -> None:
    register_systems_status(server, runtime)
    register_logs_tools(server, runtime)
    register_message_tools(server, runtime)
    register_data_tools(server, runtime)
    register_nacos_tools(server, runtime)
    register_jenkins_tools(server, runtime)


__all__ = ["register_tools"]
