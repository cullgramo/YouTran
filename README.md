# YouTran (`ytt`): YouTube transcripts for you and Claude

Downloads YouTube transcripts into a folder of Markdown files (default `~/youtube-transcripts`,
override with `$YTT_DIR` or `--dir`). Each file has YAML front matter (title, channel, URL,
language, duration, word count) and the transcript in ~60-second paragraphs, each starting with a
clickable `[mm:ss]` link back to that moment in the video.

```markdown
---
video_id: "dQw4w9WgXcQ"
title: "Some talk"
channel: "Some channel"
...
---
# Some talk
## Transcript
[00:00](https://www.youtube.com/watch?v=dQw4w9WgXcQ) Welcome everyone, today we're going to...
[01:00](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=60s) So the first thing to understand...
```

## Install

```bash
pip install -e ".[mcp]"        # or: pipx install -e ".[mcp]"
```

## Use it yourself

```bash
ytt get https://youtu.be/VIDEO_ID another_id      # fetch & save (skips ones already saved)
ytt get -f urls.txt                               # one URL per line
ytt get "https://www.youtube.com/playlist?list=PL..."   # every video in a playlist
ytt get -p "https://www.youtube.com/watch?v=ID&list=PL..."  # whole playlist from a video link
ytt get --limit 10 PLAYLIST_URL                   # just the first 10
ytt get URL -l de en                              # prefer German, then English
ytt get URL --stdout | pbcopy                     # don't save, just print
ytt list                                          # what's in the library
ytt search "gradient descent"                     # search across everything
ytt show VIDEO_ID --plain                         # text only, for piping elsewhere
```

If no transcript exists in the requested languages, it falls back to any available language
(use `--strict` to fail instead). Manual captions are preferred over auto-generated ones.

Playlist links (`/playlist?list=...`) are expanded into their videos using `yt-dlp` (metadata
only, nothing is downloaded). A `watch?v=...&list=...` link fetches just that video unless you add `-p`.
Videos already in the library are skipped, so re-running a playlist only fetches new ones.

## Let Claude use it

**Option 1: just files.** Point Claude Code at the library folder (`cd ~/youtube-transcripts && claude`,
or `/add-dir ~/youtube-transcripts`) and ask it to read, summarise or compare transcripts.

**Option 2: MCP server.** Claude gets `get_transcript`, `get_playlist`, `list_transcripts`,
`search_transcripts` and `read_transcript` tools, so you can say "summarise this video: <url>"
or "summarise each video in this playlist: <url>".

Claude Code:
```bash
claude mcp add youtube-transcripts --scope user -- ytt-mcp
```

Claude Desktop (`claude_desktop_config.json`):
```json
{ "mcpServers": { "youtube-transcripts": { "command": "/full/path/to/ytt-mcp",
    "env": { "YTT_DIR": "/Users/you/youtube-transcripts" } } } }
```

## If YouTube blocks you

YouTube often blocks requests from cloud and datacenter IPs (`RequestBlocked` / `IpBlocked`).
On a home connection it normally just works. Otherwise, pass a proxy with `--proxy http://user:pass@host:port`
or set `$YTT_PROXY`. `--delay` (default 1s) spaces out batch downloads.

## Tests

```bash
pip install -e ".[dev,mcp]" && pytest
```
