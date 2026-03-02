import pytest
from llmos.planner.heuristic import HeuristicPlanner


@pytest.fixture
def planner():
    return HeuristicPlanner()


def test_venv_and_tests(planner):
    steps = planner.plan("create venv and run tests")
    assert len(steps) == 3
    assert steps[0].command == "python3 -m venv .venv"
    assert "pip install" in steps[1].command
    assert "pytest" in steps[2].command


def test_venv_only(planner):
    steps = planner.plan("setup a python venv")
    assert len(steps) == 1
    assert steps[0].command == "python3 -m venv .venv"


def test_install_dependencies(planner):
    steps = planner.plan("install dependencies")
    assert len(steps) == 1
    assert "pip install" in steps[0].command


def test_run_tests(planner):
    steps = planner.plan("run tests")
    assert len(steps) == 1
    assert "pytest" in steps[0].command


def test_list_files(planner):
    steps = planner.plan("list files")
    assert len(steps) == 1
    assert steps[0].command == "ls -la"


def test_disk_usage(planner):
    steps = planner.plan("check disk usage")
    assert len(steps) == 1
    assert steps[0].command == "df -h"


def test_git_push(planner):
    steps = planner.plan("git push")
    assert len(steps) == 1
    assert steps[0].command == "git push"


def test_catchall(planner):
    steps = planner.plan("echo hello world")
    assert len(steps) == 1
    assert steps[0].command == "echo hello world"


def test_catchall_preserves_case(planner):
    steps = planner.plan("MyCustomScript.sh")
    assert steps[0].command == "MyCustomScript.sh"
