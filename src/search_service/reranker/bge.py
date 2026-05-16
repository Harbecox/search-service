from __future__ import annotations

import asyncio

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


class BGERerankerV2:
    def __init__(self, model_name: str, device: str) -> None:
        self._device = device
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()
        self._model.to(device)

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[str, str]],
        top_k: int,
    ) -> list[tuple[str, float]]:
        global_ids = [gid for gid, _ in candidates]
        pairs = [[query, text] for _, text in candidates]

        def _score() -> list[float]:
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=256,
            ).to(self._device)
            with torch.no_grad():
                logits = self._model(**inputs).logits.squeeze(-1)
            return logits.sigmoid().tolist()

        scores: list[float] = await asyncio.to_thread(_score)
        ranked = sorted(zip(global_ids, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
