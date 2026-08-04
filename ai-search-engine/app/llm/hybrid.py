"""Combines a chat provider (Azure OpenAI) with a separately-configured
embedding provider (e.g. a local model), so the two can be swapped
independently. The rest of the pipeline only ever sees one LLMClient.
"""
from app.llm.azure_openai import AzureOpenAIClient
from app.llm.base import ChatResult, EmbedResult, LLMClient, ToolChatResult
from app.llm.local_embedding import LocalEmbeddingModel


class HybridLLMClient(LLMClient):
    def __init__(self, chat_client: AzureOpenAIClient, embedding_model: LocalEmbeddingModel):
        self._chat_client = chat_client
        self._embedding_model = embedding_model

    def chat(self, system: str, user: str, model: str, temperature: float = 0.2,
             json_mode: bool = False, history: list[dict] | None = None) -> ChatResult:
        return self._chat_client.chat(system, user, model, temperature, json_mode=json_mode, history=history)

    def chat_with_tools(self, messages: list[dict], model: str, tools: list[dict],
                        temperature: float = 0.2) -> ToolChatResult:
        return self._chat_client.chat_with_tools(messages, model, tools, temperature=temperature)

    def embed(self, texts: list[str], model: str, is_query: bool = False) -> EmbedResult:
        return self._embedding_model.embed(texts, is_query=is_query)
