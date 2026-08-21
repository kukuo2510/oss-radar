"""Manually record like/skip feedback on an item, standing in for the app's swipe UI
until that exists. This is what src/recommend.py's personalization is built on.

Usage:
    python interact.py --like github:owner/repo --like arxiv:2608.20338v1
    python interact.py --skip huggingface_models:some-org/some-model
"""

import argparse

from db import init_db, record_interaction


def parse_key(key: str) -> tuple[str, str]:
    if ":" not in key:
        raise ValueError(f"expected 'source:source_id', got {key!r}")
    source, source_id = key.split(":", 1)
    return source, source_id


def main() -> None:
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
