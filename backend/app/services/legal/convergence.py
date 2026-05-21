"""
辩论收敛判定算法。

综合语义相似度与 KFE 匹配规则判断辩论是否收敛，
防止仅靠向量相似度忽略重要法律词义差异。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MAX_DEBATE_ROUNDS = 3
SEMANTIC_CONVERGENCE_THRESHOLD = 0.92
KFE_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6


def compute_convergence_score(
    semantic_similarity: float,
    kfe_consistency: bool,
    mismatches: list[str],
    round_num: int,
) -> float:
    """
    计算辩论收敛得分。

    Args:
        semantic_similarity: 双方最新陈述的语义余弦相似度 (0-1)
        kfe_consistency: KFE 关键维度是否全部一致
        mismatches: 不一致的 KFE 字段列表
        round_num: 当前辩论轮次

    Returns:
        收敛得分 (0-1)，>= 0.85 视为收敛
    """
    kfe_score = 1.0 if kfe_consistency else max(0, 1.0 - len(mismatches) * 0.2)

    round_bonus = min(0.15, round_num * 0.05)

    score = (
        semantic_similarity * SEMANTIC_WEIGHT
        + kfe_score * KFE_WEIGHT
        + round_bonus
    )

    return min(1.0, score)


def should_converge(
    semantic_similarity: float,
    kfe_consistency: bool,
    mismatches: list[str],
    round_num: int,
    max_rounds: int = MAX_DEBATE_ROUNDS,
    threshold: float = 0.85,
) -> tuple[bool, str]:
    """
    判断辩论是否应该收敛。

    Returns:
        (是否收敛, 原因描述)
    """
    if round_num >= max_rounds:
        return True, f"已达到最大辩论轮次（{max_rounds}轮），强制结束"

    if not kfe_consistency and semantic_similarity > 0.95:
        return False, f"语义相似度很高（{semantic_similarity:.2%}），但关键法律事实不一致：{', '.join(mismatches)}"

    score = compute_convergence_score(
        semantic_similarity, kfe_consistency, mismatches, round_num
    )

    if score >= threshold:
        reason = f"收敛得分 {score:.2%} >= 阈值 {threshold:.0%}"
        if kfe_consistency:
            reason += "，关键法律事实一致"
        return True, reason

    return False, f"收敛得分 {score:.2%} < 阈值 {threshold:.0%}，需继续辩论"


def compute_semantic_similarity(text_a: str, text_b: str) -> float:
    """
    计算两段文本的语义相似度。

    使用简单的 Jaccard + 关键词重叠作为快速近似，
    生产环境应替换为 embedding 向量余弦相似度。
    """
    if not text_a or not text_b:
        return 0.0

    def tokenize(text: str) -> set[str]:
        import re
        tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text.lower())
        return set(tokens)

    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    jaccard = len(intersection) / len(union) if union else 0.0

    legal_keywords = {
        "违约", "侵权", "赔偿", "损失", "合同", "履行", "责任",
        "故意", "过失", "证据", "法条", "民法典", "诉讼",
    }
    kw_a = tokens_a & legal_keywords
    kw_b = tokens_b & legal_keywords
    kw_overlap = len(kw_a & kw_b) / max(len(kw_a | kw_b), 1)

    return jaccard * 0.4 + kw_overlap * 0.6


class DebateConvergenceTracker:
    """辩论收敛状态追踪器"""

    def __init__(self, max_rounds: int = MAX_DEBATE_ROUNDS):
        self.max_rounds = max_rounds
        self.current_round = 0
        self.plaintiff_args: list[str] = []
        self.defendant_args: list[str] = []
        self.similarities: list[float] = []
        self.kfe_comparisons: list[dict] = []
        self.converged = False
        self.convergence_reason = ""

    def record_round(
        self,
        plaintiff_arg: str,
        defendant_arg: str,
        plaintiff_kfe: Optional[dict] = None,
        defendant_kfe: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """记录一轮辩论并判断是否收敛"""
        self.current_round += 1
        self.plaintiff_args.append(plaintiff_arg)
        self.defendant_args.append(defendant_arg)

        similarity = compute_semantic_similarity(plaintiff_arg, defendant_arg)
        self.similarities.append(similarity)

        kfe_consistent = True
        mismatches: list[str] = []
        if plaintiff_kfe and defendant_kfe:
            from .kfe_extractor import compare_kfe
            comparison = compare_kfe(plaintiff_kfe, defendant_kfe)
            self.kfe_comparisons.append(comparison)
            kfe_consistent = comparison["is_consistent"]
            mismatches = comparison["mismatches"]

        converged, reason = should_converge(
            semantic_similarity=similarity,
            kfe_consistency=kfe_consistent,
            mismatches=mismatches,
            round_num=self.current_round,
            max_rounds=self.max_rounds,
        )

        if converged:
            self.converged = True
            self.convergence_reason = reason

        return converged, reason

    def get_summary(self) -> dict:
        """获取辩论追踪摘要"""
        return {
            "total_rounds": self.current_round,
            "converged": self.converged,
            "convergence_reason": self.convergence_reason,
            "similarities": self.similarities,
            "kfe_comparisons": self.kfe_comparisons,
        }
