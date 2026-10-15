"""Real metadata, resource and selection boundaries for packaged Agent Skills."""

import hashlib

import pytest

from banking_api.agent_skills import ADVISORY_REFERENCES, AgentSkillCatalog, SkillSelectionError


def package(tmp_path, header, body="Instructions"):
    folder = tmp_path / "example"
    folder.mkdir(exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\n{header}\n---\n{body}", encoding="utf-8")
    return AgentSkillCatalog(tmp_path)


def test_standard_yaml_quotes_block_scalars_and_metadata(tmp_path):
    catalog = package(
        tmp_path,
        'name: "example"\ndescription: >-\n  Explain products\n  when asked.\n'
        'compatibility: Banking application\nmetadata:\n  version: "1.0.0"',
    )
    assert catalog.discover() == [
        {"name": "example", "description": "Explain products when asked.", "version": "1.0.0"}
    ]


@pytest.mark.parametrize(
    "header",
    [
        'name: example\nname: other\ndescription: test\nmetadata:\n  version: "1"',
        'name: example\ndescription: "   "\nmetadata:\n  version: "1"',
        "name: example\ndescription: test\nmetadata:\n  version: 1",
        'name: example\ndescription: test\nmetadata:\n  version: "1"\n  version: "2"',
        "name: example\ndescription: test\nmetadata: [version]",
        'name: example\ndescription: test\nmetadata:\n  version: "1"\n  extra: false',
        'name: example\ndescription: test\nmetadata:\n  version: "1"\nunknown: ignored',
        'name: example\ndescription: !unsafe tag\nmetadata:\n  version: "1"',
    ],
)
def test_invalid_yaml_or_metadata_is_rejected(tmp_path, header):
    with pytest.raises(ValueError):
        package(tmp_path, header)


def test_missing_linked_reference_fails_discovery(tmp_path):
    with pytest.raises(FileNotFoundError):
        package(
            tmp_path,
            'name: example\ndescription: test\nmetadata:\n  version: "1"',
            "[Details](references/missing.md)",
        )


@pytest.mark.parametrize("action", ADVISORY_REFERENCES)
def test_mode_loads_only_relevant_linked_resources_and_correct_hashes(action):
    catalog = AgentSkillCatalog()
    skill = catalog.activate(action, "$wealth-advisory")
    assert skill.skill_id == "wealth-advisory"
    assert set(skill.resources) == {"SKILL.md"} | {
        f"references/{ref}.md" for ref in ADVISORY_REFERENCES[action]
    }
    entry = catalog.read("wealth-advisory/SKILL.md")
    for resource, digest in skill.resources.items():
        assert (
            digest
            == hashlib.sha256(catalog.read(f"wealth-advisory/{resource}").encode()).hexdigest()
        )
        if resource != "SKILL.md":
            assert resource in entry


@pytest.mark.parametrize(
    "action,text",
    [
        ("RECOMMEND", "$wealth-trade-assistance"),
        ("PREPARE_PURCHASE", "$wealth-advisory"),
        ("COMPARE", "$wealth-advisory $wealth-trade-assistance"),
        ("PREPARE_UNKNOWN", ""),
        ("COMPARE", "$unknown-skill"),
    ],
)
def test_explicit_skill_cannot_override_resolved_business_action(action, text):
    with pytest.raises(SkillSelectionError):
        AgentSkillCatalog().activate(action, text)


def test_trade_directions_load_same_contract_without_executable_resources():
    catalog = AgentSkillCatalog()
    for action in ("PREPARE_PURCHASE", "PREPARE_REDEEM"):
        skill = catalog.activate(action, "$wealth-trade-assistance")
        assert set(skill.resources) == {"SKILL.md", "references/input-and-workflow.md"}
        assert "申购用元，赎回用份" in skill.instructions


def test_symlinks_cannot_escape_trusted_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("instructions")
    (root / "escape.md").symlink_to(outside)
    catalog = AgentSkillCatalog(root)
    with pytest.raises(ValueError):
        catalog.read("escape.md")
    with pytest.raises(ValueError):
        catalog.read(str(outside))
    with pytest.raises(ValueError):
        catalog.read("../outside.md")


def test_instruction_hash_describes_loaded_content_after_file_change(tmp_path):
    root = AgentSkillCatalog().root
    import shutil

    shutil.copytree(root / "wealth-advisory", tmp_path / "wealth-advisory")
    catalog = AgentSkillCatalog(tmp_path)
    source = tmp_path / "wealth-advisory" / "SKILL.md"
    original = source.read_text()
    source.write_text(original + "\nReplacement marker")
    skill = catalog.activate("COMPARE")
    assert "Replacement marker" not in skill.instructions
    assert skill.resources["SKILL.md"] == hashlib.sha256(original.encode()).hexdigest()


def test_reference_and_helper_content_are_frozen_with_the_package(tmp_path):
    folder = tmp_path / "example"
    (folder / "references").mkdir(parents=True)
    (folder / "scripts").mkdir()
    reference = folder / "references/details.md"
    helper = folder / "scripts/run.py"
    reference.write_text("Original reference")
    helper.write_text("print('original')")
    (folder / "SKILL.md").write_text(
        '---\nname: example\ndescription: Explain examples\nmetadata:\n  version: "1"\n---\n'
        "[Details](references/details.md) [Helper](scripts/run.py)"
    )
    catalog = AgentSkillCatalog(tmp_path)
    before = catalog.activate_named("example", references=("references/details.md",))
    reference.write_text("Changed instructions")
    helper.write_text("print('changed')")
    assert catalog.activate_named("example", references=("references/details.md",)) == before
    catalog.validate_activation(before)
    after = AgentSkillCatalog(tmp_path).activate_named(
        "example", references=("references/details.md",)
    )
    assert "Changed instructions" in after.instructions
    assert after.resources != before.resources


def test_reference_cannot_link_into_another_skill(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("Other package instructions")
    folder = tmp_path / "example" / "references"
    folder.mkdir(parents=True)
    (folder / "details.md").symlink_to(outside)
    with pytest.raises(ValueError, match="outside its package"):
        package(
            tmp_path,
            'name: example\ndescription: test\nmetadata:\n  version: "1"',
            "[Details](references/details.md)",
        )


def test_every_shipped_package_file_is_declared_and_usable():
    catalog = AgentSkillCatalog()
    for name, entry in catalog.entries.items():
        files = {
            str(path.relative_to(catalog.root / name))
            for path in (catalog.root / name).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        assert files == {"SKILL.md", *entry["linked_resources"]}
        references = tuple(p for p in entry["linked_resources"] if p.startswith("references/"))
        activation = catalog.activate_named(name, references=references)
        assert activation.instructions.strip()
        catalog.validate_activation(activation)
