#!/usr/bin/env python3
"""Validate the shared product metadata against the checked-in project.

This is the first release gate for the reset architecture. It catches drift
between product metadata, firmware YAML, the custom web UI, docs, and CI before
we start generating larger parts of the project from the product schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

from product_config import load_product


ROOT = Path(__file__).resolve().parent.parent
WEB_APP = ROOT / "docs" / "webserver" / "src" / "app.template.js"


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"Missing file: {rel(path)}")
        return ""
    return path.read_text()


def require_contains(text: str, needle: str, label: str, errors: list[str]) -> None:
    if needle not in text:
        errors.append(f"{label} is missing {needle!r}")


def check_devices(product: dict, errors: list[str]) -> None:
    seen: set[str] = set()
    for device in product["devices"]:
        slug = str(device.get("slug", "")).strip()
        if not slug:
            errors.append("A product device is missing slug")
            continue
        if slug in seen:
            errors.append(f"Duplicate product device slug: {slug}")
        seen.add(slug)

        for field in ("name", "chip", "build_yaml", "public_manifest", "public_beta_manifest"):
            if not str(device.get(field, "")).strip():
                errors.append(f"Device {slug} is missing {field}")

        build_yaml = ROOT / str(device.get("build_yaml", ""))
        read(build_yaml, errors)


def check_esphome_version(product: dict, errors: list[str]) -> None:
    version = str(product["project"].get("esphome_version", "")).strip()
    if not version:
        errors.append("project.esphome_version is required")
        return

    required_refs = [
        ROOT / ".github" / "workflows" / "compile.yml",
        ROOT / ".github" / "workflows" / "release.yml",
        ROOT / "README.md",
        ROOT / "docs" / "install.md",
        ROOT / "docs" / "manual-setup.md",
    ]
    for path in required_refs:
        text = read(path, errors)
        require_contains(text, version, rel(path), errors)

    for path in (ROOT / ".github" / "workflows" / "compile.yml", ROOT / ".github" / "workflows" / "release.yml"):
        text = read(path, errors)
        require_contains(text, f"ghcr.io/esphome/esphome:{version}", rel(path), errors)


def check_workflows(errors: list[str]) -> None:
    compile_workflow = read(ROOT / ".github" / "workflows" / "compile.yml", errors)
    require_contains(compile_workflow, '"product/**"', ".github/workflows/compile.yml", errors)

    docs_workflow = read(ROOT / ".github" / "workflows" / "docs.yml", errors)
    release_workflow = read(ROOT / ".github" / "workflows" / "release.yml", errors)
    for label, text in (
        (".github/workflows/docs.yml", docs_workflow),
        (".github/workflows/release.yml", release_workflow),
    ):
        require_contains(text, "scripts/product_config.py", label, errors)
        require_contains(text, "product/espframe.json", label, errors)


def check_setting(setting: dict, web_text: str, errors: list[str]) -> None:
    key = str(setting.get("key", "")).strip()
    entity = setting.get("entity") or {}
    domain = str(entity.get("domain", "")).strip()
    name = str(entity.get("name", "")).strip()
    default = str(setting.get("default", ""))
    options = [str(option) for option in setting.get("options", [])]

    if not key or not domain or not name:
        errors.append(f"Setting {key or '<missing>'} needs key, entity.domain, and entity.name")
        return

    entity_id = f"{domain}/{name}"
    require_contains(web_text, f'"{entity_id}"', f"web UI mapping for {key}", errors)
    require_contains(web_text, key, f"web UI state key for {key}", errors)
    require_contains(web_text, default, f"web UI default for {key}", errors)
    for option in options:
        require_contains(web_text, option, f"web UI option for {key}", errors)

    firmware_files = setting.get("firmware_files", [])
    if not firmware_files:
        errors.append(f"Setting {key} has no firmware_files")
    for filename in firmware_files:
        text = read(ROOT / str(filename), errors)
        require_contains(text, f'name: "{name}"', f"{filename} entity for {key}", errors)
        for option in options:
            require_contains(text, f'"{option}"', f"{filename} option for {key}", errors)

    docs_files = setting.get("docs_files", [])
    if not docs_files:
        errors.append(f"Setting {key} has no docs_files")
    for filename in docs_files:
        text = read(ROOT / str(filename), errors)
        require_contains(text, default, f"{filename} default for {key}", errors)


def check_settings(product: dict, errors: list[str]) -> None:
    web_text = read(WEB_APP, errors)
    seen: set[str] = set()
    for setting in product["settings"]:
        key = str(setting.get("key", "")).strip()
        if key in seen:
            errors.append(f"Duplicate product setting key: {key}")
        seen.add(key)
        check_setting(setting, web_text, errors)


def main() -> int:
    errors: list[str] = []
    product = load_product()
    check_devices(product, errors)
    check_esphome_version(product, errors)
    check_workflows(errors)
    check_settings(product, errors)

    if errors:
        for error in errors:
            print(f"product contract error: {error}", file=sys.stderr)
        return 1

    print("product contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
