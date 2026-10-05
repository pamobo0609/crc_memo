from typer.testing import CliRunner

from crc_memo.cli import app

runner = CliRunner()


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["process", "list", "search", "show", "todos", "reprocess"]:
        assert command in result.output
