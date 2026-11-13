#!/usr/bin/env python3
"""Validate registry.json structure, URLs, and checksums.

Usage:
    python3 scripts/validate_registry.py                                        # Structure + URL checks
    python3 scripts/validate_registry.py --download-extensions-and-verify-checksums  # Download all ZIPs and verify SHA256
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

REQUIRED_TOP_LEVEL = ["registry_version", "extensions"]
REQUIRED_EXTENSION = ["id", "name", "version", "description", "author", "publisher", "license", "category", "platforms"]
VALID_PLATFORMS = ["linux-x86_64", "linux-arm64", "macos-x86_64", "macos-arm64", "windows-x86_64", "windows-arm64"]
VALID_CATEGORIES = ["data_loader", "data_stream", "message_parser", "parser", "toolbox", "widget"]

# SemVer 2.0.0 grammar (semver.org). The PlotJuggler host refuses the whole
# registry when one record carries a version outside it.
_IDENTIFIER = r"(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
SEMVER = re.compile(
    rf"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?",
    re.ASCII,
)
# Sorts below every real version: a record without min_sdk_required is admitted by every host.
NO_FLOOR = ()


def semver_key(version) -> tuple | None:
    """Sort key with SemVer 2.0.0 precedence, or None when `version` is not SemVer.

    A pre-release sorts before its release, numeric pre-release identifiers
    compare as numbers and sort before alphanumeric ones, and build metadata is
    ignored: the order the PlotJuggler host uses to pick the highest version.
    """
    match = SEMVER.fullmatch(version) if isinstance(version, str) else None
    if not match:
        return None
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    if not match.group(4):
        return (core, 1, ())
    identifiers = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in match.group(4).split("."))
    return (core, 0, identifiers)


def validate_versions(extensions: list) -> list[str]:
    """Check the rules that let one extension id carry several versions.

    A host admits a record when its min_sdk_required is at most the host SDK
    version, with no upper bound, and installs the highest admitted version
    that ships its platform. The registry therefore keeps version V for
    platform P only while V's min_sdk_required is strictly lower than that of
    every newer version of the same id that ships P; any other platform entry
    can never be picked and must not be stored.
    """
    errors = []
    records = []  # (id, version key, min_sdk_required key, extension)
    for ext in extensions:
        if "id" not in ext or "version" not in ext:
            continue  # already reported as a missing required field
        version = semver_key(ext["version"])
        if version is None:
            errors.append(f"{ext['id']}: invalid version {ext['version']!r} (must be SemVer 2.0.0, e.g. 1.2.3 or 1.2.3-rc.1)")
        floor = NO_FLOOR
        if ext.get("min_sdk_required"):
            floor = semver_key(ext["min_sdk_required"])
            if floor is None:
                errors.append(f"{ext['id']}: invalid min_sdk_required {ext['min_sdk_required']!r} (must be SemVer 2.0.0)")
        records.append((ext["id"], version, floor, ext))
    if errors:
        return errors  # the checks below compare versions

    seen = set()
    for ext_id, version, _, ext in records:
        if (ext_id, version) in seen:
            errors.append(f"{ext_id}: duplicate version {ext['version']} (one record per version, holding every platform)")
        seen.add((ext_id, version))

    order = [(ext_id, version) for ext_id, version, _, _ in records]
    for i, (actual, expected) in enumerate(zip(order, sorted(order))):
        if actual != expected:
            errors.append("Extensions must be sorted by id, then by version (oldest first)")
            errors.append(f"  First violation: '{records[i][0]} {records[i][3]['version']}' at index {i}")
            break

    for ext_id, version, floor, ext in records:
        platforms = ext.get("platforms")
        for platform in platforms if isinstance(platforms, dict) else ():
            for newer_id, newer_version, newer_floor, newer in records:
                if (
                    newer_id == ext_id
                    and newer_version > version
                    and newer_floor <= floor
                    and platform in (newer.get("platforms") or ())
                ):
                    errors.append(
                        f"{ext_id} {ext['version']}/{platform}: superseded by {newer['version']}, whose "
                        "min_sdk_required is not higher; remove this platform entry (and the record, if it was the last)"
                    )
                    break

    return errors


def validate_structure(registry: dict) -> list[str]:
    """Validate JSON structure. Returns list of errors."""
    errors = []

    # Check top-level fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in registry:
            errors.append(f"Missing top-level field: {field}")

    if "extensions" not in registry:
        return errors

    if not isinstance(registry["extensions"], list):
        errors.append("'extensions' must be an array")
        return errors

    # Check each extension
    for i, ext in enumerate(registry["extensions"]):
        ext_id = ext.get("id", f"[index {i}]")

        # Check required fields
        for field in REQUIRED_EXTENSION:
            if field not in ext:
                errors.append(f"{ext_id}: missing required field '{field}'")

        # Check category
        if ext.get("category") and ext["category"] not in VALID_CATEGORIES:
            errors.append(f"{ext_id}: invalid category '{ext['category']}' (valid: {VALID_CATEGORIES})")

        # Check platforms structure
        platforms = ext.get("platforms", {})
        if not isinstance(platforms, dict):
            errors.append(f"{ext_id}: 'platforms' must be an object")
            continue

        for platform, data in platforms.items():
            if platform not in VALID_PLATFORMS:
                errors.append(f"{ext_id}: invalid platform '{platform}' (valid: {VALID_PLATFORMS})")

            if not isinstance(data, dict):
                errors.append(f"{ext_id}/{platform}: platform data must be an object")
                continue

            if "url" not in data:
                errors.append(f"{ext_id}/{platform}: missing 'url'")
            if "checksum" not in data:
                errors.append(f"{ext_id}/{platform}: missing 'checksum'")
            elif not data["checksum"].startswith("sha256:"):
                errors.append(f"{ext_id}/{platform}: checksum must start with 'sha256:'")

    errors.extend(validate_versions(registry["extensions"]))

    return errors


def check_url_exists(url: str, timeout: int = 10) -> tuple[bool, str]:
    """Check if URL is accessible via HEAD request. Returns (success, error_message)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "pj-plugin-registry-validator/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, ""
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, str(e.reason)
    except Exception as e:
        return False, str(e)


def verify_checksum(url: str, expected_checksum: str, timeout: int = 60) -> tuple[bool, str]:
    """Download file and verify SHA256 checksum. Returns (success, error_message)."""
    if not expected_checksum.startswith("sha256:"):
        return False, "Invalid checksum format"

    expected_hash = expected_checksum[7:]  # Remove "sha256:" prefix

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "pj-plugin-registry-validator/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sha256 = hashlib.sha256()
            while chunk := resp.read(8192):
                sha256.update(chunk)
            actual_hash = sha256.hexdigest()

            if actual_hash == expected_hash:
                return True, ""
            return False, f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
    except Exception as e:
        return False, str(e)


def validate_urls(registry: dict) -> list[str]:
    """Check all URLs are accessible. Returns list of errors."""
    errors = []
    for ext in registry.get("extensions", []):
        ext_id = ext.get("id", "unknown")
        for platform, data in ext.get("platforms", {}).items():
            url = data.get("url", "")
            if not url:
                continue

            success, msg = check_url_exists(url)
            if success:
                print(f"  ✓ {ext_id}/{platform}")
            else:
                errors.append(f"{ext_id}/{platform}: URL not accessible - {msg}")
                print(f"  ✗ {ext_id}/{platform}: {msg}")
    return errors


def validate_checksums(registry: dict) -> list[str]:
    """Verify all checksums. Returns list of errors."""
    errors = []
    for ext in registry.get("extensions", []):
        ext_id = ext.get("id", "unknown")
        for platform, data in ext.get("platforms", {}).items():
            url = data.get("url", "")
            checksum = data.get("checksum", "")

            if not url or not checksum:
                continue

            success, msg = verify_checksum(url, checksum)
            if success:
                print(f"  ✓ {ext_id}/{platform}")
            else:
                errors.append(f"{ext_id}/{platform}: checksum mismatch - {msg}")
                print(f"  ✗ {ext_id}/{platform}: {msg}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate registry.json")
    parser.add_argument("--download-extensions-and-verify-checksums", action="store_true",
                        help="Download all extension ZIPs and verify SHA256 checksums (slow)")
    parser.add_argument("--skip-urls", action="store_true", help="Skip URL accessibility checks")
    parser.add_argument("registry_file", nargs="?", default="registry.json", help="Path to registry.json")
    args = parser.parse_args()

    registry_path = Path(args.registry_file)
    if not registry_path.exists():
        print(f"Error: {registry_path} not found")
        sys.exit(1)

    # Load and parse JSON
    print(f"Loading {registry_path}...")
    try:
        with open(registry_path) as f:
            registry = json.load(f)
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        sys.exit(1)
    print("✓ Valid JSON")

    all_errors = []

    # Validate structure
    print("\nValidating structure...")
    structure_errors = validate_structure(registry)
    if structure_errors:
        for err in structure_errors:
            print(f"  ✗ {err}")
        all_errors.extend(structure_errors)
    else:
        ext_count = len(registry.get("extensions", []))
        print(f"  ✓ Structure valid ({ext_count} extensions)")

    # Validate URLs
    if not args.skip_urls:
        print("\nChecking URLs...")
        url_errors = validate_urls(registry)
        all_errors.extend(url_errors)

    # Verify checksums
    if args.download_extensions_and_verify_checksums:
        print("\nDownloading extensions and verifying checksums (this may take a while)...")
        checksum_errors = validate_checksums(registry)
        all_errors.extend(checksum_errors)

    # Summary
    print()
    if all_errors:
        print(f"✗ Validation failed with {len(all_errors)} error(s)")
        sys.exit(1)
    else:
        print("✓ All validations passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
