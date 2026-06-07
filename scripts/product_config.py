#!/usr/bin/env python3
"""Shared Espframe product metadata loader.

The product JSON is intentionally small and dependency-free so release scripts,
local checks, and CI workflows can all read the same device and setting data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PRODUCT_PATH = ROOT / "product" / "espframe.json"


def load_product(path: Path = PRODUCT_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"Product metadata not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Product metadata is not valid JSON: {exc}") from exc

    if not isinstance(data.get("project"), dict):
        raise RuntimeError("Product metadata must contain a project object")
    if not isinstance(data.get("devices"), list) or not data["devices"]:
        raise RuntimeError("Product metadata must contain at least one device")
    if not isinstance(data.get("settings"), list):
        raise RuntimeError("Product metadata must contain a settings list")
    return data


def project_value(key: str, default: str = "") -> str:
    value = load_product()["project"].get(key, default)
    return str(value)


def devices_by_slug() -> dict[str, dict[str, Any]]:
    devices = {}
    for device in load_product()["devices"]:
        slug = str(device.get("slug", "")).strip()
        if not slug:
            raise RuntimeError("Every product device needs a slug")
        if slug in devices:
            raise RuntimeError(f"Duplicate product device slug: {slug}")
        devices[slug] = device
    return devices


def settings() -> list[dict[str, Any]]:
    return list(load_product()["settings"])
