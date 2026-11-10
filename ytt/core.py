"""Core logic: resolve video IDs, fetch transcripts, store them as Markdown, read them back."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript, NoTranscriptFound
from youtube_transcript_api.proxies import GenericProxyConfig

DEFAULT_DIR = Path.home() / "youtube-transcripts"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class TranscriptError(Exception):
    """A transcript could not be fetched (disabled, missing, blocked, bad URL...)."""


def library_dir(override: str | os.PathLike | None = None) -> Path:
    """Where transcripts live: explicit override > $YTT_DIR > ~/youtube-transcripts."""
    path = Path(override or os.environ.get("YTT_DIR") or DEFAULT_DIR).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_video_id(value: str) -> str:
    """Accept a bare ID or any common YouTube URL form and return the 11-char video ID."""
    value = value.strip()
    if _ID_RE.match(value):
        return value
    url = urlparse(value if "://" in value else "https://" + value)
    host = (url.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = url.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if url.path == "/watch":
            candidate = parse_qs(url.query).get("v", [None])[0]
        else:
            parts = [p for p in url.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v", "e"}:
                candidate = parts[1]
    if candidate and _ID_RE.match(candidate):
        return candidate
    raise TranscriptError(f"Not a recognisable YouTube video URL or ID: {value!r}")


def video_url(video_id: str, seconds: float | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    return f"{url}&t={int(seconds)}s" if seconds else url


def fetch_metadata(video_id: str, session: requests.Session | None = None) -> dict:
    """Title and channel via YouTube's public oEmbed endpoint (no API key). Best effort."""
    try:
        resp = (session or requests).get(
            "https://www.youtube.com/oembed",
            params={"url": video_url(video_id), "format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"title": data.get("title"), "channel": data.get("author_name"),
                "channel_url": data.get("author_url")}
    except Exception:
        return {}


@dataclass
class Transcript:
    video_id: str
    title: str
    channel: str | None
    language: str
    language_code: str
    auto_generated: bool
    segments: list[dict] = field(default_factory=list)  # {"text", "start", "duration"}
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def duration(self) -> float:
        if not self.segments:
            return 0.0
        last = self.segments[-1]
        return last["start"] + last.get("duration", 0)

    @property
    def plain_text(self) -> str:
        return " ".join(s["text"] for s in self.segments)


def _make_api(proxy: str | None) -> YouTubeTranscriptApi:
    proxy = proxy or os.environ.get("YTT_PROXY")
    if proxy:
        return YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=proxy, https_url=proxy))
    return YouTubeTranscriptApi()


def fetch_transcript(video: str, languages: list[str] | None = None, proxy: str | None = None,
                     any_language: bool = True) -> Transcript:
    """Fetch a transcript. Prefers the given languages (manual captions over auto-generated);
    if none match and any_language is true, falls back to whatever transcript exists."""
    video_id = parse_video_id(video)
    languages = languages or ["en"]
    api = _make_api(proxy)
    try:
        available = api.list(video_id)
        try:
            chosen = available.find_transcript(languages)
        except NoTranscriptFound:
            if not any_language:
                raise
            chosen = next(iter(available))
        fetched = chosen.fetch()
    except CouldNotRetrieveTranscript as e:
        # The library's messages are long; the first paragraph is the useful part.
        raise TranscriptError(str(e).strip().split("\n\n")[0] if str(e).strip() else repr(e)) from e
    except StopIteration:
        raise TranscriptError(f"No transcripts available for {video_id}") from None

    meta = fetch_metadata(video_id)
    return Transcript(
        video_id=video_id,
        title=meta.get("title") or video_id,
        channel=meta.get("channel"),
        language=fetched.language,
        language_code=fetched.language_code,
        auto_generated=fetched.is_generated,
        segments=[{"text": s.text.replace("\n", " ").strip(), "start": round(s.start, 2),
                   "duration": round(s.duration, 2)} for s in fetched.snippets if s.text.strip()],
    )


# ---------- storage ----------

def _ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _slug(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:max_len].rstrip("-") or "video"


def _paragraphs(segments: list[dict], seconds: int) -> list[tuple[float, str]]:
    """Group caption fragments into ~N-second paragraphs."""
    paras: list[tuple[float, str]] = []
    start, buf = None, []
    for seg in segments:
        if start is None:
            start = seg["start"]
        buf.append(seg["text"])
        if seg["start"] + seg.get("duration", 0) - start >= seconds:
            paras.append((start, " ".join(buf)))
            start, buf = None, []
    if buf:
        paras.append((start, " ".join(buf)))
    return paras


def to_markdown(t: Transcript, paragraph_seconds: int = 60) -> str:
    front = {
        "video_id": t.video_id, "title": t.title, "channel": t.channel, "url": video_url(t.video_id),
        "language": t.language, "language_code": t.language_code, "auto_generated": t.auto_generated,
        "duration": _ts(t.duration), "words": len(t.plain_text.split()), "fetched_at": t.fetched_at,
    }
    # JSON-encoded scalars are valid YAML, so titles with colons/quotes stay safe.
    lines = ["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()), "---", "",
             f"# {t.title}", ""]
    if t.channel:
        lines += [f"**Channel:** {t.channel}  ", f"**Video:** {video_url(t.video_id)}  ",
                  f"**Length:** {_ts(t.duration)}", ""]
    lines += ["## Transcript", ""]
    for start, text in _paragraphs(t.segments, paragraph_seconds):
        lines += [f"[{_ts(start)}]({video_url(t.video_id, start)}) {text}", ""]
    return "\n".join(lines)


def save(t: Transcript, directory: Path, paragraph_seconds: int = 60, keep_json: bool = False) -> Path:
    for old in directory.glob(f"*{t.video_id}.md"):
        old.unlink()  # re-fetch replaces the old file even if the title changed
    path = directory / f"{_slug(t.title)}--{t.video_id}.md"
    path.write_text(to_markdown(t, paragraph_seconds), encoding="utf-8")
    if keep_json:
        json_dir = directory / "json"
        json_dir.mkdir(exist_ok=True)
        (json_dir / f"{t.video_id}.json").write_text(
            json.dumps(t.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def find(directory: Path, video: str) -> Path | None:
    video_id = parse_video_id(video)
    return next(iter(sorted(directory.glob(f"*{video_id}.md"))), None)


def read_front_matter(path: Path) -> dict:
    meta: dict = {}
    with path.open(encoding="utf-8") as f:
        if f.readline().strip() != "---":
            return meta
        for line in f:
            if line.strip() == "---":
                break
            key, _, raw = line.partition(":")
            try:
                meta[key.strip()] = json.loads(raw.strip())
            except json.JSONDecodeError:
                meta[key.strip()] = raw.strip()
    meta["path"] = str(path)
    return meta


def list_saved(directory: Path) -> list[dict]:
    items = [read_front_matter(p) for p in directory.glob("*.md")]
    return sorted(items, key=lambda m: m.get("fetched_at", ""), reverse=True)


def search(directory: Path, query: str, context: int = 120, max_hits_per_video: int = 5) -> list[dict]:
    """Case-insensitive search across all transcripts; returns snippets with timestamp links."""
    needle = query.lower()
    results = []
    for path in directory.glob("*.md"):
        meta = read_front_matter(path)
        hits = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("[") or needle not in line.lower():
                continue
            link_end = line.find(") ")
            link, body = line[: link_end + 1], line[link_end + 2:]
            i = body.lower().find(needle)
            if i < 0:
                continue  # match was only inside the link
            snippet = body[max(0, i - context): i + len(query) + context]
            hits.append({"at": link, "snippet": snippet.strip()})
            if len(hits) >= max_hits_per_video:
                break
        if hits:
            results.append({"video_id": meta.get("video_id"), "title": meta.get("title"),
                            "path": str(path), "hits": hits})
    return results
