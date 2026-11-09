"""九类排查组件的连接器注册表。"""

from __future__ import annotations

from dr_panda_mcp.connectors import (
    cls as cls_connector,
)
from dr_panda_mcp.connectors import (
    es,
    gitlab,
    kafka,
    mongo,
    mysql,
    rabbit,
    redis,
)
from dr_panda_mcp.connectors import jenkins as jenkins_connector
from dr_panda_mcp.connectors import nacos as nacos_connector
from dr_panda_mcp.connectors.base import Connector

CONNECTORS: dict[str, Connector] = {
    connector.name: connector
    for connector in (
        mysql.connector,
        mongo.connector,
        es.connector,
        redis.connector,
        gitlab.connector,
        rabbit.connector,
        kafka.connector,
        cls_connector.connector,
        nacos_connector.connector,
        jenkins_connector.connector,
    )
}


def get_connector(target_type: str) -> Connector:
    """按目标类型取连接器；未知类型抛 ``KeyError``。"""
    return CONNECTORS[target_type]


def connector_names() -> list[str]:
    return sorted(CONNECTORS)


__all__ = ["CONNECTORS", "Connector", "connector_names", "get_connector"]
