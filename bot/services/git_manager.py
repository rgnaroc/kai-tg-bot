"""Git-менеджер: чтение кода, коммиты, пуши — для self-coding."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import git
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


class GitManager:
    """Обёртка над GitPython. Не падает, если .git не найден."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path).resolve()
        self._repo = None
        self._tried_init = False

    @property
    def available(self) -> bool:
        """Доступен ли git (пакет + .git папка)."""
        if not GIT_AVAILABLE:
            return False
        return (self.repo_path / ".git").exists()

    def _ensure_repo(self):
        """Ленивая инициализация репозитория."""
        if self._tried_init:
            return self._repo
        self._tried_init = True
        if not self.available:
            return None
        try:
            self._repo = git.Repo(self.repo_path)
        except Exception as e:
            logger.warning("Git: не удалось открыть репозиторий: %s", e)
        return self._repo

    @property
    def repo(self):
        return self._ensure_repo()

    def is_clean(self) -> bool | None:
        """Проверить, нет ли незакоммиченных изменений. None если git недоступен."""
        r = self._ensure_repo()
        if r is None:
            return None
        return not r.is_dirty(untracked_files=True)

    def stash(self) -> bool:
        r = self._ensure_repo()
        if r is None:
            return False
        if r.is_dirty():
            r.git.stash("push", "--include-untracked", "-m", "kai-auto-stash")
            logger.info("Git: изменения сохранены в stash")
            return True
        return False

    def unstash(self):
        r = self._ensure_repo()
        if r is None:
            return
        try:
            r.git.stash("pop")
            logger.info("Git: stash восстановлен")
        except Exception:
            logger.warning("Git: не удалось восстановить stash")

    def read_file(self, path: str) -> str:
        full_path = (self.repo_path / path).resolve()
        if not str(full_path).startswith(str(self.repo_path)):
            raise ValueError(f"Путь {path} выходит за пределы проекта")
        return full_path.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str):
        full_path = (self.repo_path / path).resolve()
        if not str(full_path).startswith(str(self.repo_path)):
            raise ValueError(f"Путь {path} выходит за пределы проекта")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def list_python_files(self) -> list[str]:
        files = []
        for py_file in self.repo_path.rglob("*.py"):
            rel = py_file.relative_to(self.repo_path)
            if "__pycache__" not in rel.parts and ".git" not in rel.parts:
                files.append(str(rel))
        return sorted(files)

    def get_diff(self) -> str:
        r = self._ensure_repo()
        if r is None:
            return "Git недоступен"
        return r.git.diff()

    def commit_and_push(self, message: str, branch: str | None = None) -> str:
        r = self._ensure_repo()
        if r is None:
            return "❌ Git недоступен — проверь наличие .git в контейнере"
        from bot.config import GIT_REMOTE, GIT_BRANCH
        branch = branch or GIT_BRANCH
        try:
            if r.active_branch.name != branch:
                r.git.checkout(branch)
            r.git.add(A=True)
            r.git.commit("-m", message)
            remote = r.remote(name=GIT_REMOTE)
            result = remote.push(branch)
            summary = result[0].summary if result else "ok"
            logger.info("Git: коммит + пуш → %s", summary)
            return f"✅ Коммит: «{message}»\n📤 Пуш: {summary}"
        except Exception as e:
            logger.error("Git: ошибка → %s", e)
            return f"❌ Ошибка Git: {e}"

    def get_log(self, max_count: int = 5) -> str:
        r = self._ensure_repo()
        if r is None:
            return "Git недоступен"
        from bot.config import GIT_BRANCH
        commits = list(r.iter_commits(GIT_BRANCH, max_count=max_count))
        lines = []
        for c in commits:
            lines.append(f"• `{c.hexsha[:7]}` {c.message.splitlines()[0]}")
        return "\n".join(lines)
