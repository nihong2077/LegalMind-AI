from .legal_workflow import MODEL_FAST, MODEL_HEAVY, build_legal_workflow
from .debate_workflow import build_debate_workflow
from .contract_review_workflow import build_contract_review_workflow

__all__ = [
    "build_legal_workflow",
    "build_debate_workflow",
    "build_contract_review_workflow",
    "MODEL_HEAVY",
    "MODEL_FAST",
]
