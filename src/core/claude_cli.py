import asyncio
import json
import subprocess
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ClaudeCLIError(Exception):
    pass


class ClaudeCLIParseError(Exception):
    pass


class ClaudeCLI:
    def __init__(self, semaphore_limit: int = 3, timeout: int = 120) -> None:
        self._semaphore = asyncio.Semaphore(semaphore_limit)
        self._timeout = timeout

    async def call(self, prompt: str) -> str:
        """Basic text response from Claude CLI."""
        async with self._semaphore:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["claude", "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                ),
            )
            if result.returncode != 0:
                raise ClaudeCLIError(result.stderr)
            return result.stdout.strip()

    async def call_json(self, prompt: str, model: type[T]) -> T:
        """Structured JSON response parsed into a Pydantic model."""
        schema_hint = model.model_json_schema()
        full_prompt = (
            f"{prompt}\n\n"
            f"다음 JSON 스키마에 맞춰 JSON으로만 응답하세요:\n"
            f"{json.dumps(schema_hint, ensure_ascii=False)}"
        )

        last_exc: Exception = ClaudeCLIParseError("No attempts made")
        for attempt in range(3):
            raw = await self.call(full_prompt)
            cleaned = raw.strip()

            # Strip markdown code fences
            if cleaned.startswith("```"):
                lines = cleaned.split("\n", 1)
                cleaned = lines[1] if len(lines) > 1 else ""
                cleaned = cleaned.rsplit("```", 1)[0]

            try:
                return model.model_validate_json(cleaned)
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    full_prompt = (
                        f"이전 응답이 JSON 파싱에 실패했습니다. 순수 JSON만 출력하세요:\n"
                        f"{full_prompt}"
                    )

        raise ClaudeCLIParseError(f"3회 파싱 실패: {last_exc}")
