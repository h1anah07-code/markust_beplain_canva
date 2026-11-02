#!/usr/bin/env python3
"""Persist a personal MARKUST team and resolve its shared Canva destination.

Local configuration only: this helper does not authenticate, move designs or
prove Canva permissions. All Canva operations use the current connected tools.
"""

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


TEAMS = ("A", "B", "C")
DEFAULT_FOLDERS = Path(__file__).resolve().parent.parent / "references" / "team-folders.json"


def default_profile():
    codex_root = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    return codex_root / "markust" / "bridge-thumbnail-canva.json"


def team_key(value):
    if not isinstance(value, str):
        raise ValueError("Team must be A, B or C")
    key = value.strip().upper().removesuffix("팀").strip()
    if key not in TEAMS:
        raise ValueError("Team must be A, B or C")
    return key


def folder_from_url(value):
    if not isinstance(value, str):
        raise ValueError("A Canva folder URL is required")
    parsed = urlsplit(value.strip())
    match = re.fullmatch(r"/folder/([A-Za-z0-9_-]+)/?", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc not in ("www.canva.com", "canva.com")
            or not match or match.group(1) in ("root", "uploads")):
        raise ValueError("Use an HTTPS Canva folder link: https://www.canva.com/folder/FOLDER_ID")
    folder_id = match.group(1)
    return folder_id, "https://www.canva.com/folder/" + folder_id


def load_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError(f"Invalid or unsupported configuration: {path}")
    return value


def load_folders(path):
    value = load_json(path)
    teams = value.get("teams")
    if not isinstance(teams, dict) or set(teams) != set(TEAMS):
        raise ValueError("Shared folder settings must contain exactly teams A, B and C")
    used = set()
    for key, entry in teams.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("label"), str) or not entry["label"].strip():
            raise ValueError(f"Missing team label: {key}")
        folder_id, url = entry.get("folderId"), entry.get("folderUrl")
        if folder_id is None and url is None:
            continue
        observed_id, canonical_url = folder_from_url(url)
        if observed_id != folder_id or canonical_url != url:
            raise ValueError(f"Folder ID and canonical URL disagree for team {key}")
        if folder_id in used:
            raise ValueError("Different teams must have different destination folders")
        used.add(folder_id)
    return value


def load_profile(path):
    if not path.exists():
        return None
    value = load_json(path)
    if value.get("defaultTeam") not in TEAMS:
        raise ValueError(f"Invalid defaultTeam in {path}; do not silently reset the user's team")
    return value


def save_json(path, value, private=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = 0o600 if private else (path.stat().st_mode & 0o777 if path.exists() else 0o644)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".team-routing-", delete=False) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.chmod(mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def resolve(folders_path, profile_path):
    folders = load_folders(folders_path)
    profile = load_profile(profile_path)
    if profile is None:
        return {"status": "needs_team_selection", "teams": list(TEAMS)}, 2
    key = profile["defaultTeam"]
    entry = folders["teams"][key]
    if entry.get("folderId") is None:
        return {"status": "needs_folder_registration", "team": key, "teamLabel": entry["label"]}, 2
    return {
        "schemaVersion": 1,
        "status": "ready_for_canva_check",
        "team": key,
        "teamLabel": entry["label"],
        "folderId": entry["folderId"],
        "folderUrl": entry["folderUrl"],
        "canvaVerificationRequired": True,
    }, 0


def run(args):
    if args.command == "set-team":
        key = team_key(args.team)
        value = load_profile(args.profile) or {"schemaVersion": 1}
        value["defaultTeam"] = key
        save_json(args.profile, value, private=True)
        return {"status": "team_saved", "team": key, "profilePath": str(args.profile)}, 0
    if args.command == "register-folder":
        key = team_key(args.team)
        folder_id, url = folder_from_url(args.folder_url)
        value = load_folders(args.folders)
        for other_key, entry in value["teams"].items():
            if other_key != key and entry.get("folderId") == folder_id:
                raise ValueError(f"This folder is already assigned to team {other_key}")
        value["teams"][key].update(folderId=folder_id, folderUrl=url)
        save_json(args.folders, value)
        return {"status": "folder_registered", "team": key, "folderId": folder_id,
                "folderUrl": url, "canvaVerificationRequired": True}, 0
    result, code = resolve(args.folders, args.profile)
    if args.out is not None and code == 0:
        if args.out.exists():
            if load_json(args.out) != result:
                raise ValueError("Job destination is already frozen and differs from current settings; use the existing job route or explicitly start a new job")
        else:
            save_json(args.out, result, private=True)
    return result, code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("resolve", "set-team", "register-folder"):
        command = subparsers.add_parser(name)
        command.add_argument("--folders", type=Path, default=DEFAULT_FOLDERS,
                             help="Shared team-to-folder configuration")
        command.add_argument("--profile", type=Path, default=default_profile(),
                             help="Personal settings outside the skill; override only for testing/migration")
        if name in ("set-team", "register-folder"):
            command.add_argument("--team", required=True, help="A, B, C, A팀, B팀 or C팀")
        if name == "register-folder":
            command.add_argument("--folder-url", required=True)
        if name == "resolve":
            command.add_argument("--out", type=Path, help="Freeze a ready destination in a job runtime file")
    args = parser.parse_args()
    try:
        result, code = run(args)
    except (OSError, ValueError) as exc:
        result, code = {"status": "error", "message": str(exc)}, 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
