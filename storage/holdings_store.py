"""持仓配置的读取，以及持仓报告的本地存取。报告含金额，只留在 data/ 下，不进 git。"""
from __future__ import annotations

import json
import logging
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

from config.holdings import (
    HOLDINGS_EXAMPLE_FILE,
    HOLDINGS_FILE,
    HOLDINGS_REPORT_ROOT,
    PREVIOUS_REPORT_MAX_AGE_DAYS,
)
from models.holdings import HoldingsConfig, HoldingsConfigError, parse_holdings_config


def load_holdings_config(path: Path = HOLDINGS_FILE) -> HoldingsConfig:
    """每次调用都重新读文件，改了持仓不用重启。"""
    path = Path(path)
    if not path.exists():
        raise HoldingsConfigError(
            f"找不到持仓配置 {path}，请复制 {HOLDINGS_EXAMPLE_FILE.name} 为 {path.name} 后填写"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise HoldingsConfigError(f"持仓配置格式错误：{e}") from e
    return parse_holdings_config(data)


class HoldingsReportStore:
    """每天一份 YYYY-MM-DD.md（给人看）和同名 .json（每个持仓的动作，供下次对照）。"""

    def __init__(self, root: Path = HOLDINGS_REPORT_ROOT):
        self.root = Path(root)

    def save(self, day: date, markdown: str, actions: Dict[str, str]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        report = self.root / f"{day.isoformat()}.md"
        _atomic_write(report, markdown)
        payload = {"date": day.isoformat(), "actions": actions}
        _atomic_write(
            report.with_suffix(".json"),
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def save_raw(self, day: date, text: str) -> Path:
        """回复里没有合法建议时只留原文。不写动作记录，也不覆盖当天已有的报告。"""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{day.isoformat()}-raw.md"
        _atomic_write(path, text)
        return path

    def latest_actions(
        self, today: date, max_age_days: int = PREVIOUS_REPORT_MAX_AGE_DAYS,
    ) -> Optional[Tuple[date, Dict[str, str]]]:
        """不晚于今天、在 max_age_days 天内的最近一份动作记录。"""
        earliest = today - timedelta(days=max_age_days)
        candidates = []
        for path in self.root.glob("*.json"):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if earliest <= day <= today:
                candidates.append((day, path))
        for day, path in sorted(candidates, reverse=True):
            try:
                actions = json.loads(path.read_text(encoding="utf-8"))["actions"]
            except (OSError, ValueError, KeyError, TypeError) as e:
                logging.warning(f"[HoldingsReportStore] 跳过读不了的动作记录 {path}: {e}")
                continue
            if isinstance(actions, dict):
                return day, {str(k): str(v) for k, v in actions.items()}
        return None


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
