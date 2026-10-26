"""只提交 advice/ 下的改动，提交后推送。失败只记录，不抛异常。"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from config.investment import ADVICE_ROOT, REPO_ROOT

_GIT_TIMEOUT_SEC = 60


class AdviceCommitter:
    def __init__(self, repo_root: Path = REPO_ROOT, advice_root: Path = ADVICE_ROOT):
        self.repo_root = Path(repo_root)
        self.advice_root = Path(advice_root)
        self.last_error: Optional[str] = None

    def commit(self, message: str) -> bool:
        """有改动就提交并推送，返回是否产生了提交。"""
        self.last_error = None
        rel = os.path.relpath(self.advice_root, self.repo_root)
        try:
            self._git("add", "--", rel)
            if self._git("diff", "--cached", "--quiet", "--", rel, check=False).returncode == 0:
                return False
            self._git("commit", "-q", "-m", message, "--", rel)
        except (subprocess.SubprocessError, OSError, RuntimeError) as e:
            self.last_error = f"提交失败：{e}"
            logging.error(f"[AdviceCommitter] {self.last_error}")
            return False
        logging.info(f"[AdviceCommitter] 已提交：{message}")
        self._push()
        return True

    def _push(self) -> None:
        try:
            if self._git("push", "-q", "origin", "HEAD", check=False).returncode == 0:
                return
            branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            self._git("pull", "-q", "--rebase", "--autostash", "origin", branch, check=False)
            result = self._git("push", "-q", "origin", "HEAD", check=False)
            if result.returncode == 0:
                return
            detail = (result.stderr or result.stdout).strip().splitlines()
            self.last_error = f"推送失败：{detail[-1] if detail else result.returncode}"
        except (subprocess.SubprocessError, OSError, RuntimeError) as e:
            self.last_error = f"推送失败：{e}"
        logging.error(f"[AdviceCommitter] {self.last_error}")

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args], cwd=self.repo_root, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_SEC,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {args[0]}: {(result.stderr or result.stdout).strip()}")
        return result
