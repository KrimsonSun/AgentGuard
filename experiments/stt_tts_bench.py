"""STT / TTS 中文实测对比 bench（Day1 spike 的语音半场）。

设计要点：
- **可插拔** provider：填了 key 的才跑，没填的跳过。
- **抓真痛点**：门卫场景里车牌和手机号（数字/字母）最容易被 STT 听错，评分重点看这两项。
- **今晚就能出基线**：用 macOS `say`(中文) 本地合成测试音频 → OpenRouter voxtral 转写，无需外部账号。
  （注意：合成音频比真实电话音频干净，准确率偏乐观；真实电话噪声/压缩下会更低，仅作相对参考。）
- **TTS**：测首字节延迟(TTFB，语音体验最关键指标)，需 provider key，见 PROVIDERS 骨架。

推荐（据 LiveKit 插件生态）：STT/TTS 优先 **火山引擎 volcengine**（一账号双活 + 官方 livekit 插件 + 中文原生）；
Deepgram(STT)+Cartesia(TTS) 作国际对比。

用法：.venv/bin/python -m experiments.stt_tts_bench
"""
import asyncio
import base64
import os
import pathlib
import re
import subprocess
import time

from openai import AsyncOpenAI

from app.config import settings

AUDIO_DIR = pathlib.Path(__file__).parent / "audio"
client = AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)

# 测试用例：ground truth（重点是 plate / phone 两个易错关键字段）
CASES = [
    {"text": "沪A12345，来蓝色鲸鱼送货", "plate": "沪A12345", "phone": ""},
    {"text": "我的手机号是13812345678", "plate": "", "phone": "13812345678"},
    {"text": "沪B88888，张师傅，来启明科技面试", "plate": "沪B88888", "phone": ""},
]


def levenshtein(a: str, b: str) -> int:
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            prev, dp[j] = dp[j], min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
    return dp[-1]


def norm(s: str) -> str:
    return re.sub(r"[\s，。、！？,.\-]", "", s or "")


def score(gt: dict, hyp: str) -> dict:
    g, h = norm(gt["text"]), norm(hyp)
    cer = levenshtein(g, h) / max(len(g), 1)
    return {
        "cer": round(cer, 3),
        "acc": round(1 - cer, 3),
        "plate_ok": (gt["plate"] in hyp) if gt["plate"] else None,
        "phone_ok": (gt["phone"] in hyp) if gt["phone"] else None,
        "hyp": hyp,
    }


def synth_audio(text: str, idx: int, voice: str = "Reed") -> pathlib.Path:
    """macOS say 生成中文测试音频（wav，*.wav 已 gitignore）。"""
    AUDIO_DIR.mkdir(exist_ok=True)
    aiff, wav = AUDIO_DIR / f"case{idx}.aiff", AUDIO_DIR / f"case{idx}.wav"
    if not wav.exists():
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        subprocess.run(["afconvert", str(aiff), str(wav), "-f", "WAVE", "-d", "LEI16@16000"], check=True)
        aiff.unlink(missing_ok=True)
    return wav


# ---------- STT providers（可插拔）----------
async def stt_openrouter_voxtral(wav: pathlib.Path) -> tuple[str, int]:
    b64 = base64.b64encode(wav.read_bytes()).decode()
    t0 = time.monotonic()
    r = await client.chat.completions.create(
        model="mistralai/voxtral-small-24b-2507", temperature=0,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "逐字转写这段中文语音，只输出转写文本，不要标点解释。"},
            {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}},
        ]}],
    )
    return (r.choices[0].message.content or "").strip(), int((time.monotonic() - t0) * 1000)


async def stt_volcengine(wav):  # noqa: skeleton，火山 key 到位后填其流式 ASR
    raise NotImplementedError("填 VOLC_ASR：见 https://www.volcengine.com/docs/6561/ 流式语音识别")


async def stt_deepgram(wav):  # noqa: skeleton
    raise NotImplementedError("填 DEEPGRAM_API_KEY：livekit-plugins-deepgram 或 REST")


STT_PROVIDERS = {
    "openrouter/voxtral": (stt_openrouter_voxtral, bool(settings.openrouter_api_key)),
    "volcengine": (stt_volcengine, bool(os.getenv("VOLC_ASR_KEY"))),
    "deepgram": (stt_deepgram, bool(os.getenv("DEEPGRAM_API_KEY"))),
}


async def main():
    print("=== STT 中文实测（macOS say 合成音频；合成偏干净，准确率偏乐观）===\n")
    results = {}
    for name, (fn, enabled) in STT_PROVIDERS.items():
        if not enabled:
            print(f"⏭  {name}：无 key，跳过"); continue
        print(f"▶ {name}")
        rows, lat_sum = [], 0
        for i, c in enumerate(CASES):
            wav = synth_audio(c["text"], i)
            try:
                hyp, ms = await fn(wav)
            except NotImplementedError as e:
                print(f"   （骨架未实现：{e}）"); rows = None; break
            sc = score(c, hyp)
            lat_sum += ms
            crit = []
            if sc["plate_ok"] is not None:
                crit.append(f"车牌{'✓' if sc['plate_ok'] else '✗'}")
            if sc["phone_ok"] is not None:
                crit.append(f"手机{'✓' if sc['phone_ok'] else '✗'}")
            print(f"   [{ms:>5}ms] acc={sc['acc']:.0%} {' '.join(crit):<10} 「{sc['hyp'][:40]}」  (真值:{c['text']})")
            rows.append(sc)
        if rows:
            avg_acc = sum(r["acc"] for r in rows) / len(rows)
            plate = [r["plate_ok"] for r in rows if r["plate_ok"] is not None]
            phone = [r["phone_ok"] for r in rows if r["phone_ok"] is not None]
            results[name] = {"avg_acc": round(avg_acc, 3), "avg_ms": lat_sum // len(rows),
                             "plate_ok": f"{sum(plate)}/{len(plate)}", "phone_ok": f"{sum(phone)}/{len(phone)}"}
        print()
    print("=== 汇总 ===")
    print(f"{'provider':<22}{'均延迟':>8}{'均准确':>8}{'车牌':>7}{'手机':>7}")
    for n, r in results.items():
        print(f"{n:<22}{r['avg_ms']:>6}ms{r['avg_acc']:>7.0%}{r['plate_ok']:>7}{r['phone_ok']:>7}")
    import json
    (pathlib.Path(__file__).parent / "stt_bench_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("\nTTS 首字节延迟(TTFB)对比：需 provider key，见 PROVIDERS 骨架（火山/Cartesia/ElevenLabs），key 到位后补测。")


if __name__ == "__main__":
    asyncio.run(main())
