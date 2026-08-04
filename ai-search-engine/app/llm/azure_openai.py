"""Azure OpenAI implementation of LLMClient.

Deployment names in Azure often differ from model names; here we assume the
deployment name matches the model id in the bot config. Adjust the mapping in
_deployment() if yours differ.
"""
import json

from app.core.exceptions import UpstreamError
from app.llm.base import ChatResult, EmbedResult, LLMClient, ToolCall, ToolChatResult
from app.rag.history import build_messages


class AzureOpenAIClient(LLMClient):
    def __init__(self, endpoint: str, api_key: str, api_version: str):
        from openai import AzureOpenAI

        self._client = AzureOpenAI(
            azure_endpoint=endpoint, api_key=api_key, api_version=api_version
        )

    @staticmethod
    def _deployment(model: str) -> str:
        # Central place to map model id -> Azure deployment name if they differ.
        return model

    def chat(self, system: str, user: str, model: str, temperature: float = 0.2,
             json_mode: bool = False, history: list[dict] | None = None) -> ChatResult:
        try:
            resp = self._client.chat.completions.create(
                model=self._deployment(model),
                temperature=temperature,
                messages=build_messages(system, history, user),
                **({"response_format": {"type": "json_object"}} if json_mode else {}),
            )
        except Exception as exc:
            raise UpstreamError(f"Azure OpenAI chat failed: {exc}") from exc

        usage = resp.usage
        return ChatResult(
            text=resp.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            model=model,
        )

    def chat_with_tools(self, messages: list[dict], model: str, tools: list[dict],
                        temperature: float = 0.2) -> ToolChatResult:
        try:
            resp = self._client.chat.completions.create(
                model=self._deployment(model),
                temperature=temperature,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as exc:
            raise UpstreamError(f"Azure OpenAI tool-calling chat failed: {exc}") from exc

        choice = resp.choices[0]
        raw_tool_calls = choice.message.tool_calls or []
        tool_calls = []
        for tc in raw_tool_calls:
            try:
                arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                # A model that emits malformed JSON args is a tool-call
                # failure, not a request failure - surface it as an empty
                # arguments dict so the tool executor's own validation
                # rejects it cleanly (missing required args) instead of
                # crashing the whole request here.
                arguments = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        usage = resp.usage
        return ToolChatResult(
            content=choice.message.content,
            tool_calls=tool_calls,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            model=model,
            assistant_message=choice.message.model_dump(),
        )

    def embed(self, texts: list[str], model: str, is_query: bool = False) -> EmbedResult:
        # Azure OpenAI embeddings have no query/passage distinction - is_query
        # is part of the shared LLMClient contract but unused here.
        try:
            resp = self._client.embeddings.create(model=self._deployment(model), input=texts)
        except Exception as exc:
            raise UpstreamError(f"Azure OpenAI embedding failed: {exc}") from exc

        return EmbedResult(
            vectors=[d.embedding for d in resp.data],
            total_tokens=resp.usage.total_tokens,
            model=model,
        )
