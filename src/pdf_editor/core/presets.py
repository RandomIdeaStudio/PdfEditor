"""PDF downsizing presets backed by i18n keys."""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import t


@dataclass(frozen=True)
class CompressionPreset:
    key: str
    registry_id: str
    label_key: str
    short_label_key: str
    description_key: str
    target_dpi: int
    jpeg_quality: int
    max_long_edge: int

    @property
    def label(self) -> str:
        return t(self.label_key)

    @property
    def short_label(self) -> str:
        return t(self.short_label_key)

    @property
    def description(self) -> str:
        return t(self.description_key)


PRESETS: tuple[CompressionPreset, ...] = (
    CompressionPreset(
        key="email",
        registry_id="01_email",
        label_key="preset.email.label",
        short_label_key="preset.email.short",
        description_key="preset.email.desc",
        target_dpi=100,
        jpeg_quality=55,
        max_long_edge=1200,
    ),
    CompressionPreset(
        key="balanced",
        registry_id="02_balanced",
        label_key="preset.balanced.label",
        short_label_key="preset.balanced.short",
        description_key="preset.balanced.desc",
        target_dpi=150,
        jpeg_quality=72,
        max_long_edge=1800,
    ),
    CompressionPreset(
        key="high",
        registry_id="03_high",
        label_key="preset.high.label",
        short_label_key="preset.high.short",
        description_key="preset.high.desc",
        target_dpi=230,
        jpeg_quality=85,
        max_long_edge=2800,
    ),
)

PRESETS_BY_KEY: dict[str, CompressionPreset] = {p.key: p for p in PRESETS}
DEFAULT_PRESET_KEY = "balanced"


def get_preset(key: str) -> CompressionPreset:
    if key not in PRESETS_BY_KEY:
        raise ValueError(f"Unknown compression preset: {key}")
    return PRESETS_BY_KEY[key]
