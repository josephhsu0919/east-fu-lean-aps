from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .history import _json_ready


PROJECT_DIR = Path(__file__).resolve().parents[1] / "data" / "projects"


def safe_project_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()) or "EastFu_APS_Project"


def project_document(name: str, payload: dict[str, Any], version: str = "export", parent_version: str | None = None) -> dict[str, Any]:
    safe_name = safe_project_name(name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "project_id": safe_name,
        "schedule_name": name,
        "version": version,
        "created_at": payload.get("metadata", {}).get("created_at", now),
        "updated_at": now,
        "parent_version": parent_version,
    }
    return {"metadata": metadata, "payload": _json_ready(payload)}


def project_to_bytes(name: str, payload: dict[str, Any], version: str = "export") -> tuple[str, bytes]:
    safe_name = safe_project_name(name)
    document = project_document(name, payload, version=version)
    return f"{safe_name}_{version}.json", json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


def load_project_bytes(data: bytes) -> dict[str, Any]:
    document = json.loads(data.decode("utf-8-sig"))
    if "payload" not in document:
        document = {"metadata": {}, "payload": document}
    return document


def list_projects(path: Path = PROJECT_DIR) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    projects = []
    for file in sorted(path.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            projects.append({"file": file.name, **data.get("metadata", {})})
        except json.JSONDecodeError:
            continue
    return projects


def save_project(name: str, payload: dict[str, Any], save_as: bool = False, path: Path = PROJECT_DIR) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    safe_name = safe_project_name(name)
    existing = sorted(path.glob(f"{safe_name}_v*.json"))
    version = len(existing) + 1 if save_as or not existing else len(existing)
    file_path = path / f"{safe_name}_v{version:03d}.json"
    saved = project_document(name, payload, version=f"v{version:03d}", parent_version=existing[-1].name if save_as and existing else None)
    file_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


def load_project(file_name: str, path: Path = PROJECT_DIR) -> dict[str, Any]:
    file_path = path / file_name
    return json.loads(file_path.read_text(encoding="utf-8"))


def frame_to_records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    return [] if frame is None else _json_ready(frame.to_dict(orient="records"))


def records_to_frame(records: list[dict[str, Any]] | None) -> pd.DataFrame:
    return pd.DataFrame(records or [])
