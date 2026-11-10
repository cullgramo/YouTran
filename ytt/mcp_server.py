"""MCP server so Claude can fetch, list, search and read transcripts directly.

Run with `ytt-mcp` (stdio). Library folder comes from $YTT_DIR (default ~/youtube-transcripts).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import core

server = MCPServer(
    name="youtube-transcripts",
    instructions=(
        "Tools for a local library of YouTube transcripts stored as Markdown. "
        "Use get_transcript to fetch a new video (it is saved and returned). "
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
