"""Vultr Serverless Inference integration for CovenantOps Agent.

Per the Vultr track directive ("use Vultr Serverless Inference for ALL LLM
workloads"), CovenantOps Agent's reasoning and document grounding run on Vultr:

  - Reasoning: POST /v1/chat/completions (OpenAI-compatible) for drift judgement
    and cause-attribution narration.
  - Document grounding: a Vultr-managed vector store collection + the RAG chat
    endpoint (POST /v1/chat/completions/RAG) for semantic clause retrieval.

Optional and fail-safe: if Vultr is not configured or unreachable, the agent
falls back to its deterministic local reasoning/retrieval, so the demo never
breaks. Every result records which path produced it.

Verified API (docs.vultr.com):
  base:        https://api.vultrinference.com/v1
  auth:        Authorization: Bearer <VULTR_INFERENCE_API_KEY>
  chat:        POST /chat/completions           {model, messages} -> choices[0].message.content
  rag chat:    POST /chat/completions/RAG       {collection, model, messages}
  vector store:POST /vector_store               {name} -> {id}
  models:      GET  /chat/models
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

VULTR_BASE = "https://api.vultrinference.com/v1"


class VultrInference:
    def __init__(self,
                 api_key: Optional[str] = None,
                 base_url: str = VULTR_BASE,
                 chat_model: Optional[str] = None,
                 timeout: float = 20.0):
        self.api_key = api_key or os.environ.get("VULTR_INFERENCE_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model or os.environ.get("VULTR_CHAT_MODEL", "kimi-k2-instruct")
        self.timeout = float(os.environ.get("VULTR_TIMEOUT_SECONDS", timeout))
        self.enabled = bool(self.api_key)
        self.last_used = "none"   # "vultr" | "local_fallback" | "none"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # --- Reasoning (chat completion) ---
    def reason(self, prompt: str, system: Optional[str] = None, max_tokens: int = 400) -> Optional[str]:
        """Run a reasoning step on Vultr. Returns text, or None on any failure
        (caller falls back to deterministic logic)."""
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
                self.last_used = "vultr"
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            self.last_used = "local_fallback"
            return None

    # --- Vector store (document grounding setup) ---
    def create_collection(self, name: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/vector_store", headers=self._headers(),
                                json={"name": name})
                r.raise_for_status()
                return r.json().get("id")
        except Exception:
            return None

    def add_document(self, collection_id: str, content: str, description: str = "") -> bool:
        if not self.enabled or not collection_id:
            return False
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/vector_store/{collection_id}/items",
                                headers=self._headers(),
                                json={"content": content, "description": description})
                r.raise_for_status()
                return True
        except Exception:
            return False

    # --- RAG chat (semantic retrieval over the collection) ---
    def rag_query(self, collection_id: str, query: str, max_tokens: int = 400) -> Optional[str]:
        if not self.enabled or not collection_id:
            return None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(f"{self.base_url}/chat/completions/RAG", headers=self._headers(),
                                json={"collection": collection_id, "model": self.chat_model,
                                      "messages": [{"role": "user", "content": query}],
                                      "max_tokens": max_tokens})
                r.raise_for_status()
                self.last_used = "vultr"
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            self.last_used = "local_fallback"
            return None


def bootstrap_collection(inf: "VultrInference", clauses: List[Dict[str, Any]],
                         collection_name: str = "covenantops-credit-agreement") -> Optional[str]:
    """Create a Vultr vector store collection and upload the parsed covenant
    clauses as embeddings, so retrieval can run through the RAG endpoint.
    Returns the collection id, or None if Vultr is unavailable (local fallback)."""
    if not inf.enabled:
        return None
    cid = inf.create_collection(collection_name)
    if not cid:
        return None
    for c in clauses:
        inf.add_document(
            cid,
            content=f"{c['title']} (Section {c.get('section','')}): {c['text']}",
            description=f"covenant:{c.get('covenant_type')} id:{c['id']}",
        )
    return cid
