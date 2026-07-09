"""Хранилище сервисов в SQLite — пользователь может добавлять/удалять провайдеров."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from bot.services.llm.models import (
    PREDEFINED_PROVIDERS, OPENAI_COMPATIBLE, ProviderDef, ServiceInstance,
)

logger = logging.getLogger(__name__)


class ServiceStorage:
    """Управляет подключенными сервисами в SQLite."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS service_instances (
                    id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    api_key TEXT DEFAULT '',
                    base_url TEXT DEFAULT '',
                    model_id TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT ''
                )
            """)
            conn.commit()

    # ─── CRUD для сервисов ──────────────────────────────────────────────────

    def list_instances(self) -> list[ServiceInstance]:
        """Вернуть все инстансы, отсортированные по priority."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM service_instances ORDER BY priority ASC"
            ).fetchall()
            return [
                ServiceInstance(
                    id=r["id"],
                    service_id=r["service_id"],
                    display_name=r["display_name"],
                    api_key=r["api_key"] or "",
                    base_url=r["base_url"] or "",
                    model_id=r["model_id"] or "",
                    is_active=bool(r["is_active"]),
                    priority=r["priority"],
                )
                for r in rows
            ]

    def get_instance(self, instance_id: str) -> Optional[ServiceInstance]:
        """Получить инстанс по ID."""
        for s in self.list_instances():
            if s.id == instance_id:
                return s
        return None

    def add_instance(self, instance: ServiceInstance) -> bool:
        """Добавить новый инстанс. True — успешно, False — уже есть."""
        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                conn.execute(
                    """INSERT INTO service_instances
                       (id, service_id, display_name, api_key, base_url, model_id, is_active, priority)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (instance.id, instance.service_id, instance.display_name,
                     instance.api_key, instance.base_url, instance.model_id,
                     1 if instance.is_active else 0, instance.priority),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_instance(self, instance: ServiceInstance) -> bool:
        """Обновить существующий инстанс."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                """UPDATE service_instances SET
                   service_id=?, display_name=?, api_key=?, base_url=?,
                   model_id=?, is_active=?, priority=?
                   WHERE id=?""",
                (instance.service_id, instance.display_name,
                 instance.api_key, instance.base_url, instance.model_id,
                 1 if instance.is_active else 0, instance.priority, instance.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def remove_instance(self, instance_id: str) -> bool:
        """Удалить инстанс."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM service_instances WHERE id=?", (instance_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def set_active(self, instance_id: str, active: bool) -> bool:
        """Включить/выключить сервис."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "UPDATE service_instances SET is_active=? WHERE id=?",
                (1 if active else 0, instance_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def next_priority(self) -> int:
        """Следующий priority (макс + 1)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT COALESCE(MAX(priority), -1) + 1 FROM service_instances").fetchone()
            return row[0]

    def generate_instance_id(self, service_id: str) -> str:
        """Сгенерировать уникальный instance_id (как в Kai)."""
        existing = {s.id for s in self.list_instances()}
        if service_id not in existing:
            return service_id
        counter = 2
        while f"{service_id}_{counter}" in existing:
            counter += 1
        return f"{service_id}_{counter}"

    # ─── Настройки приложения ───────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    # ─── Сериализация для экспорта ──────────────────────────────────────────

    def export_json(self) -> str:
        """Экспорт всех сервисов в JSON (как Settings export в Kai)."""
        instances = self.list_instances()
        data = []
        for s in instances:
            data.append({
                "id": s.id,
                "service_id": s.service_id,
                "display_name": s.display_name,
                "api_key": s.api_key,
                "base_url": s.base_url,
                "model_id": s.model_id,
                "is_active": s.is_active,
                "priority": s.priority,
            })
        return json.dumps(data, indent=2, ensure_ascii=False)

    def import_json(self, json_str: str) -> list[str]:
        """Импорт сервисов из JSON. Возвращает список импортированных ID."""
        data = json.loads(json_str)
        imported = []
        for item in data:
            try:
                inst = ServiceInstance(
                    id=item["id"],
                    service_id=item["service_id"],
                    display_name=item.get("display_name", item["service_id"]),
                    api_key=item.get("api_key", ""),
                    base_url=item.get("base_url", ""),
                    model_id=item.get("model_id", ""),
                    is_active=item.get("is_active", True),
                    priority=item.get("priority", 0),
                )
                if self.add_instance(inst):
                    imported.append(inst.id)
            except Exception as e:
                logger.warning("Import failed for %s: %s", item.get("id"), e)
        return imported

    # ─── Хелперы для получения ProviderDef ──────────────────────────────────

    @staticmethod
    def get_provider_def(service_id: str) -> Optional[ProviderDef]:
        """Вернуть ProviderDef по service_id (из предустановленных или openai-compatible)."""
        if service_id in PREDEFINED_PROVIDERS:
            return PREDEFINED_PROVIDERS[service_id]
        if service_id == "openai-compatible":
            return OPENAI_COMPATIBLE
        return None
