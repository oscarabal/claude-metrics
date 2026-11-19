"""The user's custom commands and skills, from ~/.claude/commands and ~/.claude/skills (read-only).

Only names, the pinned model and the date of the last change are kept.
"""
import os
import re
import time

COMMANDS_DIR = os.environ.get("CLAUDE_COMMANDS_DIR", "/claude-config/commands")
SKILLS_DIR = os.environ.get("CLAUDE_SKILLS_DIR", "/claude-config/skills")


def _frontmatter(path):
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4000)
    except OSError:
        return {}
    m = re.match(r"^---\s*(.*?)\s*---", head, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            key, sep, val = line.partition(":")
            if sep and key.strip() in ("name", "model", "description"):
                out[key.strip()] = val.strip().strip("\"'")
    return out


def _changed(path):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(path)))
    except OSError:
        return None


def commands():
    """[{name, model, changed}] — a subfolder is a namespace, as in Claude Code (folder:command)."""
    out = []
    if not os.path.isdir(COMMANDS_DIR):
        return out
    for folder, _dirs, names in os.walk(COMMANDS_DIR):
        for n in sorted(names):
            if not n.endswith(".md"):
                continue
            path = os.path.join(folder, n)
            rel = os.path.relpath(path, COMMANDS_DIR)[:-3].replace(os.sep, ":").replace("/", ":")
            out.append({"name": rel, "model": _frontmatter(path).get("model"), "changed": _changed(path)})
    return sorted(out, key=lambda c: c["name"])


def skills():
    """[{name, changed}] for every folder with a SKILL.md."""
    out = []
    if not os.path.isdir(SKILLS_DIR):
        return out
    for folder, _dirs, names in os.walk(SKILLS_DIR):
        if "SKILL.md" in names:
            path = os.path.join(folder, "SKILL.md")
            out.append({"name": _frontmatter(path).get("name") or os.path.basename(folder), "changed": _changed(path)})
    return sorted(out, key=lambda s: s["name"])


def available():
    return os.path.isdir(COMMANDS_DIR), os.path.isdir(SKILLS_DIR)
