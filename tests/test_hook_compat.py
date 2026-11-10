"""Connector field aliases must keep repository, branch and forbidden-tool checks."""
from pathlib import Path
import runpy
import pytest

POLICY = runpy.run_path(str(Path(__file__).parents[1]/'.codex/hooks/policy.py'))
risk = POLICY['risk_reason']


@pytest.mark.parametrize('repository', ['jcy9066/unitree-go2-slam-nav2', 'other/repo'])
@pytest.mark.parametrize('branch', ['fix/l1-rgbd-forward-only', 'main', 'master', 'refs/heads/main', ''])
def test_connector_repo_and_branch_aliases(repository, branch):
    result = risk('mcp__github__create_branch',
                  dict(repository_full_name=repository, branch_name=branch), str(Path.cwd()))
    assert (result is None) == (repository == 'jcy9066/unitree-go2-slam-nav2' and branch == 'fix/l1-rgbd-forward-only')


@pytest.mark.parametrize('name', ['merge_pull_request', 'enable_auto_merge', 'actions_run_trigger', 'update_ref', 'delete_file'])
def test_forbidden_operations_stay_forbidden(name):
    assert risk('mcp__github__'+name, {}, str(Path.cwd()))


def test_conflicting_repository_identifiers_are_rejected():
    assert risk('mcp__github__create_branch', dict(
        repository_full_name='jcy9066/unitree-go2-slam-nav2', owner='other', repo='repo',
        branch_name='fix/test'), str(Path.cwd()))
