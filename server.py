import json
import os
import re
import hashlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
GSV_DIR = WORKSPACE / "vendor" / "GPT-SoVITS"
PY311_VENV = WORKSPACE / ".venv-gpt-sovits-py311"
TTS_API = os.environ.get("GPT_SOVITS_API", "http://127.0.0.1:9880")
MODEL = "deepseek-v4-pro"
DEEPSEEK_API_KEY_FALLBACK = "sk-fdf3983bcb634f518bdc3aa1e211665f"
TTS_PROCESS = None
CURRENT_TTS_SPEAKER = None

VOICE_PROFILES = {
    "jiajing": {
        "names": {"jiajing", "嘉靖"},
        "gpt": GSV_DIR / "GPT_weights_v2" / "dm1566_jiajing_quick_run2-e12.ckpt",
        "sovits": GSV_DIR / "SoVITS_weights_v2" / "dm1566_jiajing_quick_run2_e8_s800.pth",
        "ref": WORKSPACE / "voice_assets" / "refs" / "jiajing_quick_run2_ref_9s.wav",
        "prompt": "医不如心，人不如故。可在朕这儿啊，人也是旧的好，医也是旧的好，用久了多少都有些舍不得。",
        "postprocess": "highpass=f=80,lowpass=f=7800,afftdn=nf=-22,loudnorm=I=-15:TP=-2:LRA=9",
    },
    "yansong": {
        "names": {"yansong", "严嵩", "yanshifan", "严世蕃"},
        "gpt": GSV_DIR / "GPT_weights_v2" / "dm1566_yansong_quick_run1-e12.ckpt",
        "sovits": GSV_DIR / "SoVITS_weights_v2" / "dm1566_yansong_quick_run1_e8_s800.pth",
        "ref": WORKSPACE / "voice_assets" / "refs" / "yansong_debgm_0013_ref_9s.wav",
        "prompt": "拿人家当枪使，只为了拱倒我们。那些理学心学，你和你的老师都学到什么地方去了？",
    },
}

VOICE_CACHE = ROOT / "assets" / "generated_voice"
CLASSIC_VOICE_MANIFEST = ROOT / "assets" / "classic_voice" / "manifest.json"


def load_env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/api/health":
            self._send_json({
                "ok": True,
                "deepseekConfigured": bool(os.environ.get("DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY_FALLBACK),
                "model": MODEL,
            })
            return
        if parsed_url.path == "/api/tts/health":
            self._send_json({
                "ok": True,
                "configuredSpeakers": sorted(VOICE_PROFILES.keys()),
                "api": TTS_API,
                "apiRunning": is_tts_api_running(),
            })
            return
        if parsed_url.path == "/api/classic-voice":
            self._handle_classic_voice(parsed_url)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/tts":
            self._handle_tts()
            return
        if self.path == "/api/trim-classic-voice":
            self._handle_trim_classic_voice()
            return

        if self.path != "/api/deepseek":
            self.send_error(404, "Unknown API route")
            return

        try:
            payload = self._read_json()
            prompt = payload.get("prompt", "").strip()
            if not prompt:
                self._send_json({"error": "Missing prompt"}, status=400)
                return

            api_key = os.environ.get("DEEPSEEK_API_KEY", "") or DEEPSEEK_API_KEY_FALLBACK
            if not api_key:
                self._send_json({"error": "DEEPSEEK_API_KEY is not set"}, status=500)
                return

            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是《大明由你改写》的历史权谋互动叙事 Director Agent。"
                            "你必须只输出 JSON 对象，不要 markdown，不要代码块，不要解释。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
            )

            content = response.choices[0].message.content or ""
            parsed = parse_json_object(content)
            self._send_json({"ok": True, "model": MODEL, "result": parsed, "raw": content})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_classic_voice(self, parsed_url):
        query = urllib.parse.parse_qs(parsed_url.query)
        clip_id = (query.get("id") or [""])[0]
        manifest = load_classic_voice_manifest()
        item = manifest.get(clip_id)
        if not item:
            self._send_json({"error": "classic voice clip not found"}, status=404)
            return
        path = (ROOT / item["src"]).resolve()
        classic_root = (ROOT / "assets" / "classic_voice").resolve()
        if classic_root not in path.parents or not path.exists():
            self._send_json({"error": "classic voice asset missing"}, status=404)
            return
        self._send_bytes(path.read_bytes(), "audio/wav")

    def _handle_trim_classic_voice(self):
        try:
            payload = self._read_json()
            clip_id = str(payload.get("id", "")).strip()
            start = float(payload.get("start", 0))
            end = float(payload.get("end", 0))
            if not clip_id or end <= start or start < 0:
                self._send_json({"error": "invalid clip id or time range"}, status=400)
                return

            manifest = load_classic_voice_manifest()
            item = manifest.get(clip_id)
            if not item:
                self._send_json({"error": "classic voice clip not found"}, status=404)
                return

            output_path = (ROOT / item["src"]).resolve()
            classic_root = (ROOT / "assets" / "classic_voice").resolve()
            if classic_root not in output_path.parents:
                self._send_json({"error": "classic voice output path is outside asset root"}, status=400)
                return

            source_path, searched = find_classic_source(item.get("source", ""))
            if not source_path:
                self._send_json({
                    "error": "source media not found",
                    "source": item.get("source", ""),
                    "searched": [str(path) for path in searched],
                }, status=404)
                return

            output_path.parent.mkdir(parents=True, exist_ok=True)
            audio_filter = str(payload.get("filter") or "highpass=f=70,lowpass=f=8200,loudnorm=I=-16:TP=-2:LRA=10")
            command = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(source_path),
                "-vn",
                "-af",
                audio_filter,
                "-ar",
                "32000",
                "-ac",
                "1",
                str(output_path),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                self._send_json({"error": result.stderr.strip() or "ffmpeg failed"}, status=500)
                return

            item["start"] = f"{start:.3f}"
            item["end"] = f"{end:.3f}"
            item["filter"] = audio_filter
            CLASSIC_VOICE_MANIFEST.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._send_json({
                "ok": True,
                "id": clip_id,
                "src": item["src"],
                "source": str(source_path),
                "start": item["start"],
                "end": item["end"],
                "bytes": output_path.stat().st_size,
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_tts(self):
        try:
            payload = self._read_json()
            speaker = normalize_speaker(payload.get("speaker", ""))
            text = extract_spoken_text(payload.get("text", ""), speaker)
            if not speaker or speaker not in VOICE_PROFILES:
                self._send_json({"ok": False, "skipped": True, "reason": "voice_not_configured"})
                return
            if not text:
                self._send_json({"ok": False, "skipped": True, "reason": "empty_dialogue"})
                return

            profile = VOICE_PROFILES[speaker]
            missing = [str(path) for key in ("gpt", "sovits", "ref") if not (path := profile[key]).exists()]
            if missing:
                self._send_json({"error": "voice assets missing", "missing": missing}, status=500)
                return

            cache_path = cached_voice_path(speaker, text, profile)
            if cache_path.exists():
                self._send_bytes(cache_path.read_bytes(), "audio/wav")
                return

            ensure_tts_api()
            switch_tts_speaker(speaker)
            audio = postprocess_tts_audio(profile, synthesize_tts(profile, text))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(audio)
            self._send_bytes(audio, "audio/wav")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=502)


def parse_json_object(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_speaker(value):
    value = str(value or "").strip()
    for speaker, profile in VOICE_PROFILES.items():
        if value in profile["names"]:
            return speaker
    return value


def load_classic_voice_manifest():
    if not CLASSIC_VOICE_MANIFEST.exists():
        return {}
    return json.loads(CLASSIC_VOICE_MANIFEST.read_text(encoding="utf-8"))


def find_classic_source(source_name):
    raw = str(source_name or "").strip()
    candidates = []
    if raw:
        raw_path = Path(raw).expanduser()
        if raw_path.is_absolute():
            candidates.append(raw_path)
        candidates.extend([
            WORKSPACE / raw,
            WORKSPACE / "voice_assets" / raw,
            WORKSPACE / "Downloads" / raw,
            Path.home() / "Downloads" / raw,
        ])

    searched = []
    for candidate in candidates:
        searched.append(candidate)
        if candidate.exists():
            return candidate.resolve(), searched
    return None, searched


def extract_spoken_text(text, speaker=""):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""

    quoted = re.findall(r"[“「『](.+?)[”」』]", text)
    if quoted:
        useful = [part.strip(" ：，。；;") for part in quoted if len(part.strip(" ：，。；;")) > 2]
        selected = (useful or quoted)[:2]
        return trim_tts_text("。".join(part.strip(" ：，。；;") for part in selected if part.strip()))

    if "：" in text:
        text = text.rsplit("：", 1)[-1].strip()

    anchors = {
        "jiajing": ["朕"],
        "yansong": ["老夫", "姑娘", "你"],
    }.get(speaker, [])
    for anchor in anchors:
        index = text.find(anchor)
        if index >= 0:
            text = text[index:]
            break

    return trim_tts_text(text)


def trim_tts_text(text, max_chars=100):
    text = re.sub(r"\s+", " ", text).strip(" ：，。；;")
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    sentence_end = max(cut.rfind("。"), cut.rfind("？"), cut.rfind("！"))
    if sentence_end >= 40:
        return cut[: sentence_end + 1]
    return cut


def voice_profile_signature(profile):
    parts = []
    for key in ("gpt", "sovits", "ref"):
        path = profile[key]
        stat = path.stat()
        parts.append(f"{key}:{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    parts.append(f"postprocess:{profile.get('postprocess', '')}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def cached_voice_path(speaker, text, profile):
    version = voice_profile_signature(profile)
    digest = hashlib.sha1(f"{speaker}\n{version}\n{text}".encode("utf-8")).hexdigest()[:20]
    return VOICE_CACHE / speaker / version / f"{digest}.wav"


def is_tts_api_running():
    try:
        with urllib.request.urlopen(f"{TTS_API}/docs", timeout=1.0) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def ensure_tts_api():
    global TTS_PROCESS, CURRENT_TTS_SPEAKER
    if is_tts_api_running():
        return
    python_exec = PY311_VENV / "bin" / "python"
    if not python_exec.exists():
        raise RuntimeError(f"Missing GPT-SoVITS Python env: {python_exec}")

    env = os.environ.copy()
    env["PYTHONPATH"] = ":".join([
        str(GSV_DIR),
        str(GSV_DIR / "GPT_SoVITS"),
        str(GSV_DIR / "GPT_SoVITS" / "BigVGAN"),
        str(GSV_DIR / "tools"),
        str(GSV_DIR / "tools" / "asr"),
        env.get("PYTHONPATH", ""),
    ])
    env["is_half"] = "False"
    TTS_PROCESS = subprocess.Popen(
        [
            str(python_exec),
            "api_v2.py",
            "-a",
            "127.0.0.1",
            "-p",
            "9880",
            "-c",
            "GPT_SoVITS/configs/tts_infer.yaml",
        ],
        cwd=str(GSV_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    CURRENT_TTS_SPEAKER = None

    deadline = time.time() + 120
    while time.time() < deadline:
        if is_tts_api_running():
            return
        time.sleep(1)
    raise TimeoutError("GPT-SoVITS API did not start within 120 seconds")


def switch_tts_speaker(speaker):
    global CURRENT_TTS_SPEAKER
    if CURRENT_TTS_SPEAKER == speaker:
        return
    profile = VOICE_PROFILES[speaker]
    get_tts_api("/set_gpt_weights", {"weights_path": str(profile["gpt"])})
    get_tts_api("/set_sovits_weights", {"weights_path": str(profile["sovits"])})
    CURRENT_TTS_SPEAKER = speaker


def get_tts_api(path, params):
    url = f"{TTS_API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as response:
        body = response.read()
        if response.status >= 400:
            raise RuntimeError(body.decode("utf-8", errors="ignore"))
        return body


def synthesize_tts(profile, text):
    body = json.dumps({
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": str(profile["ref"]),
        "prompt_text": profile["prompt"],
        "prompt_lang": "zh",
        "text_split_method": "cut5",
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": 0,
        "top_k": 15,
        "top_p": 1,
        "temperature": 0.65,
        "speed_factor": 1.0,
        "parallel_infer": True,
        "repetition_penalty": 1.5,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{TTS_API}/tts",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            audio = response.read()
            content_type = response.headers.get("Content-Type", "")
            if response.status >= 400 or not content_type.startswith("audio/"):
                raise RuntimeError(audio.decode("utf-8", errors="ignore"))
            return audio
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="ignore")) from exc


def postprocess_tts_audio(profile, audio):
    audio_filter = profile.get("postprocess")
    if not audio_filter:
        return audio
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        audio_filter,
        "-ar",
        "32000",
        "-ac",
        "1",
        "-f",
        "wav",
        "pipe:1",
    ]
    result = subprocess.run(command, input=audio, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        return audio
    return result.stdout


def main():
    global MODEL
    load_env_file(ROOT / ".env")
    MODEL = os.environ.get("DEEPSEEK_MODEL", MODEL)
    port = int(os.environ.get("PORT", "8123"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DemoHandler)
    print(f"Serving demo on http://127.0.0.1:{port}")
    print(f"DeepSeek model: {MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
