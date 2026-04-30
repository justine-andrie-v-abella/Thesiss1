# ============================================================================
# FILE: questionnaires/services/__init__.py
# ============================================================================

from .extraction_service import QuestionnaireExtractor as AnthropicQuestionnaireExtractor
from .gemini_extraction_service import GeminiQuestionnaireExtractor

# ── Active provider ── swap this alias to switch AI backends ──────────────
QuestionnaireExtractor = GeminiQuestionnaireExtractor   # ← Gemini (active)
# QuestionnaireExtractor = AnthropicQuestionnaireExtractor  # ← Claude (inactive)

__all__ = ['QuestionnaireExtractor', 'GeminiQuestionnaireExtractor', 'AnthropicQuestionnaireExtractor']