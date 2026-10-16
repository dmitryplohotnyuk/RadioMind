import json
import sqlite3
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path, max_rows: int, metadata_full_policy: str = "stop") -> None:
        if metadata_full_policy not in {"stop", "drop_new"}:
            raise ValueError("Unknown metadata quota policy")
        self.metadata_full_policy = metadata_full_policy
        self.metadata_skipped: dict[str, int] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.create_function(
            "casefold", 1, lambda value: str(value).casefold(), deterministic=True
        )
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA journal_size_limit=1048576")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS frequency_profiles (
                frequency_hz INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
                favorite INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS metadata (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, timestamp TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS metadata_kind ON metadata(kind, id DESC);
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archive_deletions (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS digital_attempts (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS channels (
                frequency_hz INTEGER PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
                expires REAL NOT NULL DEFAULT 0, manual INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS digital_channels (
                frequency_hz INTEGER PRIMARY KEY, protocol TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS digital_rejections (
                frequency_hz INTEGER NOT NULL, protocol TEXT NOT NULL,
                PRIMARY KEY(frequency_hz, protocol)
            );
        """)
        self.max_rows = max_rows
        self.path = path
        self.count = int(self.db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0])

    def append(self, kind: str, timestamp: str, payload: dict[str, Any]) -> None:
        if self.count >= self.max_rows:
            if self.metadata_full_policy == "drop_new":
                key = kind if kind in {"event", "observation", "audit"} else "other"
                self.metadata_skipped[key] = self.metadata_skipped.get(key, 0) + 1
                return
            raise RuntimeError("Metadata quota reached; stopped without deleting existing data")
        self.db.execute(
            "INSERT INTO metadata(kind,timestamp,payload) VALUES(?,?,?)",
            (kind, timestamp, json.dumps(payload, allow_nan=False)),
        )
        self.db.commit()
        self.count += 1

    def recent(self, kind: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id,timestamp,payload FROM metadata WHERE kind=? ORDER BY id DESC LIMIT ?",
            (kind, min(max(limit, 1), 200)),
        ).fetchall()
        return [{"id": row[0], "timestamp": row[1], **json.loads(row[2])} for row in rows]

    def close(self) -> None:
        self.db.close()

    def save_digital_attempt(self, payload: dict[str, Any]) -> None:
        # A separate rolling diagnostic buffer remains useful when the PSD log is full.
        with self.db:
            self.db.execute(
                "INSERT INTO digital_attempts(payload) VALUES(?)",
                (json.dumps(payload, allow_nan=False),),
            )
            self.db.execute(
                "DELETE FROM digital_attempts WHERE id NOT IN "
                "(SELECT id FROM digital_attempts ORDER BY id DESC LIMIT 2000)"
            )

    def digital_attempts(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {"id": row[0], **json.loads(row[1])}
            for row in self.db.execute(
                "SELECT id,payload FROM digital_attempts ORDER BY id DESC LIMIT ?",
                (min(max(limit, 1), 200),),
            ).fetchall()
        ]

    def save_recording(self, recording: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO recordings(id,payload) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (recording["id"], json.dumps(recording, allow_nan=False)),
        )
        self.db.commit()

    def digital_mode(self, frequency_hz: int) -> str:
        row = self.db.execute(
            "SELECT protocol FROM digital_channels AS c WHERE frequency_hz=? "
            "AND NOT EXISTS (SELECT 1 FROM digital_rejections AS r "
            "WHERE r.frequency_hz=c.frequency_hz AND r.protocol=c.protocol)",
            (frequency_hz,),
        ).fetchone()
        return str(row[0]) if row else "auto"

    def remember_digital(self, frequency_hz: int, protocol: str) -> None:
        if self.digital_rejected(frequency_hz, protocol):
            return
        self.db.execute(
            "INSERT INTO digital_channels VALUES(?,?) ON CONFLICT(frequency_hz) "
            "DO UPDATE SET protocol=excluded.protocol",
            (frequency_hz, protocol),
        )
        self.db.commit()

    def review_digital_hint(self, frequency_hz: int, protocol: str) -> None:
        """Owner feedback controls forced presets, never recording permissions.

        Recompute after an undo so another remaining negative review still applies.
        Only an explicit positive review newer than negatives lifts their veto.
        """
        row = self.db.execute(
            "SELECT json_extract(payload,'$.review_label') FROM recordings "
            "WHERE json_extract(payload,'$.frequency_hz')=? "
            "AND json_extract(payload,'$.protocol')=? "
            "AND json_extract(payload,'$.review_source')='owner' "
            "AND json_extract(payload,'$.review_label') IN ('speech','noise') "
            "ORDER BY json_extract(payload,'$.reviewed_utc') DESC, rowid DESC LIMIT 1",
            (frequency_hz, protocol),
        ).fetchone()
        if row and row[0] == "noise":
            self.db.execute(
                "INSERT OR IGNORE INTO digital_rejections VALUES(?,?)", (frequency_hz, protocol)
            )
            self.db.execute(
                "DELETE FROM digital_channels WHERE frequency_hz=? AND protocol=?",
                (frequency_hz, protocol),
            )
        else:
            self.db.execute(
                "DELETE FROM digital_rejections WHERE frequency_hz=? AND protocol=?",
                (frequency_hz, protocol),
            )
        self.db.commit()

    def forget_digital(self, frequency_hz: int) -> None:
        self.db.execute("DELETE FROM digital_channels WHERE frequency_hz=?", (frequency_hz,))
        self.db.commit()

    def digital_rejected(self, frequency_hz: int, protocol: str | None) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM digital_rejections WHERE frequency_hz=? AND protocol=?",
                (frequency_hz, protocol),
            ).fetchone()
            is not None
        )

    def recording(self, recording_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload FROM recordings WHERE id=?", (recording_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def recordings(
        self, limit: int = 200, offset: int = 0, q: str = "", since: str = "", until: str = ""
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT payload FROM recordings WHERE "
            "(?='' OR instr(casefold(coalesce(json_extract(payload,'$.title'),'')),casefold(?))>0 "
            "OR instr(printf('%.6f',json_extract(payload,'$.frequency_hz')/1000000.0),?)>0) "
            "AND (?='' OR julianday(json_extract(payload,'$.start_utc'))>=julianday(?)) "
            "AND (?='' OR julianday(json_extract(payload,'$.start_utc'))<julianday(?)) "
            "ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (q, q, q, since, since, until, until, min(limit, 500), max(0, offset)),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def channel(self, frequency_hz: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM channels WHERE frequency_hz=?", (frequency_hz,)
        ).fetchone()
        result = (
            dict(
                zip(
                    ["frequency_hz", "failures", "expires", "manual", "priority", "reason"],
                    row,
                    strict=True,
                )
            )
            if row
            else {
                "frequency_hz": frequency_hz,
                "failures": 0,
                "expires": 0,
                "manual": 0,
                "priority": 0,
                "reason": "",
            }
        )
        profile = self.db.execute(
            "SELECT title,favorite FROM frequency_profiles WHERE frequency_hz=?", (frequency_hz,)
        ).fetchone()
        result.update(
            title=profile[0] if profile else "", favorite=bool(profile[1]) if profile else False
        )
        return result

    def preference(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT payload FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_preference(self, key: str, payload: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET payload=excluded.payload",
                (key, json.dumps(payload)),
            )

    def save_frequency_profile(
        self, frequency: int, title: str | None, favorite: bool | None
    ) -> dict[str, Any]:
        current = self.channel(frequency)
        with self.db:
            self.db.execute(
                "INSERT INTO frequency_profiles VALUES(?,?,?) ON CONFLICT(frequency_hz) "
                "DO UPDATE SET title=excluded.title,favorite=excluded.favorite",
                (
                    frequency,
                    current["title"] if title is None else title.strip(),
                    current["favorite"] if favorite is None else favorite,
                ),
            )
        return self.channel(frequency)

    def session_parts(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT payload FROM recordings "
            "WHERE coalesce(json_extract(payload,'$.session_id'),id)=? "
            "ORDER BY coalesce(json_extract(payload,'$.part_number'),1)",
            (session_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def conversations(
        self,
        limit: int = 200,
        offset: int = 0,
        q: str = "",
        since: str = "",
        until: str = "",
        view: str = "all",
    ) -> list[dict[str, Any]]:
        selected = self.db.execute(
            "SELECT coalesce(json_extract(payload,'$.session_id'),id) AS session_id, "
            "min(julianday(json_extract(payload,'$.start_utc'))) AS started "
            "FROM recordings GROUP BY session_id HAVING "
            "max(?='' OR instr(casefold(coalesce(json_extract(payload,'$.title'),'')),"
            "casefold(?))>0 "
            "OR EXISTS (SELECT 1 FROM frequency_profiles AS fp "
            "WHERE fp.frequency_hz=json_extract(recordings.payload,'$.frequency_hz') "
            "AND instr(casefold(fp.title),casefold(?))>0) "
            "OR instr(printf('%.6f',json_extract(payload,'$.frequency_hz')/1000000.0),?)>0) "
            "AND (?='' OR started>=julianday(?)) AND (?='' OR started<julianday(?)) "
            "AND (?!='favorites' OR max(coalesce(json_extract(payload,'$.favorite'),0))=1) "
            "AND (?!='unlistened' OR max(coalesce(json_extract(payload,'$.listened'),0))=0) "
            "AND (?!='favorite_channels' OR max(EXISTS (SELECT 1 FROM frequency_profiles AS fp "
            "WHERE fp.frequency_hz=json_extract(recordings.payload,'$.frequency_hz') "
            "AND fp.favorite=1))=1) "
            "ORDER BY started DESC LIMIT ? OFFSET ?",
            (
                q,
                q,
                q,
                q,
                since,
                since,
                until,
                until,
                view,
                view,
                view,
                min(limit, 500),
                max(offset, 0),
            ),
        ).fetchall()
        result = []
        for session_id, _ in selected:
            parts = self.session_parts(session_id)
            row = dict(parts[0])
            profile = self.channel(row["frequency_hz"])
            row.update(
                frequency_title=profile["title"],
                frequency_favorite=profile["favorite"],
                frequency_excluded=bool(profile["manual"]),
            )
            row.update(
                id=session_id,
                session_id=session_id,
                part_count=len(parts),
                duration_seconds=sum(p.get("duration_seconds", 0) for p in parts),
                playable=any(p.get("playable", False) for p in parts),
                discontinuity=any(p.get("discontinuity", False) for p in parts),
                status="recording"
                if any(p["status"] == "recording" for p in parts)
                else parts[-1]["status"],
                end_reason=parts[-1].get("end_reason"),
            )
            result.append(row)
        return result

    def unfinished_recordings(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT payload FROM recordings WHERE json_extract(payload,'$.status')='recording'"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_channel(self, channel: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO channels VALUES(?,?,?,?,?,?) ON CONFLICT(frequency_hz) "
            "DO UPDATE SET failures=excluded.failures,expires=excluded.expires,"
            "manual=excluded.manual,priority=excluded.priority,reason=excluded.reason",
            tuple(
                channel[k]
                for k in ["frequency_hz", "failures", "expires", "manual", "priority", "reason"]
            ),
        )
        self.db.commit()

    def channels(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT frequency_hz FROM channels UNION SELECT frequency_hz FROM frequency_profiles "
            "ORDER BY frequency_hz LIMIT 10000"
        )
        return [self.channel(row[0]) for row in rows.fetchall()]
