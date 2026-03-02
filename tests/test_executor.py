import pytest
from llmos.executor.runner import Executor


@pytest.fixture
def executor(tmp_path):
    return Executor(workspace_dir=tmp_path, timeout_seconds=5)


def test_basic_echo(executor):
    result = executor.run("echo hello")
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


def test_exit_nonzero(executor):
    result = executor.run("exit 42")
    assert result.exit_code == 42


def test_stderr_captured(executor):
    result = executor.run("echo error >&2")
    assert result.exit_code == 0
    assert "error" in result.stderr


def test_timeout(tmp_path):
    ex = Executor(workspace_dir=tmp_path, timeout_seconds=1)
    result = ex.run("sleep 10")
    assert result.timed_out is True
    assert result.exit_code == -1


def test_cwd_is_workspace(executor, tmp_path):
    result = executor.run("pwd")
    assert result.exit_code == 0
    assert str(tmp_path) in result.stdout


def test_file_created_in_workspace(executor, tmp_path):
    result = executor.run("touch testfile.txt")
    assert result.exit_code == 0
    assert (tmp_path / "testfile.txt").exists()


def test_multiline_output(executor):
    result = executor.run("printf 'line1\\nline2\\nline3'")
    assert result.exit_code == 0
    assert "line1" in result.stdout
    assert "line3" in result.stdout


def test_timestamps_set(executor):
    result = executor.run("echo hi")
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.finished_at >= result.started_at
