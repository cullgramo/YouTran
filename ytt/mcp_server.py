"""MCP server so Claude can fetch, list, search and read transcripts directly.

Run with `ytt-mcp` (stdio). Library folder comes from $YTT_DIR (default ~/youtube-transcripts).
"""

from __future__ import annotations

import time

from mcp.server.mcpserver import MCPServer

from . import core

server = MCPServer(
    name="youtube-transcripts",
    instructions=(
        "Tools for a local library of YouTube transcripts stored as Markdown. "
        "Use get_transcript to fetch a new video (it is saved and returned), or get_playlist to "
        "fetch every video in a playlist (saved; returns a list, then read_transcript the ones you need). "
        "Use list_transcripts / search_transcripts to find saved ones, and read_transcript to load one. "
        "Transcript paragraphs start with a [mm:ss](url) link — cite those when quoting."
    ),
)


@server.tool()
def get_transcript(video: str, languages: list[str] | None = None, force: bool = False) -> str:
    """Fetch a YouTube video's transcript (URL or 11-char ID), save it to the library, and return it
    as Markdown. Returns the saved copy without re-downloading unless force=True.
    languages: preferred language codes in order, e.g. ["en", "de"]; falls back to any available."""
    directory = core.library_dir()
    if not force and (existing := core.find(directory, video)):
        return existing.read_text(encoding="utf-8")
    t = core.fetch_transcript(video, languages)
    return core.save(t, directory).read_text(encoding="utf-8")


@server.tool()
def get_playlist(playlist: str, languages: list[str] | None = None, force: bool = False,
                 max_videos: int = 50) -> dict:
    """Fetch and save transcripts for every video in a YouTube playlist (a playlist URL, a
    watch?v=...&list=... URL, or a playlist ID). Already-saved videos are skipped unless force=True.
    Returns the playlist title and, per video, its status (saved / already_saved / failed), title,
    word count and file path. Transcripts are NOT included: use read_transcript on the ones you need.
    max_videos caps how many are fetched (playlist order), since each takes a second or two."""
    directory = core.library_dir()
    title, ids = core.playlist_videos(playlist)
    results = []
    for i, video_id in enumerate(ids[:max_videos]):
        existing = None if force else core.find(directory, video_id)
        try:
            if existing:
                status, path = "already_saved", existing
            else:
                if i:
                    time.sleep(1)  # YouTube rate-limits bursts
                status, path = "saved", core.save(core.fetch_transcript(video_id, languages), directory)
            meta = core.read_front_matter(path)
            results.append({"video_id": video_id, "status": status, "title": meta.get("title"),
                            "duration": meta.get("duration"), "words": meta.get("words"), "path": str(path)})
        except core.TranscriptError as e:
            results.append({"video_id": video_id, "status": "failed", "error": str(e)})
    return {"playlist": title, "total_videos": len(ids), "fetched": len(results),
            "failed": sum(r["status"] == "failed" for r in results), "videos": results}


@server.tool()
def list_transcripts() -> list[dict]:
    """List every saved transcript with its title, channel, duration, word count and file path."""
    return core.list_saved(core.library_dir())


@server.tool()
def search_transcripts(query: str) -> list[dict]:
    """Case-insensitive text search across all saved transcripts. Returns matching snippets with
    timestamp links, grouped by video."""
    return core.search(core.library_dir(), query)


@server.tool()
def read_transcript(video: str) -> str:
    """Return a saved transcript (by URL or video ID) as Markdown without contacting YouTube."""
    path = core.find(core.library_dir(), video)
    if not path:
        raise ValueError(f"{video} is not in the library; call get_transcript first.")
    return path.read_text(encoding="utf-8")


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
