"""Azure OpenAI implementation of LLMClient.

Deployment names in Azure often differ from model names; here we assume the
deployment name matches the model id in the bot config. Adjust the mapping in
_deployment() if yours differ.
"""
from app.core.exceptions import UpstreamError
from app.llm.base import ChatResult, EmbedResult, LLMClient


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

    def chat(self, system: str, user: str, model: str, temperature: float = 0.2) -> ChatResult:
        try:
            resp = self._client.chat.completions.create(
                model=self._deployment(model),
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
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

    def embed(self, texts: list[str], model: str) -> EmbedResult:
        try:
            resp = self._client.embeddings.create(model=self._deployment(model), input=texts)
        except Exception as exc:
            raise UpstreamError(f"Azure OpenAI embedding failed: {exc}") from exc

        return EmbedResult(
            vectors=[d.embedding for d in resp.data],
            total_tokens=resp.usage.total_tokens,
            model=model,
        )
