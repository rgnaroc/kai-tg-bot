"""Git-менеджер: чтение кода, коммиты, пуши — для self-coding."""

import logging
from pathlib import Path

import git

from bot.config import GIT_REPO_PATH, GIT_REMOTE, GIT_BRANCH

logger = logging.getLogger(__name__)


class GitManager:
    """Обёртка над GitPython для безопасной работы с репозиторием."""

    def __init__(self, repo_path: str = str(GIT_REPO_PATH)):
        self.repo_path = Path(repo_path)
        self._repo: git.Repo | None = None

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            self._repo = git.Repo(self.repo_path)
        return self._repo

    def is_clean(self) -> bool:
        """Проверить, нет ли незакоммиченных изменений."""
        return not self.repo.is_dirty(untracked_files=True)

    def stash(self) -> bool:
        """Сохранить текущие изменения в stash."""
        if self.repo.is_dirty():
            self.repo.git.stash("push", "--include-untracked", "-m", "kai-auto-stash")
            logger.info("Git: изменения сохранены в stash")
            return True
        return False

    def unstash(self):
        """Восстановить последний stash."""
        try:
            self.repo.git.stash("pop")
            logger.info("Git: stash восстановлен")
        except git.GitCommandError:
            logger.warning("Git: не удалось восстановить stash")

    def read_file(self, path: str) -> str:
        """Прочитать содержимое файла из репозитория."""
        full_path = self.repo_path / path
        if not full_path.is_relative_to(self.repo_path):
            raise ValueError(f"Путь {path} выходит за пределы репозитория")
        return full_path.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str):
        """Записать содержимое в файл."""
        full_path = self.repo_path / path
        if not full_path.is_relative_to(self.repo_path):
            raise ValueError(f"Путь {path} выходит за пределы репозитория")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def list_python_files(self) -> list[str]:
        """Список всех .py файлов в проекте (относительные пути)."""
        files = []
        for py_file in self.repo_path.rglob("*.py"):
            rel = py_file.relative_to(self.repo_path)
            # Исключаем __pycache__ и .git
            if "__pycache__" not in rel.parts and ".git" not in rel.parts:
                files.append(str(rel))
        return sorted(files)

    def get_diff(self) -> str:
        """Получить diff текущих изменений."""
        return self.repo.git.diff()

    def commit_and_push(self, message: str, branch: str | None = None) -> str:
        """Закоммитить и запушить изменения. Возвращает результат."""
        branch = branch or GIT_BRANCH
        try:
            # Переключиться на нужную ветку
            if self.repo.active_branch.name != branch:
                self.repo.git.checkout(branch)
            # Добавить всё
            self.repo.git.add(A=True)
            # Коммит
            self.repo.git.commit("-m", message)
            # Пуш
            remote = self.repo.remote(name=GIT_REMOTE)
            result = remote.push(branch)
            summary = result[0].summary if result else "ok"
            logger.info("Git: коммит + пуш → %s", summary)
            return f"✅ Коммит: «{message}»\n📤 Пуш: {summary}"
        except git.GitCommandError as e:
            logger.error("Git: ошибка → %s", e)
            return f"❌ Ошибка Git: {e}"

    def get_log(self, max_count: int = 5) -> str:
        """Последние N коммитов."""
        commits = list(self.repo.iter_commits(GIT_BRANCH, max_count=max_count))
        lines = []
        for c in commits:
            lines.append(f"• `{c.hexsha[:7]}` {c.message.splitlines()[0]}")
        return "\n".join(lines)
