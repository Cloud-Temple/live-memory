# -*- coding: utf-8 -*-
"""
Regression tests for CLI/admin surface parity.

The web admin console calls MCP tools directly through /api/tool. The script
entry point delegates to Click, while the interactive shell has its own
dispatcher. These tests pin the critical bank supervision commands so future
tool additions do not silently land in one surface only.
"""

import inspect
import sys
from pathlib import Path

from click.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cli.commands import cli  # noqa: E402
from cli import shell  # noqa: E402


def test_mcp_cli_entrypoint_delegates_to_click_cli():
    source = (ROOT / "scripts" / "mcp_cli.py").read_text(encoding="utf-8")

    assert "from cli.commands import cli" in source
    assert "cli()" in source


def test_click_exposes_stale_spaces_with_admin_console_contract():
    result = CliRunner().invoke(cli, ["bank", "stale-spaces", "--help"])

    assert result.exit_code == 0
    assert "--min-notes" in result.output
    assert "--min-age-days" in result.output
    assert "--space-ids" in result.output
    assert "--consolidate" in result.output
    assert "--json" in result.output
    assert "bank_consolidate" in result.output


def test_click_exposes_consolidation_queues():
    result = CliRunner().invoke(cli, ["bank", "consolidation-queues", "--help"])

    assert result.exit_code == 0
    assert "Show consolidation lanes per space" in result.output
    assert "SPACE_IDS" in result.output
    assert "--json" in result.output


def test_shell_dispatcher_exposes_admin_console_bank_supervision_tools():
    assert "bank stale-spaces" in shell.SHELL_COMMANDS
    assert "bank consolidation-queues" in shell.SHELL_COMMANDS

    source = inspect.getsource(shell._handle_bank)
    assert 'sub == "stale-spaces"' in source
    assert 'sub == "consolidation-queues"' in source
    assert '"bank_stale_spaces"' in source
    assert '"bank_consolidation_queues"' in source
    assert '"bank_consolidate"' in source
