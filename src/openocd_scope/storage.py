from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import ProjectConfig


def save_project(path: str, project: ProjectConfig) -> None:
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)


def load_project(path: str) -> ProjectConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ProjectConfig.from_dict(data)


def export_csv(path: str, rows: list[dict[str, float | int]], names: list[str]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", *names])
        for row in rows:
            writer.writerow([f"{float(row['time_s']):.6f}", *(row.get(name, "") for name in names)])
