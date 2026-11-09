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

## Jenkins

- [ ] 认证探活通过（API Token 优先）
- [ ] `jenkins_jobs` 只返回 `allowed_jobs`
- [ ] `jenkins_job` 返回最近构建状态
- [ ] `jenkins_builds` / `jenkins_build` 能读取构建结果和参数
- [ ] `allow_console=true` 时 `jenkins_console` 截断读取日志；false 时返回 `SCOPE_DENIED`
- [ ] `jenkins_nodes` 只返回 `allowed_nodes`
- [ ] `jenkins_queue` 只显示授权 Job 的排队项
- [ ] 越权 job/node → `SCOPE_DENIED`
- [ ] 多级文件夹 Job（`folder/sub/job`）可用
- [ ] Queue 非空时返回等待原因
- [ ] 反向代理 + TLS 可访问
- [ ] 原生 TLS + CA 可访问
- [ ] header-based SSO：记录为不兼容或使用受控代理身份

## Nacos

- [ ] 探活通过（v1 配置列表或 v3 登录/配置读取验证认证与 namespace/group）
- [ ] `api_version=auto` 对 2.2.3 识别为 v1、对 3.0.2 识别为 v3
- [ ] Nacos 3.x `nacos_config` 通过 v3 client API 读取内容
- [ ] Nacos 3.x `nacos_configs` 只返回 `allowed_data_ids` 内的 dataId
- [ ] Nacos 3.x `nacos_services` 只返回 `allowed_services`
- [ ] `data_scope=all` 时 `nacos_configs` 返回 namespace/group 下全部配置
- [ ] `data_scope=selected` 时 `nacos_configs` 只返回 `allowed_data_ids`
- [ ] `nacos_config` 读取内容正确
- [ ] `service_scope=all` 时 `nacos_services` 返回全部服务
- [ ] `service_scope=selected` 时 `nacos_services` 只返回 `allowed_services`
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
