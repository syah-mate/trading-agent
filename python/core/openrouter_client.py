"""
OpenRouter Client — Async API wrapper untuk OpenRouter.ai.
TASK 1.3 — Semua method async dengan httpx, type hints lengkap.

Default model: google/gemini-2.0-flash-001 (cepat & murah)
"""

import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "x-ai/grok-4.3"


class OpenRouterClient:
    """Async HTTP client untuk OpenRouter chat completions API.

    Usage:
        client = OpenRouterClient()
        response = await client.chat("You are helpful.", "Hello!")
        data = await client.chat_json("You are a JSON bot.", "Return {...}")
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        load_dotenv(override=True)
        self._api_key: str = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self._model: str = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self._client: httpx.AsyncClient | None = None

        if not self._api_key:
            logger.warning(
                "OPENROUTER_API_KEY tidak diset — semua LLM call akan gagal."
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init async HTTP client (reuse connection)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",  # OpenRouter wants this
                },
            )
        return self._client

    async def _raw_request(self, messages: list[dict[str, str]]) -> str:
        """Kirim request mentah ke OpenRouter, return teks response."""
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.3,  # low temp = lebih deterministik untuk trading
        }

        logger.debug("OpenRouter request → model=%s", self._model)
        try:
            response = await client.post(OPENROUTER_BASE_URL, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("OpenRouter HTTP error: %s — body: %s", e, e.response.text[:500])
            raise
        except httpx.RequestError as e:
            logger.error("OpenRouter request error: %s", e)
            raise

        data = response.json()
        content: str = data["choices"][0]["message"]["content"]
        logger.debug("OpenRouter response (%d chars)", len(content))
        return content

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Kirim chat request, return response text.

        Args:
            system_prompt: instruksi system role
            user_prompt: pertanyaan / context user

        Returns:
            str — response dari LLM
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self._raw_request(messages)

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 1,
    ) -> dict[str, Any]:
        """Kirim chat request, parse response sebagai JSON.

        Retry 1x jika gagal parse (sesuai spesifikasi TASK 1.3).

        Args:
            system_prompt: instruksi system role
            user_prompt: pertanyaan / context user
            max_retries: jumlah retry jika JSON gagal diparse (default 1)

        Returns:
            dict — parsed JSON dari LLM response

        Raises:
            ValueError: jika semua retry gagal
        """
        last_error: str = ""
        for attempt in range(max_retries + 1):
            raw = await self.chat(system_prompt, user_prompt)
            try:
                # Bersihkan markdown code fences jika ada
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    # Hapus ```json atau ``` di awal
                    first_newline = cleaned.find("\n")
                    if first_newline != -1:
                        cleaned = cleaned[first_newline + 1:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                last_error = str(e)
                logger.warning(
                    "chat_json parse attempt %d/%d gagal: %s — raw: %.200s...",
                    attempt + 1, max_retries + 1, e, raw,
                )
                if attempt < max_retries:
                    # Tambahkan reminder di user prompt untuk retry
                    user_prompt = (
                        f"{user_prompt}\n\n"
                        f"RESPOND HANYA DENGAN VALID JSON. "
                        f"Error sebelumnya: {e}"
                    )

        raise ValueError(
            f"Gagal parse JSON setelah {max_retries + 1}x percobaan. "
            f"Error terakhir: {last_error}"
        )

    async def close(self) -> None:
        """Tutup HTTP client connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
