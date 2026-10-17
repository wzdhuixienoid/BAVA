"""Keep the six architecture layers and every registered Agent discoverable."""

import runpy
from pathlib import Path

from banking_api.api.router import api_router
from banking_api.main import create_app

ROOT = Path(__file__).resolve().parents[3]
SECTIONS = (
    "职责与入口",
    "Skill 与工具",
    "执行与结果",
    "边界与失败处理",
    "源码与验证",
)


def test_framework_and_all_registered_agents_have_complete_indexed_docs():
    checker = runpy.run_path(str(ROOT / "scripts/check_docs.py"))
    index = ROOT / "docs/README.md"
    linked = {path for path, _ in checker["local_links"](index)}
    for document in (
        "agents/README.md", "skills.md", "tools.md", "workflows.md", "plans.md", "domain-api.md"
    ):
        assert ROOT / "docs/architecture" / document in linked

    agent_index = ROOT / "docs/architecture/agents/README.md"
    detailed = {path for path, _ in checker["local_links"](agent_index)}
    agents = create_app().state.agent_registry.all()
    assert agents
    for agent in agents:
        path = agent_index.parent / f"{agent.agent_id.removeprefix('agent:')}.md"
        assert path in linked and path in detailed, agent.agent_id
        content = path.read_text()
        assert f"`{agent.agent_id}`" in content
        for section in SECTIONS:
            assert f"## {section}" in content, (agent.agent_id, section)
        for skill in agent.skills:
            assert skill.skill_id in content, (agent.agent_id, skill.skill_id)
        for capability in agent.allowed_capabilities:
            assert f"`{capability}`" in content, (agent.agent_id, capability)


def test_domain_api_documents_every_registered_business_route_family():
    content = (ROOT / "docs/architecture/domain-api.md").read_text()

    def endpoints(router):
        # FastAPI may retain included routers lazily instead of flattening APIRoute.
        for route in router.routes:
            if endpoint := getattr(route, "endpoint", None):
                yield endpoint
            elif included := getattr(route, "original_router", None):
                yield from endpoints(included)

    modules = {
        endpoint.__module__.removeprefix("banking_api.api.routes.")
        for endpoint in endpoints(api_router)
        if endpoint.__module__.startswith("banking_api.api.routes.")
    }
    assert modules
    for module in modules:
        assert f"| {module}：" in content, module
