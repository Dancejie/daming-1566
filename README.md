# 大明1566 · 风暴初夜

公网产品：<https://daming-1566.onrender.com/>。

六场互动剧情、四个结局、九段 Seedance 2.5 原生音视频，复用原版人物形象与角色卡。包含剧情选择、自由进言的预览确认、限时互动、逐项结算、字幕、重播及图文模式。新版本由确定性剧情引擎结算；自由进言匹配作者预置意图。

原版 DeepSeek 名场面对线位于 `/classic/`，继续读取 Render 已有 `DEEPSEEK_API_KEY` 和可选 `DEEPSEEK_MODEL`，不需要更换密钥。

## 运行和部署

```sh
pip install -r requirements.txt
PORT=8157 python server.py
```

现有 Render 服务追踪本仓库 `main`；构建和启动命令保持不变。健康检查 `/api/health` 返回发布提交、内容版本与可用视频数。`film/private/` 是运行时目录，不提交、不对外提供。生成服务密钥和生产请求记录不包含在本仓库。

## 存档

服务端 SQLite 保存当前运行；浏览器另存已经确认的动作序列。免费实例重启后，继续游戏会在服务器找不到该存档时，通过引擎逐步校验并重放动作恢复。恢复接口不接受数值、结局或完整状态覆盖。清理浏览器网站数据会同时清除本机备份；当前没有跨设备账号同步。

## 验证

```sh
python -m unittest discover -s qa -p 'test_*.py' -v
MING_HTTP_TEST_BASE=http://127.0.0.1:8157 python -m unittest discover -s film/qa -p 'test_*.py' -v
```

素材版本、SHA256、模型、字幕及逐段检查记录见 `film/media/runtime-manifest.json`。原生配音已有自动转写与浏览器解码检查；M04、M05、M08 的个别音节仍保留人工逐字听校事项，不能将技术验收视为听校或人物创意审批结论。
