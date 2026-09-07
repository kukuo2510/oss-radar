"""手動記錄對某個項目的按讚/略過（like/skip）回饋，在 App 的滑動介面（swipe UI）
還沒做出來之前，先用命令列的方式頂替。src/recommend.py 的個人化推薦邏輯，
就是建立在這裡記錄下來的互動資料之上。

用法：
    python interact.py --like github:owner/repo --like arxiv:2608.20338v1
    python interact.py --skip huggingface_models:some-org/some-model
"""

import argparse

from db import init_db, record_interaction


def parse_key(key: str) -> tuple[str, str]:
    """把命令列參數裡的 "source:source_id" 字串拆成 (source, source_id) 這組識別碼。"""
    if ":" not in key:
        raise ValueError(f"expected 'source:source_id', got {key!r}")
    source, source_id = key.split(":", 1)
    return source, source_id


def main() -> None:
    """解析命令列參數，把所有 --like / --skip 指定的項目依序寫入互動紀錄。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--like", action="append", default=[], metavar="source:source_id")
    parser.add_argument("--skip", action="append", default=[], metavar="source:source_id")
    args = parser.parse_args()

    if not args.like and not args.skip:
        parser.error("pass at least one --like or --skip")

    init_db()
    for key in args.like:
        source, source_id = parse_key(key)
        record_interaction(source, source_id, "like")
        print(f"Liked  {source}:{source_id}")
    for key in args.skip:
        source, source_id = parse_key(key)
        record_interaction(source, source_id, "skip")
        print(f"Skipped {source}:{source_id}")


if __name__ == "__main__":
    main()
