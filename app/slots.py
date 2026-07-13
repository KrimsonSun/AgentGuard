"""单次通话的工作记忆：slot 填充状态。

上下文边界（CLAUDE.md 原则2）：进入 LLM context 的只有
静态系统提示 + 本对象的摘要 +（若回访）一句压缩摘要 + 最新用户话语。
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# 中国大陆车牌（含新能源6位序号）；语音转写常有空格/小写，先归一化再校验
PLATE_RE = re.compile(
    r"^[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领]"
    r"[A-HJ-NP-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9挂学警港澳]$"
)
PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

_FIELDS_ZH = {"plate": "车牌号", "company": "来访单位", "phone": "手机号", "purpose": "来访事由"}


def normalize_plate(v: str) -> str:
    return v.strip().upper().replace(" ", "").replace("·", "")


def normalize_phone(v: str) -> str:
    return re.sub(r"\D", "", v)


@dataclass
class VisitSlots:
    plate: str | None = None
    company: str | None = None
    phone: str | None = None
    purpose: str | None = None
    visitor_name: str | None = None  # 可选："张师傅"
    entered_at: datetime | None = None  # save_visit 时由 DB now() 定格

    def missing(self) -> list[str]:
        return [zh for k, zh in _FIELDS_ZH.items() if not getattr(self, k)]

    def complete(self) -> bool:
        return not self.missing()

    def brief(self) -> str:
        """注入 LLM 的当前状态摘要（短，省读 token）。"""
        got = [f"{zh}={getattr(self, k)}" for k, zh in _FIELDS_ZH.items() if getattr(self, k)]
        need = self.missing()
        return f"已收集: {'; '.join(got) or '无'} | 缺: {'、'.join(need) or '无（可提交）'}"

    @staticmethod
    def valid_plate(v: str) -> bool:
        return bool(PLATE_RE.match(normalize_plate(v)))

    @staticmethod
    def valid_phone(v: str) -> bool:
        return bool(PHONE_RE.match(normalize_phone(v)))
