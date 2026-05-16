from __future__ import annotations

import asyncio

from FlagEmbedding import BGEM3FlagModel


class BGEM3Embedder:
    def __init__(self, model_name: str, device: str, use_fp16: bool) -> None:
        self._model = BGEM3FlagModel(
            model_name,
            use_fp16=use_fp16,
            device=device,
        )

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            output = self._model.encode(texts, batch_size=16, max_length=256)
            return output["dense_vecs"].tolist()

        return await asyncio.to_thread(_encode)
