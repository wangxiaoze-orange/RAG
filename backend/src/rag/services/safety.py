"""⑫ SafetyGuard：紧急词检测 + 置信度判断"""
import logging
import re

logger = logging.getLogger(__name__)

# 紧急场景触发词（命中 → 答案尾部追加紧急提示）
EMERGENCY_WORDS = [
    "火灾", "火警", "自杀", "轻生", "跳楼", "割腕", "求救", "救命",
    "地震", "爆炸", "中毒", "昏迷", "大出血", "急病", "心梗", "脑梗",
    "溺水", "触电", "坠落", "枪击", "车祸", "被困",
]

EMERGENCY_TIP = (
    "\n\n⚠️ 检测到您的问题可能涉及紧急安全情况。请立即拨打当地急救电话（如中国大陆 120 / 119 / 110），"
    "并远离危险区域。以上回答仅为通用信息，不能替代专业救援。"
)


def check_emergency(question: str) -> list[str]:
    """检测问题是否含紧急词，返回命中词列表"""
    return [w for w in EMERGENCY_WORDS if w in question]


def judge_retrieval_hit(confidence: float, threshold: float) -> bool:
    """置信度判断：重排最高分 ≥ 阈值 → 判定检索命中"""
    return confidence >= threshold
