"""Self-Coding: бот читает свой код, предлагает улучшения, применяет патчи."""

import json
import logging
import re
from dataclasses import dataclass

from bot.services.git_manager import GitManager
from bot.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class CodePatch:
    """Патч для одного файла."""
    file: str
    line_start: int
    line_end: int
    new_code: str
    reason: str


class SelfCoder:
    """Самоулучшение кода бота через LLM."""

    def __init__(self, llm: LLMRouter, git: GitManager):
        self.llm = llm
        self.git = git

    async def analyze(self) -> list[CodePatch]:
        """Прочитать весь код бота, попросить LLM найти улучшения."""
        python_files = self.git.list_python_files()
        if not python_files:
            return []

        # Читаем все .py файлы и формируем промпт
        code_sections = []
        for f in python_files[:20]:  # ограничиваем, чтобы не превысить контекст
            try:
                content = self.git.read_file(f)
                # Ограничиваем длину одного файла
                if len(content) > 3000:
                    content = content[:3000] + "\n# ... (truncated)"
                code_sections.append(f"### {f}\n```python\n{content}\n```")
            except Exception as e:
                logger.warning("Не могу прочитать %s: %s", f, e)

        prompt = SELF_CODE_PROMPT.format(
            code="\n\n".join(code_sections),
            file_list="\n".join(python_files),
        )

        response = await self.llm.send(
            prompt=prompt,
            system_prompt="Ты — эксперт по Python и архитектуре кода. Твоя задача — находить "
                         "реальные баги, уязвимости и архитектурные проблемы в коде бота. "
                         "Не предлагай косметические правки.",
            temperature=0.3,
        )

        return self._parse_patches(response.text)

    def _parse_patches(self, text: str) -> list[CodePatch]:
        """Распарсить JSON-ответ LLM в список патчей."""
        patches = []
        # Ищем JSON блок
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if not json_match:
            # Может быть без обрамления
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
            if not json_match:
                return patches
        try:
            data = json.loads(json_match.group(1) if json_match.lastindex else json_match.group(0))
            if isinstance(data, list):
                for item in data:
                    patches.append(CodePatch(
                        file=item.get("file", ""),
                        line_start=item.get("line_start", 0),
                        line_end=item.get("line_end", 0),
                        new_code=item.get("new_code", ""),
                        reason=item.get("reason", ""),
                    ))
        except json.JSONDecodeError:
            logger.warning("Не удалось распарсить JSON из ответа LLM")
        return patches

    def apply(self, patches: list[CodePatch]) -> list[str]:
        """Применить патчи к файлам. Возвращает список результатов."""
        results = []
        for patch in patches:
            try:
                content = self.git.read_file(patch.file)
                lines = content.splitlines(keepends=True)
                # Заменяем строки (line_start и line_end — 1-based)
                new_lines = patch.new_code.splitlines(keepends=True)
                before = lines[:patch.line_start - 1]
                after = lines[patch.line_end:]
                updated = before + new_lines + after
                self.git.write_file(patch.file, "".join(updated))
                results.append(f"✅ {patch.file}:{patch.line_start}-{patch.line_end} — {patch.reason}")
            except Exception as e:
                results.append(f"❌ {patch.file}: {e}")
        return results

    def format_diff(self, patches: list[CodePatch]) -> str:
        """Красивый дифф для показа пользователю."""
        if not patches:
            return "Не найдено улучшений."
        lines = [f"🔍 **Найдено {len(patches)} улучшений:**\n"]
        for i, p in enumerate(patches, 1):
            lines.append(f"**{i}. {p.file}** (строки {p.line_start}-{p.line_end})")
            lines.append(f"> {p.reason}")
            code_preview = p.new_code.strip()[:200]
            if len(p.new_code.strip()) > 200:
                code_preview += "\n..."
            lines.append(f"```python\n{code_preview}\n```")
            lines.append("")
        return "\n".join(lines)


SELF_CODE_PROMPT = """Проанализируй код Telegram-бота Kai. Найди баги, потенциальные ошибки,
архитектурные проблемы и места, которые можно улучшить.

Файлы проекта:
{file_list}

Код:
{code}

Ответь СТРОГО JSON-массивом объектов:
[
  {{
    "file": "bot/handlers/commands.py",
    "line_start": 42,
    "line_end": 45,
    "new_code": "исправленный код",
    "reason": "почему это нужно исправить"
  }}
]

Важные правила:
- Указывай ТОЛЬКО реальные проблемы, не косметику
- line_start и line_end — номера строк (1-based), которые нужно ЗАМЕНИТЬ
- new_code — полный код для замены (может быть из нескольких строк)
- Если проблемы нет — верни пустой массив []
- Не предлагай добавлять новые фичи, только исправления багов и улучшения существующего кода"""
