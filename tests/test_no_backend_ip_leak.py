"""Scan the tracked tree for proprietary tokens and personal paths."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = {".py", ".pyi", ".rs", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".example"}


def _words() -> list[str]:
    return [
        "t" + "df",
        "god_" + "eye",
        "gods_" + "eye",
        "ke" + "rr",
        "22" + "4",
        "14." + "93",
        "ata" + "nh",
        "arcta" + "nh",
        "dyk" + "stra",
        "poly" + "tope",
        "heisen" + "berg",
        "light_" + "cone",
        "causal_" + "cone",
        "pi_" + "gate",
        "pi_" + "decoherence",
        "tape_" + "tension",
        "deco" + "nv",
        "break_" + "point",
        "rerun" + "4",
        "/v1/" + "mitigate",
    ]


def _marker_present(text: str, word: str) -> bool:
    if not word or any(ch not in "0123456789." for ch in word):
        return word in text
    start = 0
    while True:
        found = text.find(word, start)
        if found < 0:
            return False
        before = text[found - 1] if found else ""
        after_at = found + len(word)
        after = text[after_at] if after_at < len(text) else ""
        if not before.isdigit() and not after.isdigit():
            return True
        start = found + 1


def _tracked() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [line for line in out.splitlines() if line]


def test_tracked_tree_has_no_private_markers() -> None:
    blocked = _words()
    identity = ("/" + "Users" + "/", "bah" + "man2017", "bma" + "sarrat", "cursor" + "agent")
    failures: list[str] = []
    for rel in _tracked():
        # Search the repo-relative path itself (filenames included). The host
        # directory prefix is not part of this text.
        rel_l = rel.lower()
        for word in blocked:
            if word.lower() in rel_l:
                failures.append(f"{rel}: path {word}")
        for mark in identity:
            if mark.lower() in rel_l:
                failures.append(f"{rel}: path {mark}")
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT and path.name not in {".gitignore", "LICENSE"}:
            if path.suffix.lower() != ".zk":
                continue
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        for word in blocked:
            if _marker_present(text, word.lower()):
                failures.append(f"{rel}: {word}")
        for mark in identity:
            if mark.lower() in text:
                failures.append(f"{rel}: {mark}")
    assert failures == []
