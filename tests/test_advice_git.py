import subprocess
from pathlib import Path

from storage.advice_git import AdviceCommitter


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def _repo(tmp_path: Path, with_remote: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    if with_remote:
        remote = tmp_path / "remote.git"
        _git(tmp_path, "init", "-q", "--bare", str(remote))
        _git(repo, "remote", "add", "origin", str(remote))
        _git(repo, "push", "-q", "origin", "main")
    return repo


def test_commit_only_advice_paths_and_push(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "advice" / "2026-10").mkdir(parents=True)
    (repo / "advice" / "2026-10" / "2026-10-26-1.md").write_text("a\n", encoding="utf-8")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    committer = AdviceCommitter(repo_root=repo, advice_root=repo / "advice")
    assert committer.commit("advice: 2026-10-26 新增 1 条") is True
    assert committer.last_error is None
    assert _git(repo, "log", "-1", "--format=%s").strip() == "advice: 2026-10-26 新增 1 条"
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["advice/2026-10/2026-10-26-1.md"]
    assert "README.md" in _git(repo, "status", "--porcelain")
    remote_head = _git(tmp_path / "remote.git", "rev-parse", "main")
    assert remote_head == _git(repo, "rev-parse", "HEAD")


def test_nothing_to_commit_returns_false(tmp_path: Path):
    repo = _repo(tmp_path)
    (repo / "advice").mkdir()
    committer = AdviceCommitter(repo_root=repo, advice_root=repo / "advice")
    before = _git(repo, "rev-parse", "HEAD")
    assert committer.commit("advice: 空") is False
    assert _git(repo, "rev-parse", "HEAD") == before


def test_push_failure_is_reported_not_raised(tmp_path: Path):
    repo = _repo(tmp_path, with_remote=False)
    (repo / "advice").mkdir()
    (repo / "advice" / "lessons.md").write_text("l\n", encoding="utf-8")
    committer = AdviceCommitter(repo_root=repo, advice_root=repo / "advice")
    assert committer.commit("advice: x") is True
    assert committer.last_error and "推送失败" in committer.last_error
