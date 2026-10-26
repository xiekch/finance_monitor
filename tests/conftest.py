import sys
from datetime import date
from pathlib import Path

import pytest

# Make project root importable so tests can do `from app import ...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def advice_md():
    def make(day=26, *, symbol="NVDA", direction="看多", status="open", expiry=None,
             reference_price=140, target_price=160, stop_price=120,
             reference_date=None, reviews=""):
        created = date(2026, 10, day)
        expiry = expiry or date(2026, 11, 9)
        ref_date = reference_date or created
        stop_line = f"stop_price: {stop_price}\n" if stop_price is not None else ""
        return (
            "---\n"
            "id: tmp\n"
            f"created_at: {created.isoformat()}\n"
            f"expiry_date: {expiry.isoformat()}\n"
            f"status: {status}\n"
            f"symbol: {symbol}\n"
            "name: 测试标的\n"
            f"direction: {direction}\n"
            "currency: USD\n"
            f"reference_price: {reference_price}\n"
            f"reference_date: {ref_date.isoformat()}\n"
            "reference_url: https://example.com/quote\n"
            f"target_price: {target_price}\n"
            f"{stop_line}"
            "---\n\n"
            "## 理由\n需求还在。后面还有一句。\n\n"
            "## 目标价\n160 美元附近。\n\n"
            "## 失效条件\n跌破 120 美元。\n\n"
            "## 参考价\n140 美元，来自收盘价。\n\n"
            "## 观察条件\n财报前后。\n"
            f"{reviews}"
        )
    return make
