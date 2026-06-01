"""查看 SQLite 里抓到的推文和生成的简报。

用法：
    .venv/bin/python scripts/show_posts.py                     # 两张表各看 10 条
    .venv/bin/python scripts/show_posts.py posts --limit 50
    .venv/bin/python scripts/show_posts.py posts --author elonmusk
    .venv/bin/python scripts/show_posts.py briefings
    .venv/bin/python scripts/show_posts.py briefings --id 2    # 看某条简报的完整 markdown
"""
import argparse
import sqlite3
import sys
import textwrap
from pathlib import Path

# 项目根目录加入 sys.path，复用 config.settings.DATABASE_CONFIG
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config.settings import DATABASE_CONFIG  # noqa: E402

DB_PATH = ROOT / DATABASE_CONFIG["path"]


def _conn():
    return sqlite3.connect(DB_PATH)


def show_posts(limit: int, author: str | None) -> None:
    sql = (
        "SELECT created_at, author, post_id, text, url "
        "FROM social_posts "
    )
    params: tuple = ()
    if author:
        sql += "WHERE author = ? "
        params = (author,)
    sql += "ORDER BY created_at DESC LIMIT ?"
    params = (*params, limit)

    rows = _conn().execute(sql, params).fetchall()
    print(f"=== social_posts (latest {len(rows)}{f', author=@{author}' if author else ''}) ===")
    for created_at, author_, post_id, text, url in rows:
        wrapped = textwrap.fill(text.replace("\n", " "), width=80, subsequent_indent="    ")
        print(f"\n[{created_at}] @{author_}  id={post_id}")
        print(f"  {wrapped}")
        print(f"  → {url}")


def show_briefings(limit: int, briefing_id: int | None) -> None:
    if briefing_id is not None:
        row = _conn().execute(
            "SELECT id, created_at, window_hours, degraded, error, markdown, source_post_ids "
            "FROM briefings WHERE id = ?",
            (briefing_id,),
        ).fetchone()
        if not row:
            print(f"briefing id={briefing_id} not found")
            return
        bid, created_at, window_hours, degraded, error, markdown, source_post_ids = row
        print(f"=== briefing id={bid} ===")
        print(f"created_at      : {created_at}")
        print(f"window_hours    : {window_hours}")
        print(f"degraded        : {bool(degraded)}{f'  (error: {error})' if error else ''}")
        print(f"source_post_ids : {source_post_ids}")
        print(f"--- markdown ({len(markdown)} chars) ---")
        print(markdown)
        return

    rows = _conn().execute(
        "SELECT id, created_at, degraded, length(markdown) AS md_len, "
        "length(source_post_ids) - length(replace(source_post_ids, ',', '')) + 1 AS posts_n "
        "FROM briefings ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    print(f"=== briefings (latest {len(rows)}) ===")
    print(f"{'id':>4} {'created_at':25s} {'degraded':9s} {'md_chars':>8s} {'posts':>5s}")
    for bid, created_at, degraded, md_len, posts_n in rows:
        print(f"{bid:>4} {created_at:25s} {str(bool(degraded)):9s} {md_len:>8d} {posts_n:>5d}")
    print(f"\n用 --id N 看某条完整 markdown")


def main():
    parser = argparse.ArgumentParser(
        description="查看 social_posts / briefings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    p_posts = sub.add_parser("posts", help="列出抓到的推文")
    p_posts.add_argument("--limit", type=int, default=10)
    p_posts.add_argument("--author", help="按 author 过滤（不带 @）")

    p_brief = sub.add_parser("briefings", help="列出已生成的简报")
    p_brief.add_argument("--limit", type=int, default=10)
    p_brief.add_argument("--id", type=int, help="看某条简报的完整 markdown")

    args = parser.parse_args()

    if args.cmd == "posts":
        show_posts(args.limit, args.author)
    elif args.cmd == "briefings":
        show_briefings(args.limit, args.id)
    else:
        show_posts(limit=10, author=None)
        print()
        show_briefings(limit=10, briefing_id=None)


if __name__ == "__main__":
    main()
