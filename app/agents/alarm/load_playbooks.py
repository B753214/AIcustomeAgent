"""Playbook 加载与截断（对齐 fc_monitor.js truncatePlaybook）。"""
from __future__ import annotations

import re
from pathlib import Path

_PLAYBOOK_DIR = Path(__file__).parent / "playbooks"

_IMPORTANT_PATTERNS = [
    re.compile(r"用于把[\s\S]*?(?=\n## )"),
    re.compile(r"排查要点[\s\S]*?(?=\n### |\n## |$)"),
    re.compile(r"常见问题模式[\s\S]*?(?=\n### |\n## |$)"),
    re.compile(r"经验教训[\s\S]*?(?=\n## |$)"),
    re.compile(r"错误类型快速判断[\s\S]*?(?=\n### |\n## |$)"),
]


def truncate_playbook(playbook: str, max_len: int = 3000) -> str:
    if not playbook or len(playbook) <= max_len:
        return playbook or ""
    sections: list[str] = []
    for pat in _IMPORTANT_PATTERNS:
        m = pat.search(playbook)
        if m:
            sections.append(m.group(0).strip())
    result = "\n\n".join(sections) if sections else playbook
    return result[:max_len]


def load_playbook(skill_key: str, *, max_len: int = 3000) -> str:
    """按 skill key 加载 playbook，缺省回退 generic；过长则截断。"""
    playbooks: dict[str, str] = {}
    for md_file in _PLAYBOOK_DIR.glob("*.md"):
        playbooks[md_file.stem] = md_file.read_text(encoding="utf-8")
    raw = playbooks.get(skill_key) or playbooks.get("generic") or ""
    return truncate_playbook(raw, max_len)
