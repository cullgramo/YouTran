"""ytt — download YouTube transcripts into a Markdown library."""

from __future__ import annotations

import argparse
import sys
import time

from . import core


def _split_langs(args) -> None:
    """`-l` takes several values, so `ytt get -l de URL` puts the URL into args.lang.
    Move anything that parses as a video back into args.videos (language codes never do)."""
    langs = []
    for value in args.lang:
        if core.playlist_id(value, include_watch=True):
            args.videos.append(value)
            continue
        try:
            core.parse_video_id(value)
            args.videos.append(value)
        except core.TranscriptError:
            langs.append(value)
    args.lang = langs or ["en"]


def _read_inputs(args) -> list[str]:
    _split_langs(args)
    videos = list(args.videos)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            videos += [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not videos and not sys.stdin.isatty():
        videos += [ln.strip() for ln in sys.stdin if ln.strip()]
    return videos


def _expand_playlists(videos: list[str], args) -> tuple[list[str], int]:
    """Replace playlist links with their videos. Returns (videos, number of playlists that failed)."""
    out, failures = [], 0
    for value in videos:
        if not core.playlist_id(value, include_watch=args.playlist):
            out.append(value)
            continue
        try:
            title, ids = core.playlist_videos(value, args.proxy)
            if args.limit and len(ids) > args.limit:
                print(f"list  {title}: {len(ids)} videos (taking the first {args.limit})", file=sys.stderr)
                ids = ids[: args.limit]
            else:
                print(f"list  {title}: {len(ids)} videos", file=sys.stderr)
            out += ids
        except core.TranscriptError as e:
            failures += 1
            print(f"FAIL  {value}: {e}", file=sys.stderr)
    return list(dict.fromkeys(out)), failures


def cmd_get(args) -> int:
    directory = core.library_dir(args.dir)
    videos, failures = _expand_playlists(_read_inputs(args), args)
    if not videos:
        if not failures:
            print("Give at least one video or playlist URL (or -f FILE).", file=sys.stderr)
        return 1 if failures else 2
    counts = {"saved": 0, "skipped": 0}
    for i, video in enumerate(videos):
        try:
            if not args.force:
                existing = core.find(directory, video)
                if existing and args.stdout:
                    print(existing.read_text(encoding="utf-8"))  # print the saved copy
                    continue
                if existing:
                    counts["skipped"] += 1
                    print(f"skip  {existing}  (already saved; --force to re-fetch)", flush=True)
                    continue
            t = core.fetch_transcript(video, args.lang, args.proxy, any_language=not args.strict)
            if args.stdout:
                print(core.to_markdown(t, args.paragraph))
            else:
                path = core.save(t, directory, args.paragraph, args.json)
                counts["saved"] += 1
                kind = "auto" if t.auto_generated else "manual"
                print(f"saved {path}  [{t.language_code}, {kind}, {core._ts(t.duration)}]", flush=True)
        except core.TranscriptError as e:
            failures += 1
            print(f"FAIL  {video}: {e}", file=sys.stderr)
        if i < len(videos) - 1:
            time.sleep(args.delay)  # be gentle; YouTube rate-limits bursts
    if len(videos) > 1 and not args.stdout:
        print(f"done  {counts['saved']} saved, {counts['skipped']} already saved, {failures} failed",
              file=sys.stderr)
    return 1 if failures else 0


def cmd_list(args) -> int:
    for m in core.list_saved(core.library_dir(args.dir)):
        print(f"{m.get('video_id')}  {m.get('duration', ''):>8}  {m.get('channel') or '':<24.24}  {m.get('title')}")
    return 0


def cmd_search(args) -> int:
    results = core.search(core.library_dir(args.dir), args.query)
    for r in results:
        print(f"\n# {r['title']}  ({r['path']})")
        for h in r["hits"]:
            print(f"  {h['at']}\n    …{h['snippet']}…")
    if not results:
        print("No matches.")
    return 0


def cmd_show(args) -> int:
    path = core.find(core.library_dir(args.dir), args.video)
    if not path:
        print("Not in library. Fetch it with: ytt get " + args.video, file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    if args.plain:
        body = text.split("## Transcript", 1)[-1]
        text = "\n".join(ln.split(") ", 1)[-1] for ln in body.splitlines() if ln.startswith("["))
    print(text)
    return 0


def cmd_path(args) -> int:
    print(core.library_dir(args.dir))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ytt", description=__doc__)
    p.add_argument("--dir", help="library folder (default: $YTT_DIR or ~/youtube-transcripts)")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="fetch transcripts for one or more videos")
    g.add_argument("videos", nargs="*", help="YouTube video or playlist URLs, or 11-character video IDs")
    g.add_argument("-p", "--playlist", action="store_true",
                   help="for watch?v=...&list=... links, fetch the whole playlist instead of just that video")
    g.add_argument("--limit", type=int, help="fetch at most N videos from each playlist")
    g.add_argument("-f", "--file", help="text file with one URL/ID per line (# comments ok)")
    g.add_argument("-l", "--lang", nargs="+", default=["en"], help="preferred language codes, in order (default: en)")
    g.add_argument("--strict", action="store_true", help="fail instead of falling back to another language")
    g.add_argument("--force", action="store_true", help="re-fetch even if already saved")
    g.add_argument("--stdout", action="store_true", help="print Markdown instead of saving")
    g.add_argument("--json", action="store_true", help="also save raw segments to json/<id>.json")
    g.add_argument("--paragraph", type=int, default=60, help="seconds per timestamped paragraph (default: 60)")
    g.add_argument("--proxy", help="HTTP(S) proxy URL (or set $YTT_PROXY); useful if YouTube blocks your IP")
    g.add_argument("--delay", type=float, default=1.0, help="seconds between videos (default: 1)")
    g.set_defaults(func=cmd_get)

    sub.add_parser("list", help="list saved transcripts").set_defaults(func=cmd_list)

    s = sub.add_parser("search", help="search all saved transcripts")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)

    sh = sub.add_parser("show", help="print a saved transcript")
    sh.add_argument("video")
    sh.add_argument("--plain", action="store_true", help="text only, no timestamps or header")
    sh.set_defaults(func=cmd_show)

    sub.add_parser("path", help="print the library folder").set_defaults(func=cmd_path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except core.TranscriptError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
