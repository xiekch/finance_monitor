# Investment Advice Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers-executing-plans to implement this plan task-by-task.

**Goal:** 增加四条独立任务：模型自己搜索并每天给出 1～3 条带目标价的投资建议，再按到期、周、月三档把价格和逻辑复盘追加到 Markdown，供下一次建议读取。

**Architecture:** 建议和复盘都不接现有抓取步骤。每条建议是 git 跟踪的 `advice/YYYY-MM/{id}.md`，价格类字段放在文首，复盘追加在原文件，经验追加到 `advice/lessons.md`。任务通过挂载本仓库的 `CursorLLMClient.complete(prompt)` 搜索、读取历史并写作，合法结果原子写入、只提交 `advice/` 并 push，再用现有企业微信 webhook 逐条推送。设计见 `docs/plans/2026-10-26-investment-advice-design.md`。

**Tech Stack:** Python 3.9+、现有 APScheduler 任务注册、Cursor cloud agent、`WeChatNotifier`、pytest。不新增依赖。

---

### Task 0: 确认 cloud agent 能联网、能读仓库（手动，不写代码）

1. 在 Python 交互环境里用现有 `CursorLLMClient._create_and_wait("搜索 NVDA 最新收盘价，给出价格、日期和来源链接")` 跑一次。结果里要有当天或最近交易日的价格和可打开的链接。
2. 临时在 `_create_agent` 的请求体里加 `"repos": [{"url": "https://github.com/xiekch/finance_monitor", "startingRef": "main"}]`，提示词写「读 README.md 第一行并原样输出，不要修改任何文件」。结果要和仓库里的内容一致。

任一项不满足就停下，回到设计讨论，不要继续实现。验证完撤销临时改动。

---

### Task 1: 建议文档的解析、渲染和校验

**Files:**
- Modify: `tests/conftest.py`
- Create: `models/advice.py`
- Test: `tests/test_advice_doc.py`

**Step 1: Write the failing test**

在 `tests/conftest.py` 追加样本 fixture，后续测试共用：

```python
from datetime import date

import pytest


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
```

`tests/test_advice_doc.py`：

```python
from datetime import date

from models.advice import parse_advice_markdown, render_advice_markdown, validate_advice


def test_roundtrip_keeps_frontmatter_and_sections(advice_md):
    doc = parse_advice_markdown(advice_md())
    again = parse_advice_markdown(render_advice_markdown(doc))
    assert again.created_at == date(2026, 10, 26)
    assert again.expiry_date == date(2026, 11, 9)
    assert again.direction == "看多"
    assert again.currency == "USD"
    assert again.reference_price == 140
    assert again.target_price == 160
    assert again.stop_price == 120
    assert again.reference_url == "https://example.com/quote"
    assert again.sections["理由"].startswith("需求还在")
    assert validate_advice(again) == []


def test_stop_price_is_optional(advice_md):
    doc = parse_advice_markdown(advice_md(stop_price=None))
    assert doc.stop_price is None
    assert "stop_price" not in render_advice_markdown(doc)
    assert validate_advice(doc) == []


def test_reject_long_target_or_stop_on_wrong_side(advice_md):
    assert any("目标价" in e for e in validate_advice(parse_advice_markdown(advice_md(target_price=140))))
    assert any("失效" in e for e in validate_advice(parse_advice_markdown(advice_md(stop_price=150))))


def test_reject_short_target_or_stop_on_wrong_side(advice_md):
    ok = parse_advice_markdown(advice_md(direction="看空", target_price=120, stop_price=150))
    assert validate_advice(ok) == []
    bad_target = parse_advice_markdown(advice_md(direction="看空", target_price=150, stop_price=160))
    assert any("目标价" in e for e in validate_advice(bad_target))
    bad_stop = parse_advice_markdown(advice_md(direction="看空", target_price=120, stop_price=130))
    assert any("失效" in e for e in validate_advice(bad_stop))


def test_watch_allows_target_on_either_side(advice_md):
    doc = parse_advice_markdown(advice_md(direction="观望", target_price=130, stop_price=None))
    assert validate_advice(doc) == []


def test_reject_stale_or_future_reference(advice_md):
    assert validate_advice(parse_advice_markdown(advice_md(reference_date=date(2026, 10, 23)))) == []
    stale = parse_advice_markdown(advice_md(reference_date=date(2026, 10, 22)))
    assert any("参考价" in e for e in validate_advice(stale))
    future = parse_advice_markdown(advice_md(reference_date=date(2026, 10, 27)))
    assert any("参考价" in e for e in validate_advice(future))


def test_reject_expiry_beyond_31_days(advice_md):
    assert validate_advice(parse_advice_markdown(advice_md(expiry=date(2026, 11, 26)))) == []
    doc = parse_advice_markdown(advice_md(expiry=date(2026, 11, 27)))
    assert any("到期日" in e for e in validate_advice(doc))


def test_reject_symbol_already_open(advice_md):
    doc = parse_advice_markdown(advice_md())
    assert any("标的" in e for e in validate_advice(doc, open_symbols={"NVDA"}))


def test_reject_empty_section(advice_md):
    doc = parse_advice_markdown(advice_md())
    doc.sections["观察条件"] = "  "
    assert any("观察条件" in e for e in validate_advice(doc))
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_advice_doc.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'models.advice'`

**Step 3: Write minimal implementation**

`models/advice.py` 提供 `AdviceDoc`（dataclass）、`InvestmentMessage`（只有 `markdown: str`）、`parse_advice_markdown`、`render_advice_markdown`、`validate_advice(doc, open_symbols=frozenset())`。

- 文首是 `---` 包裹的 `key: value`，不要引入 PyYAML。日期字段转 `date`，价格字段转 `float`，`stop_price` 缺省为 `None`。
- 正文章节按 `## ` 切分。`## 复盘 ...` 放进 `reviews: list[str]`，每项保留自己的标题。其余放进 `sections: dict[str, str]`。
- 价格只从文首读取，不从正文抠数字。
- `validate_advice` 按设计文档「以下任一情况，该条不落盘」逐条检查，错误信息里带上关键字：目标价、失效、参考价、到期日、标的、方向、章节名。
- 渲染时文首键顺序固定，`stop_price` 为 `None` 时省略；五节顺序固定，复盘按原顺序接在后面。整数值的价格渲染成不带 `.0` 的形式。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_advice_doc.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add models/advice.py tests/conftest.py tests/test_advice_doc.py
git commit -m "$(cat <<'EOF'
feat: parse and validate investment advice markdown

EOF
)"
```

---

### Task 2: Markdown 存储、档期和经验摘录

**Files:**
- Create: `config/investment.py`
- Create: `storage/advice_store.py`
- Test: `tests/test_advice_store.py`

**Step 1: Write the failing test**

```python
from datetime import date
from pathlib import Path

from models.advice import parse_advice_markdown
from storage.advice_store import AdviceStore, previous_month, previous_week


def _save(store, advice_md, *args, **kwargs):
    return store.save_new(parse_advice_markdown(advice_md(*args, **kwargs)))


def test_save_puts_file_in_month_dir_and_assigns_id(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    first = _save(store, advice_md, 26)
    second = _save(store, advice_md, 26, symbol="AAPL")
    assert first.id == "2026-10-26-1"
    assert second.id == "2026-10-26-2"
    assert (tmp_path / "2026-10" / "2026-10-26-1.md").is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_due_includes_missed_and_week_month_cohorts(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    _save(store, advice_md, 19, expiry=date(2026, 10, 25))
    _save(store, advice_md, 10, symbol="MISSED", expiry=date(2026, 10, 20))
    _save(store, advice_md, 15, symbol="DONE", status="closed", expiry=date(2026, 10, 22))
    _save(store, advice_md, 25, symbol="AAPL", expiry=date(2026, 11, 20))
    today = date(2026, 10, 26)
    assert [d.created_at.day for d in store.list_due(today)] == [10, 19]
    start, end = previous_week(today)
    assert (start, end) == (date(2026, 10, 19), date(2026, 10, 25))
    assert [d.created_at.day for d in store.list_created_between(start, end)] == [19, 25]
    assert previous_month(date(2026, 11, 1)) == (date(2026, 10, 1), date(2026, 10, 31))


def test_open_summaries_use_price_and_logic_lines(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    _save(store, advice_md, 26)
    _save(store, advice_md, 25, symbol="AAPL", reviews=(
        "\n## 复盘 2026-10-26 周回溯\n"
        "- 价格：未碰到目标价。\n"
        "- 逻辑：催化剂未落地。\n"
        "- 事件过程：无。\n"
        "- 经验：无\n"
    ))
    _save(store, advice_md, 20, symbol="OLD", status="closed", expiry=date(2026, 10, 25))
    _save(store, advice_md, 1, symbol="STALE", expiry=date(2026, 10, 25))
    lines = store.open_summaries(date(2026, 10, 26))
    assert len(lines) == 2
    nvda = next(line for line in lines if "NVDA" in line)
    aapl = next(line for line in lines if "AAPL" in line)
    assert "尚无复盘" in nvda
    assert "需求还在。" in nvda and "后面还有一句" not in nvda
    assert "未碰到目标价" in aapl and "催化剂未落地" in aapl
    assert "## 复盘" not in aapl
    assert store.open_symbols(date(2026, 10, 26)) == {"NVDA", "AAPL"}


def test_last_30_lessons(tmp_path: Path):
    store = AdviceStore(tmp_path)
    for i in range(35):
        store.append_lesson(f"经验 {i}", advice_id="x", symbol="NVDA", kind="到期结案", on=date(2026, 10, 1))
    recent = "\n".join(store.recent_lessons(30))
    assert len(store.recent_lessons(30)) == 30
    assert "经验 4\n" not in recent + "\n"
    assert "经验 5" in recent and "经验 34" in recent
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_advice_store.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'storage.advice_store'`

**Step 3: Write minimal implementation**

`config/investment.py` 先只放常量：

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADVICE_ROOT = REPO_ROOT / "advice"
ADVICE_REPO_URL = "https://github.com/xiekch/finance_monitor"
ADVICE_REPO_REF = "main"
MAX_ADVICE = 3
LESSON_LIMIT = 30
MAX_HORIZON_DAYS = 31
MAX_REFERENCE_AGE_DAYS = 3
MAX_REVIEWS_PER_RUN = 20
DISCLAIMER = "模型生成，非投资建议"
```

`models/advice.py` 的校验改为引用这里的 `MAX_HORIZON_DAYS` 和 `MAX_REFERENCE_AGE_DAYS`。

`storage/advice_store.py`：

- `AdviceStore(root=ADVICE_ROOT)` 创建根目录。`save_new` 用 `created_at` 决定 `YYYY-MM` 目录，`id` 取同一天已有 `{date}-N` 的最大 N 加 1，再把渲染结果原子写入。原子写是同目录 `*.tmp` 然后 `Path.replace`。
- `list_due(today)`：`status == open` 且 `expiry_date < today`，按 `expiry_date`、`id` 升序。
- `list_created_between(start, end)` 含两端，按 `created_at`、`id` 升序。
- `previous_week(today)`：本周一往前 7 天到本周一的前一天。
- `previous_month(today)`：上一个自然月的第一天和最后一天。
- `open_summaries(today)`：`status == open` 且 `expiry_date >= today`。每行 `id | symbol name | direction | 到期 YYYY-MM-DD | 目标价 N | 理由第一句 | 最近复盘`。理由第一句按 `。！？` 切。最近复盘取最后一段复盘的 `- 价格：` 和 `- 逻辑：` 两行，去掉前缀，各截到 60 字，用 `；` 连接；没有复盘写「尚无复盘」。
- `open_symbols(today)`：同一筛选条件下的 symbol 集合。
- `append_lesson` / `recent_lessons(30)`：`lessons.md` 以 `## {date} · {symbol} · {id} · {kind}` 分块，读取时只留最后 30 块。
- 读取时扫描根目录下全部 `*.md`，跳过 `lessons.md`。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_advice_store.py tests/test_advice_doc.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add config/investment.py storage/advice_store.py models/advice.py tests/test_advice_store.py
git commit -m "$(cat <<'EOF'
feat: store investment advice as monthly markdown files

EOF
)"
```

---

### Task 3: 追加复盘和文件锁

**Files:**
- Modify: `storage/advice_store.py`
- Test: `tests/test_advice_store.py`

**Step 1: Write the failing test**

在 `tests/test_advice_store.py` 追加：

```python
import pytest

DUE_NOTE = """## 复盘 2026-10-26 到期结案
- 价格：建议时 140 美元，目标价 160 美元，结案时 151 美元。窗口内未碰到目标价。来源 https://example.com/close
- 逻辑：需求仍在。
- 事件过程：10 月下旬订单评论偏多。
- 经验：目标价没碰到就不把叙事写成已兑现。
"""


def test_due_review_appends_and_closes_without_rewriting_thesis(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    updated = store.append_review(saved.id, DUE_NOTE, kind="due")
    assert updated.status == "closed"
    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    assert text.index("## 理由") < text.index("## 复盘 2026-10-26 到期结案")
    assert "需求还在。" in text
    assert "目标价没碰到" in store.recent_lessons(30)[0]


def test_due_no_new_finding_raises_and_stays_open(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    with pytest.raises(ValueError):
        store.append_review(saved.id, "NO_NEW_FINDING", kind="due")
    assert store.load(saved.id).status == "open"


def test_weekly_no_new_finding_does_not_write(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 19)
    path = tmp_path / "2026-10" / f"{saved.id}.md"
    before = path.read_text(encoding="utf-8")
    assert store.append_review(saved.id, "NO_NEW_FINDING", kind="weekly") is None
    assert path.read_text(encoding="utf-8") == before


def test_second_review_sees_first(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    saved = _save(store, advice_md, 25, expiry=date(2026, 10, 25))
    store.append_review(saved.id, DUE_NOTE.replace("- 经验：目标价没碰到就不把叙事写成已兑现。", "- 经验：无"), kind="due")
    again = store.load(saved.id)
    assert any("结案时 151" in review for review in again.reviews)
    assert store.recent_lessons(30) == []
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_advice_store.py -v`

Expected: FAIL with `AttributeError: 'AdviceStore' object has no attribute 'append_review'`

**Step 3: Write minimal implementation**

- 锁放在模块级：`_LOCKS: dict[Path, threading.Lock]`，键是 `path.resolve()`，取锁本身再用一把模块级锁保护。每个 `ReviewStep` 会各自新建 `AdviceStore`，锁挂在实例上会互不相见。`lessons.md` 用同一套锁。
- `append_review(advice_id, note, kind)` 在锁内重新 `load`。
- `kind` 为 `weekly` 或 `monthly` 且去掉空白后等于 `NO_NEW_FINDING`：返回 `None`。
- `kind == "due"` 且内容是 `NO_NEW_FINDING`：抛 `ValueError`，不写文件。
- 其他内容必须含 `## 复盘`、`- 价格：`、`- 逻辑：`、`- 事件过程：`、`- 经验：`。否则抛 `ValueError`。
- 到期复盘把文首 `status` 改成 `closed`，再把复盘节追加到末尾，原子写回。
- `- 经验：` 的正文去掉空白后不是「无」时，调用 `append_lesson`。
- `load(advice_id)` 按 `id` 前 7 位定位月份目录。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_advice_store.py tests/test_advice_doc.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add storage/advice_store.py tests/test_advice_store.py
git commit -m "$(cat <<'EOF'
feat: append investment reviews without rewriting the thesis

EOF
)"
```

---

### Task 3b: 只提交 advice/ 并推送

**Files:**
- Create: `storage/advice_git.py`
- Test: `tests/test_advice_git.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_advice_git.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'storage.advice_git'`

**Step 3: Write minimal implementation**

`AdviceCommitter(repo_root=REPO_ROOT, advice_root=ADVICE_ROOT)`，没有关闭推送的参数：

- `commit(message) -> bool`：开头清空 `last_error`。`git add -- <advice 相对路径>`；用 `git diff --cached --quiet -- <path>` 判断有没有改动，没有就返回 `False`，也不推送；有则 `git commit -m message -- <path>`。
- 提交成功后一定 `git push origin HEAD`；失败先 `git pull --rebase --autostash` 再推一次；仍失败把 `last_error` 设为「推送失败：…」并记日志，不抛异常。提交本身成功就返回 `True`。
- `git add` / `git commit` 失败时把 `last_error` 设为「提交失败：…」，返回 `False`，不抛异常。
- 所有 git 调用用 `subprocess.run([...], cwd=repo_root, capture_output=True, text=True, timeout=60)`，不经过 shell。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_advice_git.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add storage/advice_git.py tests/test_advice_git.py
git commit -m "$(cat <<'EOF'
feat: commit only advice files after each run

EOF
)"
```

---

### Task 4: 模型输出解析和提示词

**Files:**
- Create: `steps/investment_parse.py`
- Modify: `config/investment.py`
- Test: `tests/test_investment_parse.py`

**Step 1: Write the failing test**

```python
from datetime import date

from models.advice import parse_advice_markdown
from steps.investment_parse import (
    build_advice_prompt,
    build_review_prompt,
    parse_advice_response,
    parse_review_response,
)


def _block(symbol, expiry="2026-11-09", target=160):
    return f"""<<<ADVICE>>>
symbol: {symbol}
name: 测试
direction: 看多
expiry_date: {expiry}
currency: USD
reference_price: 140
reference_date: 2026-10-26
reference_url: https://example.com/{symbol}
target_price: {target}
stop_price: 120
## 理由
需求还在。
## 目标价
160 附近。
## 失效条件
跌破 120。
## 参考价
140 收盘。
## 观察条件
财报。
<<<END>>>"""


def test_parse_drops_invalid_and_already_open():
    raw = "\n".join([_block("NVDA"), _block("BAD", expiry="2027-01-01"), _block("AAPL")])
    valid, dropped = parse_advice_response(raw, today=date(2026, 10, 26), open_symbols={"AAPL"})
    assert [d.symbol for d in valid] == ["NVDA"]
    assert valid[0].created_at == date(2026, 10, 26)
    assert dropped == 2


def test_parse_drops_duplicate_in_batch_and_caps_at_three():
    raw = "\n".join([_block("NVDA"), _block("NVDA"), _block("A"), _block("B"), _block("C")])
    valid, dropped = parse_advice_response(raw, today=date(2026, 10, 26), open_symbols=set())
    assert [d.symbol for d in valid] == ["NVDA", "A", "B"]
    assert dropped == 2


def test_review_sentinel_and_note():
    assert parse_review_response("NO_NEW_FINDING", kind="weekly") is None
    note = parse_review_response("""## 复盘 2026-10-26 周回溯
- 价格：未碰到目标价。
- 逻辑：催化剂未落地。
- 事件过程：本周没有新订单。
- 经验：无
""", kind="weekly")
    assert "周回溯" in note


def test_advice_prompt_includes_history_only():
    prompt = build_advice_prompt(
        today=date(2026, 10, 26),
        open_summaries=["2026-10-20-1 | NVDA 英伟达 | 看多 | 到期 2026-11-09 | 目标价 160 | 需求还在。 | 尚无复盘"],
        lessons=["## 2026-10-25 · NVDA · 2026-10-01-1 · 到期结案\n别把叙事写成已兑现。"],
    )
    assert "2026-10-20-1" in prompt
    assert "别把叙事写成已兑现" in prompt
    assert "不使用已抓取的行情" in prompt
    assert "不要再发新建议" in prompt
    assert "advice/lessons.md" in prompt
    assert "只读" in prompt


def test_review_prompt_window_stops_at_expiry(advice_md):
    doc = parse_advice_markdown(advice_md(19, expiry=date(2026, 10, 25)))
    doc.id = "2026-10-19-1"
    prompt = build_review_prompt(doc, kind="monthly", today=date(2026, 11, 1))
    assert "2026-10-19 至 2026-10-25" in prompt
    assert "NO_NEW_FINDING" in prompt
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_investment_parse.py -v`

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

`config/investment.py` 增加建议和复盘的提示词模板。

建议提示词要点：

- 自己联网搜索，不使用已抓取的行情、调用方提供的行情表或社媒帖子
- 最多 3 条；每条用 `<<<ADVICE>>>` 与 `<<<END>>>` 包裹
- 块内先写 `symbol`、`name`、`direction`、`expiry_date`、`currency`、`reference_price`、`reference_date`、`reference_url`、`target_price`、可选 `stop_price`，价格写纯数字；再写五节正文
- 参考价必须是 `reference_date` 当天或前 3 天内的真实成交价，`reference_url` 是能打开的来源
- 到期日是具体日期，不超过今天加 31 天
- 附上未到期摘要，并写明「下面这些标的已有未到期建议，不要再发新建议」
- 附上最近经验
- 说明仓库里的 `advice/` 目录结构和文件格式；要求先读 `advice/lessons.md` 全文，对准备给建议的标的先搜索它在 `advice/` 里的历史建议和复盘
- 要求只读：不修改、不新建、不提交仓库里的任何文件，结果只写在回复里

复盘提示词由 `build_review_prompt(doc, kind, today)` 生成：

- 附建议全文和已有复盘
- 说明可以只读参考 `advice/` 里同一标的的其他建议
- 写明价格评估窗口 `{created_at} 至 {min(today, expiry_date)}`；到期之后的走势只能在事件过程里提一句，不用来判断对错或写经验
- 观望：写窗口内是否触及目标价，不按涨跌判断方向对错
- `kind=due` 时禁止返回 `NO_NEW_FINDING`，必须写到期结案；`weekly` / `monthly` 说明什么算新发现，没有时只返回 `NO_NEW_FINDING`

`parse_advice_response(raw, today, open_symbols)` 把每块转成 `AdviceDoc`（`created_at = today`，`status = open`），按出现顺序调用 `validate_advice(doc, open_symbols=已开 + 本批已收)`。合法的留下，非法的计入 `dropped`。合法数达到 `MAX_ADVICE` 后，其余都算 dropped。

`parse_review_response`：周/月的 `NO_NEW_FINDING` 返回 `None`；到期档收到它时抛 `ValueError`；其余检查四个必填行。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_investment_parse.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add config/investment.py steps/investment_parse.py tests/test_investment_parse.py
git commit -m "$(cat <<'EOF'
feat: parse searched investment advice and review notes

EOF
)"
```

---

### Task 5: Cursor complete 和投资专用客户端

**Files:**
- Modify: `clients/llm_client/cursor.py`
- Modify: `clients/llm_client/factory.py`
- Modify: `clients/llm_client/__init__.py`
- Test: `tests/test_investment_llm.py`

**Step 1: Write the failing test**

```python
import asyncio

import pytest

from clients.llm_client.cursor import CursorLLMClient
from clients.llm_client.factory import build_investment_llm_client
from config.social import SOCIAL_CONFIG


def test_cursor_complete_sends_prompt_without_briefing_template(monkeypatch):
    client = CursorLLMClient(api_key="k", model="grok-4.7", prompt_template="UNUSED {posts_block}")
    seen = {}

    def fake_create_and_wait(prompt: str):
        seen["prompt"] = prompt
        return "agent", {"id": "run", "result": " NO_NEW_FINDING \n"}

    monkeypatch.setattr(client, "_create_and_wait", fake_create_and_wait)
    monkeypatch.setattr(client, "_fetch_usage", lambda agent_id, run_id: (0, 0))
    assert asyncio.run(client.complete("请搜索 NVDA 现价")) == "NO_NEW_FINDING"
    assert seen["prompt"] == "请搜索 NVDA 现价"


def test_create_agent_sends_repos_only_when_configured(monkeypatch):
    bodies = []

    def fake_get_json(url, method="GET", **kwargs):
        bodies.append(kwargs.get("json"))
        return {"agent": {"id": "a"}, "run": {"id": "r", "status": "FINISHED"}}

    plain = CursorLLMClient(api_key="k", model="m", prompt_template="")
    monkeypatch.setattr(plain, "_get_json", fake_get_json)
    plain._create_agent("p")
    repo = {"url": "https://github.com/xiekch/finance_monitor", "startingRef": "main"}
    mounted = CursorLLMClient(api_key="k", model="m", prompt_template="", repos=[repo])
    monkeypatch.setattr(mounted, "_get_json", fake_get_json)
    mounted._create_agent("p")
    assert "repos" not in bodies[0]
    assert bodies[1]["repos"] == [repo]


def test_investment_client_requires_cursor_and_mounts_repo(monkeypatch):
    monkeypatch.setitem(SOCIAL_CONFIG, "llm_provider", {
        "name": "cursor", "api_key": "k", "base_url": "https://api.cursor.com",
        "model": "grok-4.7", "timeout_sec": 900,
    })
    client = build_investment_llm_client()
    assert isinstance(client, CursorLLMClient)
    assert client.repos == [{"url": "https://github.com/xiekch/finance_monitor", "startingRef": "main"}]
    monkeypatch.setitem(SOCIAL_CONFIG, "llm_provider", {"name": "tongyi"})
    with pytest.raises(RuntimeError, match="搜索"):
        build_investment_llm_client()
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_investment_llm.py -v`

Expected: FAIL with `ImportError` for `build_investment_llm_client`

**Step 3: Write minimal implementation**

- `CursorLLMClient.__init__` 增加 `repos: Optional[list[dict]] = None`。`_create_agent` 只在 `repos` 非空时往请求体里加 `"repos"`，现有 `test_cursor_llm.py` 的 `"repos" not in kwargs["json"]` 仍成立。
- `CursorLLMClient.complete(prompt)`：未配置 `api_key` 时抛 `RuntimeError`；复用 `_create_and_wait` 和 `_fetch_usage`，日志格式与 `summarize` 一致，返回去掉首尾空白的 `run["result"]`。
- `build_investment_llm_client()`：读 `SOCIAL_CONFIG["llm_provider"]`，`name` 不是 `cursor` 时抛 `RuntimeError("投资建议需要能联网搜索的后端，当前只支持 cursor")`；否则 `client_from_config(cfg, "")`，模板传空字符串，因为 `complete` 不格式化它；再把 `client.repos` 设为 `[{"url": ADVICE_REPO_URL, "startingRef": ADVICE_REPO_REF}]`。
- 不改 `TongyiLLMClient`。
- 在 `clients/llm_client/__init__.py` 导出 `build_investment_llm_client`。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_investment_llm.py tests/test_cursor_llm.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add clients/llm_client/cursor.py clients/llm_client/factory.py clients/llm_client/__init__.py tests/test_investment_llm.py
git commit -m "$(cat <<'EOF'
feat: let investment tasks send a raw research prompt to Cursor

EOF
)"
```

---

### Task 6: 建议任务和复盘任务

**Files:**
- Create: `steps/investment_advice.py`
- Create: `steps/investment_review.py`
- Create: `steps/notify/investment.py`
- Test: `tests/test_investment_steps.py`

**Step 1: Write the failing test**

```python
import asyncio
from datetime import date
from pathlib import Path

from config.investment import DISCLAIMER
from models.advice import parse_advice_markdown
from steps.investment_advice import AdviceStep
from steps.investment_review import ReviewStep
from steps.notify.investment import InvestmentNotifyStep
from storage.advice_store import AdviceStore


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_markdown(self, content: str) -> bool:
        self.sent.append(content)
        return True


class FakeCommitter:
    def __init__(self, ok=True, error=None):
        self.messages = []
        self.ok = ok
        self.last_error = None
        self._error = error

    def commit(self, message: str) -> bool:
        self.messages.append(message)
        self.last_error = self._error
        return self.ok


def _run(step, notifier):
    items = asyncio.run(step.process([]))
    asyncio.run(InvestmentNotifyStep(notifier=notifier).process(items))


ADVICE = """<<<ADVICE>>>
symbol: NVDA
name: 英伟达
direction: 看多
expiry_date: 2026-11-09
currency: USD
reference_price: 140
reference_date: 2026-10-26
reference_url: https://example.com/nvda
target_price: 160
## 理由
需求还在。
## 目标价
160 附近。
## 失效条件
跌破 120。
## 参考价
140 收盘。
## 观察条件
财报。
<<<END>>>"""

DUE = """## 复盘 2026-10-28 到期结案
- 价格：建议时 140，目标价 160，结案时 151。未碰到目标价。来源 https://example.com/close
- 逻辑：需求仍在。
- 事件过程：订单评论偏多。
- 经验：没碰到目标价就不要写成已兑现。
"""

WEEKLY = """## 复盘 2026-10-26 周回溯
- 价格：碰到失效价。
- 逻辑：催化剂落空。
- 事件过程：订单下修。
- 经验：无
"""


def test_advice_step_saves_commits_and_pushes(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert (tmp_path / "2026-10" / "2026-10-26-1.md").is_file()
    assert committer.messages == ["advice: 2026-10-26 新增 1 条"]
    assert len(notifier.sent) == 1
    assert "NVDA" in notifier.sent[0]
    assert notifier.sent[0].rstrip().endswith(DISCLAIMER)


def test_advice_failure_pushes_error_and_writes_nothing(tmp_path: Path):
    class Boom:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("down")

    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = AdviceStep(store_root=tmp_path, llm=Boom(), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert list(tmp_path.rglob("*.md")) == []
    assert committer.messages == []
    assert notifier.sent and "失败" in notifier.sent[0]


def test_commit_failure_still_pushes_with_note(tmp_path: Path):
    notifier = FakeNotifier()
    committer = FakeCommitter(ok=True, error="推送失败：rejected")
    step = AdviceStep(store_root=tmp_path, llm=FakeLLM([ADVICE]), committer=committer,
                      today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert "NVDA" in notifier.sent[0]
    assert "推送失败" in notifier.sent[-1]


def test_weekly_silent_on_no_new_finding(tmp_path: Path, advice_md):
    AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(19)))
    notifier = FakeNotifier()
    committer = FakeCommitter()
    step = ReviewStep(kind="weekly", store_root=tmp_path, llm=FakeLLM(["NO_NEW_FINDING"]),
                      committer=committer, today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert notifier.sent == []
    assert committer.messages == []


def test_due_uses_today_at_run_time_and_closes(tmp_path: Path, advice_md):
    saved = AdviceStore(tmp_path).save_new(parse_advice_markdown(advice_md(25, expiry=date(2026, 10, 27))))
    days = [date(2026, 10, 26)]
    llm = FakeLLM([DUE])
    committer = FakeCommitter()
    step = ReviewStep(kind="due", store_root=tmp_path, llm=llm, committer=committer,
                      today_fn=lambda: days[0])
    notifier = FakeNotifier()
    _run(step, notifier)
    assert llm.prompts == [] and notifier.sent == [] and committer.messages == []
    days[0] = date(2026, 10, 28)
    _run(step, notifier)
    text = (tmp_path / "2026-10" / f"{saved.id}.md").read_text(encoding="utf-8")
    assert "status: closed" in text
    assert committer.messages == ["advice: 2026-10-28 到期结案 1 份"]
    assert len(notifier.sent) == 1


def test_review_cap_skips_extra_files(tmp_path: Path, advice_md):
    store = AdviceStore(tmp_path)
    store.save_new(parse_advice_markdown(advice_md(19)))
    store.save_new(parse_advice_markdown(advice_md(20, symbol="AAPL")))
    llm = FakeLLM([WEEKLY])
    notifier = FakeNotifier()
    step = ReviewStep(kind="weekly", store_root=tmp_path, llm=llm, committer=FakeCommitter(),
                      max_per_run=1, today_fn=lambda: date(2026, 10, 26))
    _run(step, notifier)
    assert len(llm.prompts) == 1
    assert "跳过 1 份" in notifier.sent[-1]
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_investment_steps.py -v`

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

- 两个 step 的构造参数：`store_root=ADVICE_ROOT`、`llm=None`（为 `None` 时调用 `build_investment_llm_client()`）、`committer=None`（为 `None` 时用 `AdviceCommitter()`）、`today_fn=date.today`。`ReviewStep` 另有 `kind` 和 `max_per_run=MAX_REVIEWS_PER_RUN`。构造函数里不算日期，`process()` 开头调用一次 `today_fn()`。
- 写了文件才调用一次 `committer.commit(message)`，放在返回消息之前。提交信息：建议 `advice: {today} 新增 N 条`；复盘 `advice: {today} 到期结案 N 份` / `周回溯 N 份` / `月回溯 N 份`，N 是本次实际追加的份数。`commit` 之后 `committer.last_error` 非空时，在最后一条消息末尾附上它。
- `AdviceStep.process`：读 `open_summaries`、`open_symbols`、`recent_lessons(LESSON_LIMIT)`，调用 `complete`，用 `parse_advice_response` 解析并 `save_new`。每条保存成功的建议返回一个 `InvestmentMessage`。零条合法时只返回一条失败说明。部分丢弃时，最后一条消息末尾写「丢弃 N 条」。模型异常同样返回失败说明，不写文件。
- `ReviewStep.process`：按 `kind` 取档期（`due` 用 `list_due`，`weekly` / `monthly` 用 `list_created_between` 配合 `previous_week` / `previous_month`），排序后取前 `max_per_run` 份。每份单独 `build_review_prompt`、`complete`、`parse_review_response`、`append_review`。`append_review` 返回 `None` 时不推送。单条异常记入失败数，继续下一份。每段写下的复盘返回一个 `InvestmentMessage`。有失败或有跳过时，在最后一条消息末尾写「失败 N 条」「跳过 N 份」；本次没有任何复盘但有失败或跳过时，单独返回一条说明。全部为空时返回空列表。
- `InvestmentNotifyStep(BaseNotifyStep)`：对空列表直接返回。否则对每个 `InvestmentMessage` 调用 `send_markdown(markdown + "\n\n" + DISCLAIMER)`。返回空列表。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_investment_steps.py tests/test_advice_store.py tests/test_advice_git.py tests/test_investment_parse.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add steps/investment_advice.py steps/investment_review.py steps/notify/investment.py tests/test_investment_steps.py
git commit -m "$(cat <<'EOF'
feat: generate investment advice and append later reviews

EOF
)"
```

---

### Task 7: 注册四条任务

**Files:**
- Modify: `config/schedule.py`
- Modify: `tasks.py`
- Modify: `steps/notify/__init__.py`
- Test: `tests/test_investment_tasks.py`

**Step 1: Write the failing test**

```python
from tasks import TASK_GROUPS, TASK_REGISTRY, expand_task_keys
from config.schedule import TASK_SCHEDULE


def test_investment_group_is_separate():
    keys = expand_task_keys(["investment"])
    assert keys == [
        "investment_review_due",
        "investment_advice",
        "investment_review_weekly",
        "investment_review_monthly",
    ]
    for key in keys:
        assert key in TASK_REGISTRY
        assert key not in TASK_GROUPS["briefings"]
        assert key not in TASK_GROUPS["morning_pack"]


def test_investment_crons():
    assert TASK_SCHEDULE["investment_review_due"]["kwargs"] == {"hour": 8, "minute": 20}
    assert TASK_SCHEDULE["investment_advice"]["kwargs"] == {"hour": 9, "minute": 0}
    assert TASK_SCHEDULE["investment_review_weekly"]["kwargs"] == {
        "day_of_week": "mon", "hour": 21, "minute": 0,
    }
    assert TASK_SCHEDULE["investment_review_monthly"]["kwargs"] == {
        "day": 1, "hour": 21, "minute": 10,
    }
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_investment_tasks.py -v`

Expected: FAIL with `KeyError: 'investment'`

**Step 3: Write minimal implementation**

在 `TASK_SCHEDULE` 写入上面四个 cron。在 `TASK_REGISTRY` 注册：

- `investment_review_due`: `ReviewStep(kind="due") | InvestmentNotifyStep()`
- `investment_advice`: `AdviceStep() | InvestmentNotifyStep()`
- `investment_review_weekly`: `ReviewStep(kind="weekly") | InvestmentNotifyStep()`
- `investment_review_monthly`: `ReviewStep(kind="monthly") | InvestmentNotifyStep()`

注册表里的值必须保持 `lambda: ...`，step 只在 `build_tasks` 选中该 key 时才构造，provider 不是 cursor 时其他任务不受影响。

`TASK_GROUPS["investment"]` 的顺序与测试一致。不要修改 `briefings` 和 `morning_pack`。

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_investment_tasks.py tests/test_investment_steps.py tests/test_advice_doc.py tests/test_advice_store.py tests/test_advice_git.py tests/test_investment_parse.py tests/test_investment_llm.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add config/schedule.py tasks.py steps/notify/__init__.py tests/test_investment_tasks.py
git commit -m "$(cat <<'EOF'
feat: schedule daily investment advice and three review passes

EOF
)"
```

---

## 执行说明

实现时先读 `docs/plans/2026-10-26-investment-advice-design.md`，并先完成 Task 0。单测一律用临时目录、假的 `complete`、`FakeCommitter` 和注入的 `today_fn`，不要调用 Cursor API，不要读写仓库里真实的 `advice/`，也不要在真实仓库里 commit；git 相关测试只在 `tmp_path` 下新建的仓库里跑。

本次撰写设计与计划时不提交 git。上面每个 Task 的 Commit 步骤留给正式实现；如果实现时仍要求不提交，跳过这些步骤。

计划完成后用下面的命令做一次总验收：

```bash
.venv/bin/python3 -m pytest tests/ -v
```

Expected: 全部 PASS，包括原有测试
