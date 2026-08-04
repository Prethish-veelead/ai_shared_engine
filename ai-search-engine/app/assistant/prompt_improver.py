"""Admin-portal "Improve Prompt" button: takes whatever a bot creator has
typed into the System Prompt field and asks an LLM to tighten it up - better
organized, adds universal RAG-safety instructions (answer only from the
knowledge base, don't hallucinate, ask when ambiguous, cite sources) - while
never inventing company-specific facts/policies/contacts that aren't already
there. One-shot text-in, text-out; nothing is stored (the caller decides
whether to keep the result, exactly like typing over the field by hand).
"""
from sqlalchemy.orm import Session

from app.assistant.admin_assistant import ASSISTANT_BOT_ID
from app.core.exceptions import UpstreamError
from app.llm.base import LLMClient
from app.tracking.usage_tracker import record_chat

# Same synthetic bot id the admin analytics assistant uses - both are admin-
# only AI tooling, not real bots, and should show up as ONE row in the
# usage/cost dashboards rather than two separate ones.
IMPROVER_BOT_ID = ASSISTANT_BOT_ID
IMPROVER_MODEL = "gpt-4o-mini"

_IMPROVER_SYSTEM = """You are an expert AI Prompt Engineer specializing in Retrieval-Augmented Generation (RAG) systems.

Your task is to improve the user's system prompt while preserving its original intent.

Rules:
- Never change the bot's purpose.
- Keep all user-defined business rules.
- Improve grammar, wording, and readability.
- Organize the prompt into logical sections with headings.
- Add only universally applicable RAG best practices.
- Do not invent company-specific policies, workflows, contacts, or facts.
- Emphasize that responses must come only from the provided knowledge base.
- Instruct the assistant not to hallucinate or make assumptions.
- Specify how to handle missing information by informing the user that the information is not available in the provided documents.
- Recommend asking clarifying questions when the user's request is ambiguous.
- Encourage concise, friendly, and professional responses.
- Suggest citing the source document when appropriate.
- Preserve placeholders or variables exactly as written.
- Output only the improved system prompt without explanations, markdown fences, or commentary.

The user's current system prompt follows as the next message. Output ONLY the improved system prompt - no preamble, no markdown fences, no commentary."""


def improve_system_prompt(db: Session, prompt: str, llm: LLMClient, user_id: str | None) -> str:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("System prompt is empty - write something first, then improve it.")

    result = llm.chat(system=_IMPROVER_SYSTEM, user=prompt, model=IMPROVER_MODEL, temperature=0.3)
    improved = result.text.strip()
    if not improved:
        raise UpstreamError("The model returned an empty improved prompt - try again.")

    record_chat(
        db, bot_id=IMPROVER_BOT_ID, user_id=user_id, model=IMPROVER_MODEL,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
    )
    db.commit()

    return improved
