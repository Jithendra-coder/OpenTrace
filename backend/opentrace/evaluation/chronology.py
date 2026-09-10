"""Tamper-evident local chronology for the final Gate B v3 run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ChronologyState(StrEnum):
    PROTOCOL_FROZEN = "PROTOCOL_FROZEN"
    DATASET_GENERATED = "DATASET_GENERATED"
    DATASET_VALIDATED = "DATASET_VALIDATED"
    SPLIT_SEALED = "SPLIT_SEALED"
    DEVELOPMENT_COMPLETE = "DEVELOPMENT_COMPLETE"
    PRE_TEST_FROZEN = "PRE_TEST_FROZEN"
    TEST_ACCESSED = "TEST_ACCESSED"
    FORMAL_EVALUATION_COMPLETE = "FORMAL_EVALUATION_COMPLETE"


_ORDER = tuple(ChronologyState)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass
class ChronologyLog:
    path: Path
    events: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path | str) -> ChronologyLog:
        target = Path(path)
        events = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
        log = cls(target, events)
        log.verify()
        return log

    @classmethod
    def create(cls, path: Path | str) -> ChronologyLog:
        target = Path(path)
        if target.exists():
            raise FileExistsError(f"chronology log already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return cls(target, [])

    @property
    def state(self) -> ChronologyState | None:
        return ChronologyState(self.events[-1]["event_type"]) if self.events else None

    def append(
        self,
        event_type: ChronologyState,
        *,
        artifact_digests: dict[str, str],
        configuration_digest: str,
    ) -> dict[str, Any]:
        expected_index = len(self.events)
        if expected_index >= len(_ORDER) or event_type is not _ORDER[expected_index]:
            raise ValueError(f"illegal chronology transition to {event_type}")
        previous = self.events[-1]["event_hash"] if self.events else "0" * 64
        event = {
            "event_index": expected_index,
            "event_type": event_type.value,
            "previous_event_hash": previous,
            "artifact_digests": dict(sorted(artifact_digests.items())),
            "configuration_digest": configuration_digest,
        }
        event["event_hash"] = _digest(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        self.events.append(event)
        return event

    def verify(self) -> None:
        previous = "0" * 64
        for index, event in enumerate(self.events):
            if event.get("event_index") != index:
                raise ValueError("chronology event index is not contiguous")
            if event.get("previous_event_hash") != previous:
                raise ValueError("chronology hash chain is broken")
            event_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key != "event_hash"}
            if event_hash != _digest(body):
                raise ValueError("chronology event digest mismatch")
            if event.get("event_type") != _ORDER[index].value:
                raise ValueError("chronology event order is invalid")
            previous = event_hash

    @property
    def chain_digest(self) -> str:
        self.verify()
        return self.events[-1]["event_hash"] if self.events else "0" * 64
