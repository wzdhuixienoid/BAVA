"""Trusted packaged Agent Skills; resources do not grant execution permissions."""

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
ADVISORY_REFERENCES = {
    "RECOMMEND": ("agent-rules", "evidence-and-facts", "recommendation"),
    "EXPLAIN": ("agent-rules", "evidence-and-facts", "recommendation"),
    "COMPARE": ("agent-rules", "evidence-and-facts", "comparison"),
    "PRODUCT_OVERVIEW": ("agent-rules", "evidence-and-facts", "product-overview"),
    "PRODUCT_INTRO": ("agent-rules", "evidence-and-facts", "product-overview"),
    "KNOWLEDGE": (
        "agent-rules",
        "evidence-and-facts",
    ),
    "CATALOGUE": (
        "agent-rules",
        "evidence-and-facts",
    ),
}
TRADE_ACTIONS = {"PREPARE_PURCHASE", "PREPARE_REDEEM"}


class SkillSelectionError(ValueError):
    """An explicit skill cannot handle the resolved action; ask without running it."""


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate YAML metadata key")
        return mapping


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
            header = re.fullmatch(r"---\n(.*?)\n---\n(.*)", content, re.S)
            if not header:
                raise ValueError("SKILL.md requires YAML frontmatter")
            try:
                metadata = yaml.load(header[1], Loader=_UniqueKeyLoader)
            except (yaml.YAMLError, TypeError) as exc:
                raise ValueError("Invalid skill YAML frontmatter") from exc
            if not isinstance(metadata, dict) or set(metadata) - {
                "name",
                "description",
                "license",
                "compatibility",
                "metadata",
                "allowed-tools",
            }:
                raise ValueError("Invalid skill frontmatter fields")
            name, description = metadata.get("name"), metadata.get("description")
            extra = metadata.get("metadata", {})
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
                or len(name) > 64
                or name != directory.name
                or not isinstance(description, str)
                or not description.strip()
                or len(description) > 1024
                or not isinstance(extra, dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in extra.items())
                or not header[2].strip()
            ):
                raise ValueError("Invalid trusted skill metadata")
            for field, limit in (
                ("license", None),
                ("compatibility", 500),
                ("allowed-tools", None),
            ):
                if field in metadata and (
                    not isinstance(metadata[field], str)
                    or not metadata[field].strip()
                    or (limit is not None and len(metadata[field]) > limit)
                ):
                    raise ValueError(f"Invalid skill {field}")
            # Versioning is an application packaging requirement, not a spec requirement.
            version = extra.get("version")
            if not isinstance(version, str) or not version.strip():
                raise ValueError("Packaged skills require metadata.version")
            self.entries[name] = {
                "description": description.strip(),
                "version": version,
                "body": header[2],
                "source": content,
            }
            self.entries[name]["metadata"] = extra
            linked = tuple(
                dict.fromkeys(re.findall(r"\]\(((?:references|scripts)/[^)]+)\)", header[2]))
            )
            self.entries[name]["linked_resources"] = linked
            resource_data = {}
            # Every linked resource must exist inside its own skill package.
            for relative in linked:
                if ".." in Path(relative).parts:
                    raise ValueError("Skill reference outside its package")
                path = (self.root / name / relative).resolve()
                if not path.is_relative_to((self.root / name).resolve()):
                    raise ValueError("Skill reference outside its package")
                data = path.read_bytes()
                if relative.startswith("references/"):
                    if path.suffix != ".md" or not data.decode("utf-8").strip():
                        raise ValueError("Skill references require nonempty Markdown")
                    # Instructions and hashes must use the same immutable process snapshot.
                    data = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
                resource_data[relative] = data
            self.entries[name]["resource_data"] = resource_data

    def read(self, resource: str) -> str:
        if ".." in Path(resource).parts or Path(resource).is_absolute():
            raise ValueError("Skill resource outside trusted root")
        path = (self.root / resource).resolve()
        if not path.is_relative_to(self.root) or path.suffix != ".md":
            raise ValueError("Skill resource outside trusted root")
        # Normalize line endings so standards-compliant CRLF files load correctly.
        return path.read_text(encoding="utf-8")

    def discover(self):
        return [
            {"name": name, "description": item["description"], "version": item["version"]}
            for name, item in self.entries.items()
        ]

    def activate(self, action: str, text: str = "") -> ActivatedSkill:
        if action not in ADVISORY_REFERENCES and action not in TRADE_ACTIONS:
            raise SkillSelectionError(
                "当前动作没有可用的理财技能，请明确要介绍、比较还是准备交易。"
            )
        name = "wealth-trade-assistance" if action in TRADE_ACTIONS else "wealth-advisory"
        explicit = set(re.findall(r"\$([a-z][a-z0-9-]*)", text))
        if explicit - self.entries.keys():
            raise SkillSelectionError(
                "未找到指定的应用技能，请使用已提供的理财顾问或交易协助技能。"
            )
        if explicit and explicit != {name}:
            raise SkillSelectionError(
                f"指定的技能与当前请求不匹配；当前请求适用 ${name}。请核对要办理的业务。"
            )
        refs = ("input-and-workflow",) if action in TRADE_ACTIONS else ADVISORY_REFERENCES[action]
        return self.activate_named(name, references=tuple(f"references/{ref}.md" for ref in refs))

    def activate_named(
        self, name: str, *, references: tuple[str, ...] | None = None
    ) -> ActivatedSkill:
        """Load a known package; callers select linked references, never permissions."""
        if name not in self.entries:
            raise SkillSelectionError(f"未找到应用技能 ${name}。")
        entry = self.entries[name]
        declared = entry["linked_resources"]
        references = () if references is None else references
        if set(references) - set(declared):
            raise ValueError("Skill reference is not declared in SKILL.md")
        resources = {"SKILL.md": hashlib.sha256(entry["source"].encode()).hexdigest()}
        pieces = [entry["body"]]
        for relative in references:
            if not relative.startswith("references/") or not relative.endswith(".md"):
                raise ValueError("Only Markdown references may become instructions")
            data = entry["resource_data"][relative].decode("utf-8")
            resources[relative] = hashlib.sha256(data.encode()).hexdigest()
            pieces.append(data)
        # Helpers are auditable resources, not executable instructions or new tool access.
        for relative in declared:
            if relative.startswith("scripts/"):
                data = entry["resource_data"][relative]
                resources[relative] = hashlib.sha256(data).hexdigest()
        return ActivatedSkill(
            name, entry["version"], entry["description"], "\n\n".join(pieces), resources
        )

    def validate_activation(self, skill: ActivatedSkill) -> None:
        references = tuple(name for name in skill.resources if name.startswith("references/"))
        if skill != self.activate_named(skill.skill_id, references=references):
            raise ValueError("Agent skill instructions and hashes do not match its package")

    def bind_business_skill(self, definition) -> ActivatedSkill:
        skill = self.activate_named(definition.agent_skill_name)
        metadata = self.entries[skill.skill_id]["metadata"]
        expected = {
            "business-skill-id": definition.skill_id,
            "contract-version": str(definition.version),
            "input-schema": definition.input_schema.__name__,
            "output-schema": definition.output_schema.__name__,
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Business Skill contract does not match its standard package")
        if definition.allowed_tools:
            raise ValueError("Business presentation skills cannot grant tool permissions")
        return skill


@lru_cache(maxsize=1)
def packaged_catalog() -> AgentSkillCatalog:
    """Immutable deployed package snapshot; custom/test roots use their own catalogs."""
    return AgentSkillCatalog()
