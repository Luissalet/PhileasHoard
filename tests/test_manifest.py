"""faustus-plugin.json, the README and the docs stay in sync with the code."""

import json
import re
from pathlib import Path

from phileas_hoard import SERVICE
from phileas_hoard.agent_tools import TOOLS
from phileas_hoard.config import DEFAULT_PORT

ROOT = Path(__file__).resolve().parent.parent
BANNED = ("chatgpt", "claude", "openai", "anthropic", "lm studio", "odysseus", "gemini", "copilot", "14track", "aftership app", "parcel app")


def test_manifest_matches_code():
    manifest = json.loads((ROOT / "faustus-plugin.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "phileas" and manifest["name"] == "Phileas's Hoard"
    assert manifest["app"]["health"]["expect"]["service"] == SERVICE == "phileas-hoard"
    assert manifest["defaults"]["APP_URL"].endswith(f":{DEFAULT_PORT}") and DEFAULT_PORT == 5199
    assert manifest["app"]["launch_hint"]["env"]["PHILEAS_PORT"] == str(DEFAULT_PORT)


def test_every_tool_is_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    for tool in TOOLS:
        assert f"`{tool.name}`" in readme or tool.name in api, tool.name


def test_first_lines_are_short():
    for tool in TOOLS:
        assert len(tool.description.splitlines()[0]) <= 110, tool.name


def test_no_other_products_or_slogans_in_docs():
    for path in [ROOT / "README.md", ROOT / "README.es.md", *sorted((ROOT / "docs").glob("*.md"))]:
        text = path.read_text(encoding="utf-8").lower()
        for word in BANNED:
            assert word not in text, f"{word} in {path.name}"


def test_version_matches():
    from phileas_hoard import __version__
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(rf'version = "{re.escape(__version__)}"', pyproject)
