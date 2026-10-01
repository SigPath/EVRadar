"""Wczytywanie konfiguracji z YAML (modele, filtry, źródła)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


class ModelTarget(BaseModel):
    brand: str
    model: str
    aliases: list[str] = Field(default_factory=list)
    require_electric: bool = False


class Filters(BaseModel):
    max_price_gross_pln: int | None = None
    max_mileage_km: int | None = None
    min_year: int | None = None


class Notifications(BaseModel):
    enabled: bool = False
    channel: str = "telegram"


class ModelsConfig(BaseModel):
    targets: list[ModelTarget]
    filters: Filters = Field(default_factory=Filters)
    notifications: Notifications = Field(default_factory=Notifications)


class SourceConfig(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool = True
    reason: str | None = None
    delay_min_s: float = 1.0
    delay_max_s: float = 3.0
    concurrency: int = 2
    timeout_s: float = 30.0
    retries: int = 3
    max_pages: int = 5
    params: dict[str, Any] = Field(default_factory=dict)


class SourcesConfig(BaseModel):
    sources: list[SourceConfig]


def load_models_config(path: Path | None = None) -> ModelsConfig:
    """Wczytuje config/models.yaml i spłaszcza `targets` do listy ModelTarget."""
    raw = yaml.safe_load((path or CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))
    targets: list[ModelTarget] = []
    for brand, entries in (raw.get("targets") or {}).items():
        for entry in entries:
            targets.append(ModelTarget(brand=brand, **entry))
    return ModelsConfig(
        targets=targets,
        filters=Filters(**(raw.get("filters") or {})),
        notifications=Notifications(**(raw.get("notifications") or {})),
    )


def load_sources_config(path: Path | None = None) -> SourcesConfig:
    """Wczytuje config/sources.yaml (klucz = source_id)."""
    raw = yaml.safe_load((path or CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))
    sources = [SourceConfig(id=sid, **body) for sid, body in raw["sources"].items()]
    return SourcesConfig(sources=sources)
