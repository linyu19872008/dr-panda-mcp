# 真实上游 E2E 验收清单

发版或变更连接器后，对已登记的生产/预发目标手工勾选。密钥不进 CI；本清单只做本地/堡垒机验证。

## CLS

- [ ] 目标探活绿灯（含每个 `allowed_topics` 的轻量 `SearchLog`）
- [ ] `systems_status` 中 `scope.allowed_topics` 为 `logsetId/topicId` UUID
- [ ] `cls_search` 窄窗查询返回非空 `content`
- [ ] `*| SELECT count(*) as c` 返回 `stats.mode=analysis` 且 rows 含聚合列
- [ ] 第一次 search 的 `stats.next_context` 可传给第二次 `context` 翻页
- [ ] `cls_context` 用 search 返回的 `package_id` / `btime` / `package_log_id` 能读到前后文
- [ ] 宽窗（>2h）+ `sort=desc` 时 notes 含 newest-first 提示

## Nacos

- [ ] 探活通过（配置列表读取验证认证与 namespace/group）
- [ ] `nacos_configs` 只返回 `allowed_data_ids`
- [ ] `nacos_config` 读取内容正确
- [ ] `nacos_services` 只返回 `allowed_services`
- [ ] `nacos_instances` 返回健康、端口、集群和 metadata
- [ ] 未授权 namespace/group/dataId/service → `SCOPE_DENIED`

## Kafka

- [ ] 探活通过
- [ ] `kafka_lag` 对授权 topic 有分区滞后数据
- [ ] `kafka_peek` 有限条消息，且未加入消费组、未提交 offset
- [ ] 未授权 topic → `SCOPE_DENIED`

## GitLab

- [ ] 探活通过
- [ ] `gitlab_search_code` 仅命中授权 project
- [ ] `gitlab_get_file` / `gitlab_blame` 在授权 project 内可读
- [ ] 越权 project → `SCOPE_DENIED`

## 通用

- [ ] `INTERNAL` / `UPSTREAM_*` 错误信息对 Agent 可见且不含密钥
- [ ] 结果截断时包络 `truncated=true` 且 notes 有说明
