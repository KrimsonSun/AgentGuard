"""门卫 Agent worker — 链式 pipeline：流式STT → LLM(OpenRouter) → 流式TTS。

单 Agent（CLAUDE.md 原则1）：一个大脑 + 工具，不做 multi-agent 编排。
呼入边缘可插拔（HANDOFF §决策3 v2）：WebRTC(demo) / 企微语音消息(通道2) / SIP(生产)
全部落到同一个 LiveKit 房间，本文件不感知呼入方式。

⚠️ livekit-agents 版本迭代快：STT/TTS 插件接线在 Day1 spike 按当前版本文档校准；
   本文件为骨架主线，标注 [Day1] 处为待接线点。
"""
import logging
import time
import uuid

from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, RunContext, function_tool
from livekit.plugins import openai as lk_openai
from livekit.plugins import silero

from . import ledger, memory, runtime_config, wecom
from .config import settings
from .prompts import GREETING, RETURNING_VISITOR_TEMPLATE, SYSTEM_PROMPT
from .slots import VisitSlots, normalize_phone, normalize_plate

log = logging.getLogger("agentguard")


class GateAgent(Agent):
    """一通电话 = 一个 GateAgent 实例。slots 即工作记忆，通话结束即弃。"""

    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.slots = VisitSlots()
        self.call_id = uuid.uuid4().hex[:12]
        self.connected_at: float | None = None  # Agent 开口时刻（25s 计时起点）
        self.turn = 0

    # ---- 工具：LLM 每轮抽取到的字段写入工作记忆 ----
    @function_tool
    async def update_slots(
        self,
        ctx: RunContext,
        plate: str | None = None,
        company: str | None = None,
        phone: str | None = None,
        purpose: str | None = None,
        visitor_name: str | None = None,
    ) -> str:
        """记录司机这句话里给出的登记信息。给了几项传几项。

        Args:
            plate: 车牌号（如 沪A12345）
            company: 来访单位（园区内公司名）
            phone: 手机号（11位）
            purpose: 来访事由（送货/拜访/面试等）
            visitor_name: 对方自称（如 张师傅），可选
        """
        if plate:
            p = normalize_plate(plate)
            if VisitSlots.valid_plate(p):
                self.slots.plate = p
            else:
                return f"车牌号「{plate}」格式可疑，请向司机复述确认。{self.slots.brief()}"
        if phone:
            ph = normalize_phone(phone)
            if VisitSlots.valid_phone(ph):
                self.slots.phone = ph
            else:
                return f"手机号「{phone}」不是11位，请再问一遍。{self.slots.brief()}"
        if company:
            self.slots.company = company.strip()
        if purpose:
            self.slots.purpose = purpose.strip()
        if visitor_name:
            self.slots.visitor_name = visitor_name.strip()
        # 顺手做回访识别：拿到车牌或手机号的第一时间点查画像
        if (self.slots.plate or self.slots.phone) and not getattr(self, "_profile_checked", False):
            self._profile_checked = True
            profile = await memory.lookup_returning_visitor(
                self.slots.plate or "", self.slots.phone or ""
            )
            if profile:
                hint = RETURNING_VISITOR_TEMPLATE.format(
                    summary=profile["summary"] or "",
                    plate=profile["plate"],
                    last_visit=profile["last_visit_at"].strftime("%m月%d日"),
                    count=profile["visit_count"],
                )
                return f"{self.slots.brief()}\n{hint}"
        return self.slots.brief()

    # ---- 工具：四项收齐后落库 ----
    @function_tool
    async def save_visit(self, ctx: RunContext) -> str:
        """四项信息收齐后调用，登记入库。"""
        if not self.slots.complete():
            return f"还不能提交，缺：{'、'.join(self.slots.missing())}"
        visit_id = await memory.save_visit(self.call_id, self.slots)
        return f"已登记（单号 {visit_id}）。现在调 notify_guard 通知门卫。"

    # ---- 工具：推送保安企业微信（25s 指标终点） ----
    @function_tool
    async def notify_guard(self, ctx: RunContext) -> str:
        """登记入库后调用，把访客信息推送给门卫（保安企业微信）。"""
        elapsed = time.monotonic() - self.connected_at if self.connected_at else None
        ok = await wecom.notify_guard(self.slots, elapsed_s=elapsed)
        if elapsed is not None:
            log.info("25s指标 call=%s 接通→微信送达 %.1fs", self.call_id, elapsed)
            await ledger.record_media(self.call_id, "telephony", "livekit",
                                      audio_seconds=elapsed)
        return "已通知门卫，可以收尾了。" if ok else "推送失败，请告知司机稍后由门卫人工处理。"


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    gate = GateAgent()
    # 每通电话读一次运行时配置（点查 ~20ms，与媒体建立并行，不在接听路径）；
    # 通话内固定，admin console 切换后下一通即生效（HANDOFF §决策7）
    model = await runtime_config.get_model()

    session = AgentSession(
        llm=lk_openai.LLM(
            model=model,
            base_url=settings.openrouter_base_url,  # → OpenRouter（OpenAI 兼容）
            api_key=settings.openrouter_api_key,
        ),
        stt=None,  # [Day1] 中文流式 STT 定稿后接线（国内 vs Deepgram 实测对比）
        tts=None,  # [Day1] 中文流式 TTS 定稿后接线
        vad=silero.VAD.load(),
    )

    # 每轮 LLM 用量 → usage_ledger（读/写 token 分列；以回传 usage 为准）
    @session.on("metrics_collected")
    def _on_metrics(ev):  # [Day1] 按当前版本事件字段校准
        m = ev.metrics
        if getattr(m, "prompt_tokens", None) is not None:
            gate.turn += 1
            import asyncio
            asyncio.create_task(ledger.record_llm(
                gate.call_id, gate.turn, model,
                m.prompt_tokens, m.completion_tokens,
                getattr(m, "prompt_cached_tokens", 0) or 0,
            ))

    await session.start(agent=gate, room=ctx.room)
    gate.connected_at = time.monotonic()  # Agent 开口 = 25s 计时起点
    session.say(GREETING)  # 固定开场白直走 TTS，LLM 不在接听路径（秒接）

    # 通话结束时打印对账（挂断回调里执行，[Day1] 校准挂断事件名）
    # summary = await ledger.call_summary(gate.call_id)
    # if summary: log.info(ledger.format_summary(summary))


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
