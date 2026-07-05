"""Vultr Serverless Inference integration for CovenantOps Agent.

Per the Vultr track directive ("use Vultr Serverless Inference for ALL LLM
workloads"), CovenantOps Agent runs on Vultr:

  - Reasoning: POST /v1/chat/completions (OpenAI-compatible) for the credit-risk
    analyst note and clarifying Q&A.
  - Document retrieval: POST /v1/rerank with a VultronRetriever model
    (https://huggingface.co/collections/vultr/vultronretriever) to semantically
    rank covenant clauses against the investigation query.

Optional and fail-safe: if Vultr is not configured or unreachable, the agent
falls back to deterministic local reasoning/retrieval, so the demo never breaks.
Every result records which path produced it (`vultr` | `local_fallback`).

Verified API (docs.vultr.com):
  base:     https://api.vultrinference.com/v1
  auth:     Authorization: Bearer <VULTR_INFERENCE_API_KEY>
  chat:     POST /chat/completions   {model, messages} -> choices[0].message.content
  rerank:   POST /rerank             {model, query, documents} -> results[{index, relevance_score}]
  models:   GET  /models
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

VULTR_BASE = "https://api.vultrinference.com/v1"


class VultrInference:
    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: str = VULTR_BASE,
                 chat_model: Optional[str] = None,
                 rerank_model: Optional[str] = None,
                 timeout: float = 20.0):
        self.api_key = api_key or os.environ.get("VULTR_INFERENCE_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model or os.environ.get("VULTR_CHAT_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
        self.rerank_model = rerank_model or os.environ.get("VULTR_RERANK_MODEL", "vultr/VultronRetrieverPrime-Qwen3.5-8B")
        self.timeout = float(os.environ.get("VULTR_TIMEOUT_SECONDS", timeout))
        self.enabled = bool(self.api_key)
        self.last_used = "none"       # "vultr" | "local_fallback" | "none"
        self.retrieval_used = "none"  # last document-retrieval path

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # --- Reasoning (chat completion) ---
    def reason(self, prompt: str, system: Optional[str] = None, max_tokens: int = 400) -> Optional[str]:
        """Run a reasoning/answer step on Vultr. Returns text, or None on any
        failure (caller falls back to deterministic logic)."""
        if not self.enabled:
            return None
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/chat/completions", headers=self._headers(),
                                json={"model": self.chat_model, "messages": messages,
                                      "max_tokens": max_tokens, "temperature": 0.2})
                r.raise_for_status()
                content = r.json()["choices"][0]["message"].get("content")
                if content:
                    self.last_used = "vultr"
                    return content
                self.last_used = "local_fallback"
                return None
        except Exception:
            self.last_used = "local_fallback"
            return None

    # --- Document retrieval (semantic rerank via a VultronRetriever model) ---
    def rerank(self, query: str, documents: List[str], top_n: Optional[int] = None) -> Optional[List[Tuple[int, float]]]:
        """Rank `documents` by relevance to `query` using a VultronRetriever model
        on Vultr Serverless Inference. Returns [(orig_index, score), ...] sorted by
        relevance (desc), or None on any failure / when not configured."""
        if not self.enabled or not documents:
            return None
        payload: Dict[str, Any] = {"model": self.rerank_model, "query": query, "documents": documents}
        if top_n:
            payload["top_n"] = top_n
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/rerank", headers=self._headers(), json=payload)
                r.raise_for_status()
                results = r.json().get("results", [])
                ranked = [(int(item["index"]), float(item.get("relevance_score", 0.0))) for item in results]
                if not ranked:
                    self.retrieval_used = "local_fallback"
                    return None
                ranked.sort(key=lambda t: t[1], reverse=True)
                self.retrieval_used = "vultr"
                return ranked
        except Exception:
            self.retrieval_used = "local_fallback"
            return None
