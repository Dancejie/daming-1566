# 浏览器动作存档恢复验收

2026-09-16，独立发布克隆；未修改 8156 原项目，未提交或部署。

## 实现

- 新存档记录服务端确认的 `actionLog`，含 advance、choice、自由输入预览/确认及 QTE；日志只含动作所需字段。
- 本机保存同一命名空间下的 `checkpoint.<runId>`；续写先 GET，只有 HTTP 404 才提交版本与动作序列恢复。
- 引擎从剧本初始状态重新执行，全部校验成功后以新 runId 入库；不接收客户端 state/stats/receipt/revision。
- 恢复支持当前及显式兼容版本；限 100 次提交、20,000 UTF-8 字节。无 checkpoint、坏版本和非法序列明确报错。
- 网络失败、HTTP 500 不恢复、不自动另开；未收到服务端确认的动作不会写入 checkpoint。原有 requestId 去重仍有效。
- 封面增加“原版名场面” `/classic/` 链接。

## 验证

`python3 -m unittest discover -s film/qa -p test_engine.py -v`：9 项通过。

`MING_RESTORE_BROWSER=1 NODE_PATH=<Playwright 模块目录> python3 -m unittest discover -s film/qa -p test_restore.py -v`：7 项通过。

- 初始状态、选择收条、自由输入待确认及完整结局重放一致：state/history/receipt/proposal/actionLog 等一致，仅 runId 更新。
- 兼容版本迁移到当前版本，非法/越限/篡改状态及末尾非法动作均不入库。
- 相同 requestId 重试只记录一次动作；额外客户端 stats 不影响权威状态。
- 真实 Chrome：预览 checkpoint 已保存；404 后恢复相同 proposal 和状态；network/500/缺少 checkpoint 均未误开新档。
- `node --check film/frontend/app.js` 与 QA 脚本语法检查通过。

测试使用临时 SQLite、独立动态端口及全新浏览器上下文，退出已清理。无截图或媒体副本。CI 默认跳过需 Playwright 的浏览器项，其余恢复测试可直接 discover。
