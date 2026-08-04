"""Pure-logic unit test for the admin-portal "Improve Prompt" button's
backend validation - no DB, no live LLM. The actual improved-prompt quality
was verified live against the real Azure OpenAI deployment with the sample
HR prompt from the feature request, consistent with how the rest of this
repo's AI-calling admin endpoints are verified.
"""
import pytest

from app.assistant.prompt_improver import improve_system_prompt


class _ExplodingLLM:
    """Any call proves the empty-prompt check didn't short-circuit first."""

    def chat(self, *args, **kwargs):
        raise AssertionError("should never call the LLM for an empty prompt")


class _ExplodingDb:
    def execute(self, *args, **kwargs):
        raise AssertionError("should never touch the DB for an empty prompt")

    def commit(self):
        raise AssertionError("should never touch the DB for an empty prompt")


def test_empty_prompt_rejected_before_any_llm_or_db_call():
    with pytest.raises(ValueError, match="empty"):
        improve_system_prompt(_ExplodingDb(), "   ", _ExplodingLLM(), user_id="u1")


def test_whitespace_only_prompt_rejected():
    with pytest.raises(ValueError):
        improve_system_prompt(_ExplodingDb(), "\n\t  \n", _ExplodingLLM(), user_id="u1")
