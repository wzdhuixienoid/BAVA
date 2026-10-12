"""Trusted packaged Agent Skills; no user paths or executable resources."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ActivatedSkill:
    skill_id: str
    version: str
    description: str
    instructions: str
    resources: dict[str, str]

    def metadata(self):
        return {
            "skill_id": self.skill_id,
            "skill_version": self.version,
            "resource_hashes": self.resources,
        }


class AgentSkillCatalog:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.entries = {}
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or not (directory / "SKILL.md").is_file():
                continue
            content = self.read(f"{directory.name}/SKILL.md")
            # Packaged metadata intentionally accepts the bounded YAML scalar subset.
            header = re.fullmatch(r"---\n(.*?)\n---\n(.*)", content, re.S)
            if not header:
                raise ValueError("SKILL.md requires YAML frontmatter")
            name = re.search(r"^name: ([a-z0-9-]{1,64})$", header[1], re.M)
            description = re.search(r"^description: (.+)$", header[1], re.M)
            version = re.search(r'^  version: "([\d.]+)"$', header[1], re.M)
            if (
                not name
                or name[1] != directory.name
                or "--" in name[1]
                or name[1].startswith("-")
                or name[1].endswith("-")
                or not description
                or len(description[1]) > 1024
                or not version
            ):
                raise ValueError("Invalid trusted skill metadata")
            self.entries[name[1]] = {
                "description": description[1],
                "version": version[1],
                "body": header[2],
            }

    def read(self, resource: str) -> str:
        if ".." in Path(resource).parts or Path(resource).is_absolute():
            raise ValueError("Skill resource outside trusted root")
        path = (self.root / resource).resolve()
        if not path.is_relative_to(self.root) or path.suffix != ".md":
            raise ValueError("Skill resource outside trusted root")
        return path.read_text(encoding="utf-8")

    def discover(self):
        return [
            {"name": name, "description": item["description"], "version": item["version"]}
            for name, item in self.entries.items()
        ]

    def activate(self, action: str, text: str = "") -> ActivatedSkill:
        name = "wealth-trade-assistance" if action.startswith("PREPARE_") else "wealth-advisory"
        explicit = re.findall(r"\$([a-z][a-z0-9-]*)", text)
        if explicit:
            if explicit[0] not in self.entries:
                raise ValueError("Unknown skill")
            name = explicit[0]
        entry = self.entries[name]
        refs = (
            ["input-and-workflow"]
            if name == "wealth-trade-assistance"
            else ["evidence-and-facts"]
            + (
                ["comparison"]
                if action == "COMPARE"
                else ["product-overview"]
                if action == "PRODUCT_OVERVIEW"
                else ["recommendation"]
                if action in {"RECOMMEND", "EXPLAIN"}
                else []
            )
        )
        resources = {}
        pieces = [entry["body"]]
        for relative in ["SKILL.md"] + [f"references/{ref}.md" for ref in refs]:
            data = self.read(f"{name}/{relative}")
            resources[relative] = hashlib.sha256(data.encode()).hexdigest()
            if relative != "SKILL.md":
                pieces.append(data)
        return ActivatedSkill(
            name, entry["version"], entry["description"], "\n\n".join(pieces), resources
        )
