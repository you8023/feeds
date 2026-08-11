#!/usr/bin/env python3
"""Fix misaligned feed files caused by feed-me-up-scotty's index bug.

Upstream bug (feed-me-up-scotty <= 1.10.0, src/run.ts):

    const feedsData: FeedData[] = ... // failed feeds are FILTERED OUT here
    const individualFeedPromises = feedsData.map((feedData, i) =>
      generateFeed(feedConfigs[i].id, feedData)  // index i is from the FILTERED array
    );

`feedsData` is filtered (feeds with onFail = "exclude"/"stale" that yielded no
data are dropped), but the file name is taken from `feedConfigs[i].id`, the
*unfiltered* config array. As soon as any feed fails, every feed after it is
written under the wrong id (its data is shifted to an earlier id's file name).

This script repairs the damage: each generated `public/<id>.json` contains the
`url` it was actually crawled from; we look up which feed id that url belongs
to in feeds.toml (urls are unique) and rename the file pair to the correct id.
"""

import json
import os
import shutil
import sys

import tomllib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # .github/scripts -> repo root
CONFIG_PATH = os.path.join(ROOT, "feeds.toml")
PUBLIC_DIR = os.path.join(ROOT, "public")


def load_url_to_id() -> dict:
    with open(CONFIG_PATH, "rb") as f:
        toml = tomllib.load(f)

    url_to_id: dict[str, str] = {}
    for sid, cfg in toml.items():
        if sid == "default":
            continue
        url = cfg.get("url")
        urls = url if isinstance(url, list) else [url]
        for u in urls:
            if u in url_to_id and url_to_id[u] != sid:
                print(
                    f"WARNING: url {u} is configured for both "
                    f"'{url_to_id[u]}' and '{sid}'; repair may be wrong",
                    file=sys.stderr,
                )
            url_to_id[u] = sid
    return url_to_id


def main() -> int:
    if not os.path.isdir(PUBLIC_DIR):
        print("No public/ directory; nothing to do.")
        return 0

    url_to_id = load_url_to_id()
    with open(CONFIG_PATH, "rb") as f:
        toml = tomllib.load(f)

    # Collect files whose data url does not match their file-name id.
    mismatches = []  # (current_id, data_url, correct_id)
    for name in sorted(os.listdir(PUBLIC_DIR)):
        if not name.endswith(".json"):
            continue
        fid = name[: -len(".json")]
        try:
            with open(os.path.join(PUBLIC_DIR, name)) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        data_url = data.get("url")
        if not isinstance(data_url, str):
            continue
        configured = toml.get(fid, {}).get("url")
        configured_urls = configured if isinstance(configured, list) else [configured]
        if data_url in configured_urls:
            continue  # aligned
        correct_id = url_to_id.get(data_url)
        if correct_id is None or correct_id == fid:
            continue
        mismatches.append((fid, data_url, correct_id))

    if not mismatches:
        print("All feeds aligned; nothing to repair.")
        return 0

    # Move mismatched files aside first, then place them under the correct id.
    # (Renaming in place could collide when files are chained: A holds B's
    # data while B holds C's data, etc.)
    tmp_dir = os.path.join(PUBLIC_DIR, ".repairing")
    os.makedirs(tmp_dir, exist_ok=True)
    staged = []
    for fid, data_url, correct_id in mismatches:
        for ext in ("xml", "json"):
            src = os.path.join(PUBLIC_DIR, f"{fid}.{ext}")
            if os.path.isfile(src):
                shutil.move(src, os.path.join(tmp_dir, f"{fid}.{ext}"))
        staged.append((fid, correct_id))

    placed = 0
    removed = 0
    for fid, correct_id in staged:
        for ext in ("xml", "json"):
            src = os.path.join(tmp_dir, f"{fid}.{ext}")
            if not os.path.isfile(src):
                continue
            dst = os.path.join(PUBLIC_DIR, f"{correct_id}.{ext}")
            if os.path.exists(dst):
                os.remove(dst)  # conflicting (should not happen); prefer correct one
                removed += 1
            shutil.move(src, dst)
            placed += 1
        print(f"Fixed: {fid}.xml/.json -> {correct_id}")

    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(
        f"Repaired {len(staged)} misaligned feed(s): "
        f"{placed} file(s) renamed, {removed} conflicting file(s) removed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
