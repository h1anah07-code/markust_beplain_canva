#!/usr/bin/env python3
"""Offline routing checks; never access Canva or real personal settings."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import team_routing as routing


class TeamRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folders = self.root / "skill" / "references" / "team-folders.json"
        self.profile = self.root / "personal" / "bridge-thumbnail-canva.json"
        self.route = self.root / "job" / "runtime" / "routing.json"
        routing.save_json(self.folders, {
            "schemaVersion": 1,
            "teams": {key: {"label": key + "팀", "folderId": "Test" + key,
                            "folderUrl": "https://www.canva.com/folder/Test" + key}
                      for key in routing.TEAMS},
        })

    def cli(self, command, *options, code=0, folders=None):
        result = subprocess.run([
            sys.executable, "-B", str(Path(routing.__file__)), command,
            "--folders", str(folders or self.folders), "--profile", str(self.profile),
            *options,
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def select(self, team):
        return self.cli("set-team", "--team", team)

    def test_first_use_is_read_only_and_has_no_assumed_team(self):
        before = self.folders.read_bytes()
        result = self.cli("resolve", "--out", str(self.route), code=2)
        self.assertEqual(result["status"], "needs_team_selection")
        self.assertFalse(self.profile.exists())
        self.assertFalse(self.route.exists())
        self.assertEqual(before, self.folders.read_bytes())

    def test_all_teams_resolve_in_new_processes(self):
        for key in routing.TEAMS:
            with self.subTest(team=key):
                self.select(key + "팀")
                result = self.cli("resolve")
                self.assertEqual(result["team"], key)
                self.assertEqual(result["folderId"], "Test" + key)
                self.assertEqual(result["status"], "ready_for_canva_check")
                self.assertTrue(result["canvaVerificationRequired"])

    def test_team_change_only_updates_personal_setting(self):
        before = self.folders.read_bytes()
        self.select("B")
        self.select("c팀")
        self.assertEqual(self.cli("resolve")["folderId"], "TestC")
        self.assertEqual(before, self.folders.read_bytes())
        self.assertEqual(json.loads(self.profile.read_text())["defaultTeam"], "C")
        self.assertEqual(self.profile.stat().st_mode & 0o777, 0o600)

    def test_skill_update_does_not_reset_personal_team(self):
        self.select("B")
        updated = self.root / "updated-skill" / "references" / "team-folders.json"
        value = routing.load_folders(self.folders)
        value["teams"]["B"].update(folderId="NewB", folderUrl="https://www.canva.com/folder/NewB")
        routing.save_json(updated, value)
        result = self.cli("resolve", folders=updated)
        self.assertEqual((result["team"], result["folderId"]), ("B", "NewB"))

    def test_unconfigured_folder_never_writes_a_ready_route(self):
        self.select("A")
        value = routing.load_folders(self.folders)
        value["teams"]["A"].update(folderId=None, folderUrl=None)
        routing.save_json(self.folders, value)
        result = self.cli("resolve", "--out", str(self.route), code=2)
        self.assertEqual(result["status"], "needs_folder_registration")
        self.assertFalse(self.route.exists())
        self.assertEqual(json.loads(self.profile.read_text())["defaultTeam"], "A")

    def test_register_folder_preserves_other_teams_and_profile(self):
        self.select("B")
        before = self.profile.read_bytes()
        original = routing.load_folders(self.folders)
        self.cli("register-folder", "--team", "A", "--folder-url",
                 "https://canva.com/folder/ReplacedA/?utm_source=test")
        updated = routing.load_folders(self.folders)
        self.assertEqual(updated["teams"]["A"]["folderId"], "ReplacedA")
        self.assertEqual(updated["teams"]["B"], original["teams"]["B"])
        self.assertEqual(updated["teams"]["C"], original["teams"]["C"])
        self.assertEqual(before, self.profile.read_bytes())

    def test_duplicate_destination_rejected_without_changes(self):
        before = self.folders.read_bytes()
        result = self.cli("register-folder", "--team", "A", "--folder-url",
                          "https://www.canva.com/folder/TestB", code=2)
        self.assertEqual(result["status"], "error")
        self.assertEqual(before, self.folders.read_bytes())

    def test_invalid_team_cannot_change_selection(self):
        self.select("B")
        before = self.profile.read_bytes()
        self.cli("set-team", "--team", "D", code=2)
        self.assertEqual(before, self.profile.read_bytes())

    def test_bad_folder_urls_cannot_change_map(self):
        before = self.folders.read_bytes()
        for url in ("http://www.canva.com/folder/TestD", "https://evil.example/folder/TestD",
                    "https://www.canva.com.evil.example/folder/TestD",
                    "https://www.canva.com/design/DesignID/edit", "https://www.canva.com/folder/root",
                    "https://user@www.canva.com/folder/TestD"):
            with self.subTest(url=url):
                self.cli("register-folder", "--team", "A", "--folder-url", url, code=2)
                self.assertEqual(before, self.folders.read_bytes())

    def test_corrupt_profile_is_not_reset(self):
        self.profile.parent.mkdir()
        self.profile.write_text("{broken", encoding="utf-8")
        self.cli("resolve", code=2)
        self.cli("set-team", "--team", "C", code=2)
        self.assertEqual(self.profile.read_text(), "{broken")

    def test_unknown_schema_is_not_reset(self):
        routing.save_json(self.profile, {"schemaVersion": 2, "defaultTeam": "B"})
        self.cli("resolve", code=2)
        self.assertEqual(json.loads(self.profile.read_text())["schemaVersion"], 2)

    def test_inconsistent_folder_binding_is_blocked(self):
        self.select("B")
        value = routing.load_folders(self.folders)
        value["teams"]["B"]["folderId"] = "WrongID"
        routing.save_json(self.folders, value)
        self.cli("resolve", "--out", str(self.route), code=2)
        self.assertFalse(self.route.exists())

    def test_frozen_job_does_not_follow_a_later_default_change(self):
        self.select("B")
        self.cli("resolve", "--out", str(self.route))
        before = self.route.read_bytes()
        self.cli("resolve", "--out", str(self.route))
        self.select("C")
        self.cli("resolve", "--out", str(self.route), code=2)
        self.assertEqual(self.route.read_bytes(), before)
        self.assertEqual(self.cli("resolve")["team"], "C")

    def test_configuration_write_failure_reports_incomplete(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["team_routing.py", "set-team", "--team", "B",
                                        "--profile", str(self.profile)]), \
                patch.object(routing, "save_json", side_effect=PermissionError("permission denied")), \
                contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            routing.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")
        self.assertFalse(self.profile.exists())

    def test_default_profile_is_outside_skill(self):
        expected_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        self.assertEqual(routing.default_profile(), expected_root / "markust" / "bridge-thumbnail-canva.json")
        self.assertNotIn(Path(routing.__file__).parent.parent, routing.default_profile().parents)


if __name__ == "__main__":
    unittest.main()
