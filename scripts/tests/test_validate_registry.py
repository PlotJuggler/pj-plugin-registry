import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from validate_registry import validate_structure

LINUX, MACOS = "linux-x86_64", "macos-arm64"


def record(version, floor=None, platforms=(LINUX, MACOS), ext_id="csv-loader"):
    entry = {
        "id": ext_id,
        "name": "CSV Loader",
        "version": version,
        "description": "Loads CSV files.",
        "author": "PlotJuggler",
        "publisher": "PlotJuggler",
        "license": "MPL-2.0",
        "category": "data_loader",
        "platforms": {p: {"url": f"https://example.com/{version}/{p}.zip", "checksum": "sha256:00"} for p in platforms},
    }
    if floor is not None:
        entry["min_sdk_required"] = floor
    return entry


def errors(*extensions):
    return validate_structure({"registry_version": 1, "extensions": list(extensions)})


class MultipleVersionTests(unittest.TestCase):
    def test_several_versions_of_one_id_are_allowed_across_a_floor_raise(self):
        self.assertEqual(errors(record("1.0.0", "0.28.0"), record("1.1.0", "0.34.0")), [])

    def test_a_version_without_a_floor_survives_below_one_that_has_a_floor(self):
        self.assertEqual(errors(record("1.0.0"), record("1.1.0", "0.28.0")), [])

    def test_a_pre_release_floor_is_lower_than_its_release(self):
        self.assertEqual(errors(record("1.0.0", "0.34.0-dev.1"), record("1.1.0", "0.34.0")), [])

    def test_the_same_version_twice_is_rejected(self):
        for again in ("1.0.0", "1.0.0+rebuild"):
            with self.subTest(again=again):
                found = errors(record("1.0.0", "0.28.0", platforms=(LINUX,)), record(again, "0.28.0", platforms=(MACOS,)))
                self.assertTrue(any("duplicate version" in e for e in found), found)


class PruneRuleTests(unittest.TestCase):
    def test_an_older_version_at_the_same_floor_is_rejected(self):
        found = errors(record("1.0.0", "0.28.0", platforms=(LINUX,)), record("1.1.0", "0.28.0", platforms=(LINUX,)))
        self.assertEqual(len(found), 1, found)
        self.assertIn("csv-loader 1.0.0/linux-x86_64", found[0])
        self.assertIn("1.1.0", found[0])

    def test_an_older_version_at_a_higher_floor_is_rejected(self):
        found = errors(record("1.0.0", "0.34.0", platforms=(LINUX,)), record("1.1.0", "0.28.0", platforms=(LINUX,)))
        self.assertEqual(len(found), 1, found)

    def test_two_versions_without_a_floor_are_rejected(self):
        self.assertEqual(len(errors(record("1.0.0", platforms=(LINUX,)), record("1.1.0", platforms=(LINUX,)))), 1)

    def test_an_older_version_kept_for_the_platform_the_newer_one_lacks_is_allowed(self):
        self.assertEqual(
            errors(record("1.0.0", "0.31.0", platforms=(MACOS,)), record("1.1.0", "0.31.0", platforms=(LINUX,))), []
        )

    def test_an_older_version_must_be_trimmed_to_the_platforms_it_still_serves(self):
        found = errors(record("1.0.0", "0.31.0"), record("1.1.0", "0.31.0", platforms=(LINUX,)))
        self.assertEqual(len(found), 1, found)
        self.assertIn("csv-loader 1.0.0/linux-x86_64", found[0])

    def test_a_pre_release_is_older_than_its_release(self):
        found = errors(record("1.0.0-dev.2", "0.28.0", platforms=(LINUX,)), record("1.0.0", "0.28.0", platforms=(LINUX,)))
        self.assertEqual(len(found), 1, found)
        self.assertIn("csv-loader 1.0.0-dev.2/linux-x86_64", found[0])

    def test_other_ids_do_not_supersede(self):
        self.assertEqual(errors(record("1.0.0", "0.28.0", ext_id="a"), record("1.1.0", "0.28.0", ext_id="b")), [])


class SortOrderTests(unittest.TestCase):
    def assert_unsorted(self, *extensions):
        found = errors(*extensions)
        self.assertTrue(any("sorted" in e for e in found), found)

    def test_ids_must_be_sorted(self):
        self.assert_unsorted(record("1.0.0", ext_id="b"), record("1.0.0", ext_id="a"))

    def test_versions_of_one_id_must_be_sorted_oldest_first(self):
        self.assert_unsorted(record("1.1.0", "0.34.0"), record("1.0.0", "0.28.0"))

    def test_versions_sort_by_number_not_by_text(self):
        self.assertEqual(errors(record("1.9.0", "0.28.0"), record("1.10.0", "0.34.0")), [])
        self.assert_unsorted(record("1.10.0", "0.34.0"), record("1.9.0", "0.28.0"))

    def test_a_pre_release_sorts_before_its_release(self):
        self.assertEqual(errors(record("1.0.0-dev.2", "0.28.0"), record("1.0.0-dev.10", "0.31.0"), record("1.0.0", "0.34.0")), [])
        self.assert_unsorted(record("1.0.0", "0.34.0"), record("1.0.0-dev.2", "0.28.0"))


class VersionFormatTests(unittest.TestCase):
    def test_a_version_that_is_not_semver_is_rejected(self):
        for version in ("1.0", "v1.0.0", "1.0.0-", "01.0.0", "1.0.0\n", "", 1):
            with self.subTest(version=version):
                found = errors(record(version))
                self.assertTrue(any("invalid version" in e for e in found), found)

    def test_a_floor_that_is_not_semver_is_rejected(self):
        for floor in ("0.28", "", 0, False):
            with self.subTest(floor=floor):
                found = errors(record("1.0.0", floor))
                self.assertTrue(any("invalid min_sdk_required" in e for e in found), found)

    def test_a_null_floor_is_rejected(self):
        entry = record("1.0.0")
        entry["min_sdk_required"] = None
        found = errors(entry)
        self.assertTrue(any("invalid min_sdk_required" in e for e in found), found)

    def test_optional_version_fields_must_be_strings(self):
        for field in ("min_plotjuggler_version", "suggested_sdk_version"):
            with self.subTest(field=field):
                entry = record("1.0.0")
                entry[field] = None
                found = errors(entry)
                self.assertTrue(any(f"'{field}' must be a string" in e for e in found), found)
                entry[field] = "4.0.0"
                self.assertEqual(errors(entry), [])


if __name__ == "__main__":
    unittest.main()
