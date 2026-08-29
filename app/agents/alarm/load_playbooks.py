from pathlib import Path

playbook_dir = Path(__file__).parent / "playbooks"

def load_playbook(skill_key: str) -> str:
    """加载所有 playbooks。"""
    playbooks = {}
    for md_file in playbook_dir.glob("*.md"):
        playbooks[md_file.stem] = md_file.read_text(encoding="utf-8")
    return playbooks.get(skill_key) or playbooks.get("generic") or ""
