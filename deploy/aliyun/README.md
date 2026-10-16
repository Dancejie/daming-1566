# 大明1566 阿里云运行时迁移

基于远端已发布 main `c9e738185694ffeb81a53b6485dd84b68496c052`，不修改故事、人物或已批准媒体。

- OSS 前缀 `/daming/`，推荐主入口 `/daming/original/index.html`。保留风暴初夜和名场面入口。
- API 反代前缀 `/daming-api/`，容器内部 `8019`、UID/GID `10001`、单服务进程。
- 独立持久卷 `/data`，两个 SQLite 分别为 `/data/original/runs.sqlite3` 与 `/data/storm/runs.sqlite3`。
- 部署固定环境：`DAMING_DATA_DIR=/data`、`DAMING_EXTERNAL_MEDIA=verified-oss-release`、`DAMING_ALLOWED_ORIGIN=https://app.echodrama.cn`、`DAMING_STATIC_BASE=https://app.echodrama.cn/daming`；`DAMING_RELEASE` 可设源版本。
- 名场面对话继续使用现有 `DEEPSEEK_API_KEY` 和原模型设置。密钥只在服务器私有环境，不在包内。原 Render 的实时 GPT-SoVITS 未运行，迁移保留已有原声音频，不承诺新增本不存在的推理服务。

导出命令（必须使用不存在的新输出路径，不覆盖源）：

```sh
python3 deploy/aliyun/export-release.py \
  --output /tmp/.work-daming-oss-release \
  --api-base https://47-82-84-228.sslip.io/daming-api \
  --backend-out /tmp/daming-backend-release.tar.gz
```

导出只允许运行时文件：111 个 OSS 对象，约 144.6 MiB；后端约 56 KiB，不含数据库、凭据、原始制作材料或模型。上传需要逐项应用 `upload-manifest.json` 的类型、缓存和 SHA-256，依赖文件先于入口 HTML 发布。后端媒体可用性开关只在这份完整 OSS 包发布后使用。

## 存档边界

原著篇和风暴初夜的服务端存档在独立 SQLite 中持续保存；浏览器仍留完整动作记录用于恢复。新站的“存档迁移”支持下载 JSON、校验导入；导入重放在服务器完成，成功后才替换当前指针，原指针保存为 `before-import`。不同篇章不互相导入。

跨域不会自动带走旧 Render 的 localStorage。旧 Render 保持原样供继续游玩；可在原设备使用菜单提供的本地导出书签，再回新站导入。书签仅读取两个剧情 namespace，不读取连接设置或 API Key，不联网。若玩家没有原设备/浏览器动作记录，不能承诺找回旧档。经典名场面旧版原本只有当前页内进度，不把它声称为已具备服务端存档的模式。

## 已运行验证

`original/qa/test_original.py`：6；`film/qa/test_restore.py`：6（另 1 浏览器测试跳过）；`film/qa/test_engine.py`：9；`qa/test_aliyun.py`：3。覆盖原著四种结局、旧篇章隔离、动作日志恢复、双篇章真实进程重启存档一致、精确跨域白名单、运行时与私有路由。合成测试后端 RSS 约 19.1 MiB；建议共享主机先使用 192 MiB 容器上限并实测并发，不据此保证任意负载。

`node qa/test_cloud_frontend.cjs <输出目录>`：111 个文件 SHA、API/媒体路径、JSON 导入导出、备份指针与旧档书签无密钥导出均通过。公网浏览器/OSS/真实模型请求仍由发布阶段单独验证，未跑付费模型。
