# 大明 1566 名场面互动 Demo 内网发布包

## 启动

```bash
cd 大明1566_内网发布包
chmod +x start.sh
./start.sh
```

启动后访问：

```text
http://服务器内网IP:8123/
```

本机测试：

```text
http://127.0.0.1:8123/
```

## 已包含

- `index.html` / `app.js` / `style.css`
- `server.py`：静态服务与 DeepSeek 后端代理
- `assets/新背景图.png`
- `assets/title_bgm_5s_2m.m4a`
- `assets/characters/`
- `assets/classic_voice/`
- `assets/poster.webp`
- `assets/jiajing-scene.png`

## 未包含

- GPT-SoVITS 训练权重
- 训练素材与 `voice_assets`
- 原始长视频 mp4
- 生成语音缓存

## DeepSeek

DeepSeek API key 只写在后端 `server.py`，不会写入前端 `app.js`。内网部署时所有玩家通过 `/api/deepseek` 调用后端代理。

如需换 key，优先使用环境变量：

```bash
export DEEPSEEK_API_KEY="新的 key"
./start.sh
```

环境变量会覆盖 `server.py` 里的默认 fallback key。
