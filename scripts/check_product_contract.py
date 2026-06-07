#!/usr/bin/env python3
"""Validate the shared product metadata against the checked-in project.

This is the first release gate for the reset architecture. It catches drift
between product metadata, firmware YAML, the custom web UI, docs, and CI before
we start generating larger parts of the project from the product schema.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from product_config import (
    DOCS_SETTINGS_TABLES,
    load_product,
    web_initial_fetch_keys,
    web_settings_metadata,
    web_static_entities_metadata,
)


ROOT = Path(__file__).resolve().parent.parent
WEB_TEMPLATE = ROOT / "docs" / "webserver" / "src" / "app.template.js"
WEB_APP = ROOT / "docs" / "public" / "webserver" / "app.js"
SETTING_DOMAINS = {"number", "select", "switch", "text"}


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


def extract_js_json_var(text: str, var_name: str, errors: list[str]) -> object | None:
    match = re.search(rf"\bvar {re.escape(var_name)} = (.*?);", text)
    if not match:
        errors.append(f"Generated web app is missing {var_name}")
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        errors.append(f"Generated web app {var_name} is not valid JSON: {exc}")
        return None


def firmware_entity_block(text: str, name: str, filename: str, errors: list[str]) -> str:
    needle = f'name: "{name}"'
    lines = text.splitlines()
    name_index = next((idx for idx, line in enumerate(lines) if needle in line), None)
    if name_index is None:
        errors.append(f"{filename} entity is missing {needle!r}")
        return ""

    start = name_index
    while start > 0 and not lines[start].startswith("  - platform:"):
        start -= 1
    if not lines[start].startswith("  - platform:"):
        errors.append(f"{filename} entity block for {name} is missing a platform header")
        return ""

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("  - platform:") or (lines[idx] and not lines[idx].startswith((" ", "#"))):
            end = idx
            break

    return "\n".join(lines[start:end])


def check_path_list(setting: dict, key: str, field: str, errors: list[str]) -> list[str]:
    value = setting.get(field, [])
    if not isinstance(value, list) or not value:
        errors.append(f"Setting {key} must have a non-empty {field} list")
        return []
    result: list[str] = []
    for item in value:
        path = str(item).strip()
        if not path:
            errors.append(f"Setting {key} has a blank entry in {field}")
            continue
        if Path(path).is_absolute() or ".." in Path(path).parts:
            errors.append(f"Setting {key} has unsafe {field} path: {path}")
            continue
        result.append(path)
    return result


def check_setting_schema(setting: dict, errors: list[str]) -> None:
    key = str(setting.get("key", "")).strip()
    entity = setting.get("entity") or {}
    domain = str(entity.get("domain", "")).strip()
    raw_default = setting.get("default", "")
    options = setting.get("options", [])
    developer_options = setting.get("developer_options", [])

    if domain not in SETTING_DOMAINS:
        errors.append(f"Setting {key or '<missing>'} has unsupported domain: {domain or '<missing>'}")
        return

    if domain == "select":
        if not isinstance(raw_default, str):
            errors.append(f"Select setting {key} default must be a string")
        if not isinstance(options, list) or not options:
            errors.append(f"Select setting {key} must define non-empty options")
        elif any(not isinstance(option, str) or not option for option in options):
            errors.append(f"Select setting {key} options must be non-empty strings")
        elif raw_default and raw_default not in options and not str(setting.get("firmware_initial_option", "")).startswith("${"):
            errors.append(f"Select setting {key} default is not in options")

        if developer_options:
            if not isinstance(developer_options, list):
                errors.append(f"Select setting {key} developer_options must be a list")
            elif any(not isinstance(option, str) or not option for option in developer_options):
                errors.append(f"Select setting {key} developer_options must be non-empty strings")
            elif set(developer_options).intersection(options):
                errors.append(f"Select setting {key} developer_options must not duplicate normal options")
    elif domain == "number":
        for field in ("default", "min", "max", "step"):
            if not isinstance(setting.get(field), (int, float)) or isinstance(setting.get(field), bool):
                errors.append(f"Number setting {key} needs numeric {field}")
                return
        minimum = setting["min"]
        maximum = setting["max"]
        default = setting["default"]
        step = setting["step"]
        if minimum > maximum:
            errors.append(f"Number setting {key} min must not exceed max")
        if not minimum <= default <= maximum:
            errors.append(f"Number setting {key} default must be within min/max")
        if step <= 0:
            errors.append(f"Number setting {key} step must be greater than zero")
        if options or developer_options:
            errors.append(f"Number setting {key} must not define options")
    elif domain == "switch":
        if not isinstance(raw_default, bool):
            errors.append(f"Switch setting {key} default must be true or false")
        if options or developer_options:
            errors.append(f"Switch setting {key} must not define options")
    elif domain == "text":
        if not isinstance(raw_default, str):
            errors.append(f"Text setting {key} default must be a string")
        if options or developer_options:
            errors.append(f"Text setting {key} must not define options")


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


def check_generated_web_metadata(product: dict, web_text: str, errors: list[str]) -> None:
    product_settings = extract_js_json_var(web_text, "PRODUCT_SETTINGS", errors)
    if product_settings is not None and product_settings != web_settings_metadata(product["settings"]):
        errors.append("Generated web PRODUCT_SETTINGS does not match product/espframe.json")

    static_entities = extract_js_json_var(web_text, "STATIC_ENTITIES", errors)
    if static_entities is not None and static_entities != web_static_entities_metadata():
        errors.append("Generated web STATIC_ENTITIES does not match product_config.py")

    initial_fetch_keys = extract_js_json_var(web_text, "INITIAL_FETCH_KEYS", errors)
    if initial_fetch_keys is not None and initial_fetch_keys != web_initial_fetch_keys(product["settings"]):
        errors.append("Generated web INITIAL_FETCH_KEYS does not match product/espframe.json")


def check_docs_table_membership(product: dict, errors: list[str]) -> None:
    settings_by_key = {str(setting.get("key", "")): setting for setting in product["settings"]}
    table_memberships: set[tuple[str, str]] = set()
    for path, table_blocks in DOCS_SETTINGS_TABLES.items():
        relative_path = rel(path)
        for block_id, table in table_blocks.items():
            for key in [str(item) for item in table["settings"]]:
                table_memberships.add((relative_path, key))
                setting = settings_by_key.get(key)
                if not setting:
                    errors.append(f"{relative_path} settings table {block_id} references unknown setting {key}")
                    continue
                docs_files = [str(item) for item in setting.get("docs_files", [])]
                if relative_path not in docs_files:
                    errors.append(
                        f"{relative_path} settings table {block_id} includes {key}, "
                        f"but product docs_files does not include {relative_path}"
                    )
    generated_docs_files = {rel(path) for path in DOCS_SETTINGS_TABLES}
    for key, setting in settings_by_key.items():
        for docs_file in [str(item) for item in setting.get("docs_files", [])]:
            if docs_file in generated_docs_files and (docs_file, key) not in table_memberships:
                errors.append(f"{key} declares {docs_file} but is not included in a generated settings table")


def check_docs_table_markers(errors: list[str]) -> None:
    marker_re = re.compile(r"<!-- ESPFRAME:SETTINGS_TABLE ([A-Za-z0-9_-]+) (START|END) -->")
    expected = {
        (rel(path), block_id)
        for path, table_blocks in DOCS_SETTINGS_TABLES.items()
        for block_id in table_blocks
    }
    seen: dict[tuple[str, str], dict[str, int]] = {}
    for docs_path in sorted(ROOT.glob("docs/**/*.md")):
        relative_path = rel(docs_path)
        text = read(docs_path, errors)
        for match in marker_re.finditer(text):
            block_id, side = match.groups()
            key = (relative_path, block_id)
            if key not in expected:
                errors.append(f"{relative_path} has unregistered settings table marker {block_id}")
            seen.setdefault(key, {"START": 0, "END": 0})[side] += 1

    for key in sorted(expected):
        counts = seen.get(key, {"START": 0, "END": 0})
        if counts["START"] != 1 or counts["END"] != 1:
            errors.append(
                f"{key[0]} settings table {key[1]} needs exactly one START and one END marker "
                f"(found {counts['START']} START, {counts['END']} END)"
            )
    for key, counts in sorted(seen.items()):
        if key in expected and (counts["START"] != 1 or counts["END"] != 1):
            continue
        if key not in expected and (counts["START"] != counts["END"] or counts["START"] > 1):
            errors.append(
                f"{key[0]} unregistered settings table {key[1]} has "
                f"{counts['START']} START and {counts['END']} END markers"
            )


def check_setting(setting: dict, web_text: str, errors: list[str]) -> None:
    key = str(setting.get("key", "")).strip()
    entity = setting.get("entity") or {}
    domain = str(entity.get("domain", "")).strip()
    name = str(entity.get("name", "")).strip()
    raw_default = setting.get("default", "")
    default = str(raw_default)
    web_default = json.dumps(raw_default, separators=(",", ":"))
    docs_default = str(setting.get("docs_default", default))
    options = [str(option) for option in setting.get("options", [])]
    developer_options = [str(option) for option in setting.get("developer_options", [])]

    if not key or not domain or not name:
        errors.append(f"Setting {key or '<missing>'} needs key, entity.domain, and entity.name")
        return
    check_setting_schema(setting, errors)

    entity_id = f"{domain}/{name}"
    require_contains(web_text, f'"{entity_id}"', f"web UI mapping for {key}", errors)
    require_contains(web_text, key, f"web UI state key for {key}", errors)
    require_contains(web_text, web_default, f"web UI default for {key}", errors)
    for option in options:
        require_contains(web_text, option, f"web UI option for {key}", errors)
    for option in developer_options:
        require_contains(web_text, option, f"web UI developer option for {key}", errors)

    firmware_files = check_path_list(setting, key, "firmware_files", errors)
    for filename in firmware_files:
        text = read(ROOT / str(filename), errors)
        block = firmware_entity_block(text, name, str(filename), errors)
        for option in options:
            require_contains(block, f'"{option}"', f"{filename} option for {key}", errors)
        for option in developer_options:
            require_contains(block, f'"{option}"', f"{filename} developer option for {key}", errors)
        if entity.get("domain") == "select":
            initial_option = str(setting.get("firmware_initial_option", raw_default))
            if initial_option.startswith("${"):
                if (
                    f"initial_option: {initial_option}" not in block
                    and f'initial_option: "{initial_option}"' not in block
                ):
                    errors.append(f"{filename} initial_option for {key} is missing {initial_option!r}")
            else:
                require_contains(block, f'initial_option: "{initial_option}"', f"{filename} initial_option for {key}", errors)
        if entity.get("domain") == "number":
            for product_field, firmware_field in (
                ("default", "initial_value"),
                ("min", "min_value"),
                ("max", "max_value"),
                ("step", "step"),
            ):
                if product_field in setting:
                    value = str(setting[product_field])
                    require_contains(block, f"{firmware_field}: {value}", f"{filename} {firmware_field} for {key}", errors)
        if entity.get("domain") == "switch" and isinstance(raw_default, bool):
            restore_mode = "RESTORE_DEFAULT_ON" if raw_default else "RESTORE_DEFAULT_OFF"
            require_contains(block, f"restore_mode: {restore_mode}", f"{filename} restore_mode for {key}", errors)

    docs_files = check_path_list(setting, key, "docs_files", errors)
    for filename in docs_files:
        text = read(ROOT / str(filename), errors)
        require_contains(text, docs_default, f"{filename} default for {key}", errors)
        for field in ("docs_label", "docs_description", "docs_format", "docs_type"):
            if setting.get(field):
                require_contains(text, str(setting[field]), f"{filename} {field} for {key}", errors)


def check_settings(product: dict, errors: list[str]) -> None:
    web_template = read(WEB_TEMPLATE, errors)
    web_text = read(WEB_APP, errors)
    check_generated_web_metadata(product, web_text, errors)
    check_docs_table_membership(product, errors)
    check_docs_table_markers(errors)
    require_contains(web_template, "__ESPFRAME_PRODUCT_SETTINGS__", rel(WEB_TEMPLATE), errors)
    require_contains(web_template, "__ESPFRAME_STATIC_ENTITIES__", rel(WEB_TEMPLATE), errors)
    require_contains(web_template, "__ESPFRAME_INITIAL_FETCH_KEYS__", rel(WEB_TEMPLATE), errors)
    for needle in (
        "registerProductSettingStateDefaults",
        "registerProductSettingEndpoints",
        "registerProductSettingEntities",
        "endpoints[key] = eid(parts.domain, parts.name);",
        "ENTITY_STATE_MAP[productSpec.entity] = stateSpec;",
    ):
        require_contains(web_template, needle, rel(WEB_TEMPLATE), errors)
    seen: set[str] = set()
    seen_entities: set[str] = set()
    for setting in product["settings"]:
        key = str(setting.get("key", "")).strip()
        if key in seen:
            errors.append(f"Duplicate product setting key: {key}")
        seen.add(key)
        entity = setting.get("entity") or {}
        entity_id = f'{entity.get("domain", "")}/{entity.get("name", "")}'
        if entity_id in seen_entities:
            errors.append(f"Duplicate product setting entity: {entity_id}")
        seen_entities.add(entity_id)
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
