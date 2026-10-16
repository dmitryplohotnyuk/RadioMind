"""Owner-confirmed archive deletion, with durable retry of locked files."""

import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from radiomind.storage import Store


def deletion_paths(store: Store, source: str, plan: dict[str, Any]) -> list[Path]:
    roots = {
        "audio": store.path.parent / f"{source}-audio",
        "text": store.path.parent / f"{source}-text",
    }
    parent = store.path.parent.resolve()
    for root in roots.values():
        if (
            root.is_symlink()
            or root.resolve() != root.absolute()
            or root.resolve().parent != parent
        ):
            raise ValueError("Archive directory escaped data root")
    paths = []
    for ident in set(plan["part_ids"] + plan["session_ids"]):
        if not isinstance(ident, str) or UUID(ident).hex != ident:
            raise ValueError("Invalid archive identity")
        for kind, suffixes in {
            "audio": (
                ".wav",
                ".partial.wav",
                ".clean-v1.wav",
                ".clean-v1.partial.wav",
                ".clean-v2.wav",
                ".clean-v2.partial.wav",
                ".clean-v3.wav",
                ".clean-v3.partial.wav",
            ),
            "text": (".json", ".partial.json"),
        }.items():
            for suffix in suffixes:
                path = roots[kind] / (ident + suffix)
                if path.is_symlink() or path.resolve() != path.absolute():
                    raise ValueError("Archive file escaped its root")
                if path.exists() and not path.is_file():
                    raise ValueError("Unexpected directory in archive")
                paths.append(path)
    return paths


def retry_deletions(store: Store, source: str) -> int:
    """Committed tombstones survive interruption; missing files are already removed."""
    jobs = store.db.execute("SELECT id,payload FROM archive_deletions").fetchall()
    pending = 0
    for ident, payload in jobs:
        paths = deletion_paths(store, source, json.loads(payload))
        failed = False
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed = True
        if failed:
            pending += 1
        else:
            with store.db:
                store.db.execute("DELETE FROM archive_deletions WHERE id=?", (ident,))
    return pending


class ArchiveDeletion:
    def __init__(self, engine: Any, cleaner: Any) -> None:
        self.engine, self.cleaner = engine, cleaner
        self.store: Store = engine.store
        self.plans: dict[str, dict[str, Any]] = {}

    def select(self, session_id: str | None, frequency_hz: int | None) -> list[dict[str, Any]]:
        if session_id is not None:
            if UUID(session_id).hex != session_id:
                raise ValueError("Invalid conversation identity")
            return self.store.session_parts(session_id)
        selected = self.store.db.execute(
            "SELECT DISTINCT coalesce(json_extract(payload,'$.session_id'),id) "
            "FROM recordings WHERE json_extract(payload,'$.frequency_hz')=?",
            (frequency_hz,),
        ).fetchall()
        return [part for row in selected for part in self.store.session_parts(row[0])]

    def guard(self, rows: list[dict[str, Any]], frequency_hz: int | None) -> None:
        sessions = {r.get("session_id", r["id"]) for r in rows}
        active = self.engine.conversation
        if any(r["status"] == "recording" for r in rows) or (
            active
            and not active.done
            and (
                active.session_id in sessions
                or frequency_hz == active.frequency_hz
                or any(r.get("capture_group") == active.session_id for r in rows)
            )
        ):
            raise RuntimeError("На этой частоте идёт захват. Дождитесь окончания разговора.")
        if any(self.cleaner.states.get(s) == "processing" for s in sessions):
            raise RuntimeError("Дождитесь завершения очистки звука.")
        for row in rows:
            group = row.get("capture_group")
            if group:
                if UUID(group).hex != group:
                    raise ValueError("Invalid capture identity")
                if any(self.engine.archive.staging_root.glob(group + "*")):
                    raise RuntimeError("Запись ещё сохраняется. Повторите позже.")

    def preview(self, session_id: str | None, frequency_hz: int | None) -> dict[str, Any]:
        rows = self.select(session_id, frequency_hz)
        if not rows:
            raise ValueError("Записи уже удалены или не найдены.")
        self.guard(rows, frequency_hz)
        plan: dict[str, Any] = {
            "session_id": session_id,
            "frequency_hz": frequency_hz,
            "part_ids": sorted(r["id"] for r in rows),
            "session_ids": sorted({r.get("session_id", r["id"]) for r in rows}),
            "expires": time.monotonic() + 120,
        }
        paths = deletion_paths(self.store, self.engine.settings.source, plan)
        self.plans = {k: v for k, v in self.plans.items() if v["expires"] > time.monotonic()}
        if len(self.plans) >= 32:
            self.plans.pop(next(iter(self.plans)))
        token = uuid4().hex
        self.plans[token] = plan
        return {
            "token": token,
            "conversations": len(plan["session_ids"]),
            "parts": len(rows),
            "bytes": sum(p.stat().st_size for p in paths if p.is_file()),
            "frequency_hz": frequency_hz,
        }

    def commit(self, token: str) -> dict[str, Any]:
        plan = self.plans.pop(token, None)
        if plan is None or plan["expires"] <= time.monotonic():
            raise RuntimeError("Подтверждение устарело. Откройте удаление ещё раз.")
        rows = self.select(plan["session_id"], plan["frequency_hz"])
        if sorted(r["id"] for r in rows) != plan["part_ids"]:
            raise RuntimeError("Список записей изменился. Проверьте новое подтверждение.")
        self.guard(rows, plan["frequency_hz"])
        deletion_paths(self.store, self.engine.settings.source, plan)
        # Hide all parts atomically before removal; retries cannot resurrect playback.
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO archive_deletions(id,payload) VALUES(?,?)", (token, json.dumps(plan))
            )
            self.store.db.executemany(
                "DELETE FROM recordings WHERE id=?", [(ident,) for ident in plan["part_ids"]]
            )
        pending = retry_deletions(self.store, self.engine.settings.source)
        self.engine.archive.used_bytes = sum(
            p.stat().st_size for p in self.engine.archive.root.glob("*.wav")
        )
        for ident in plan["session_ids"]:
            self.cleaner.states.pop(ident, None)
            self.cleaner.errors.pop(ident, None)
        return {"deleted_sessions": plan["session_ids"], "pending_file_cleanup": pending}
