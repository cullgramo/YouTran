from types import SimpleNamespace

import pytest
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from ytt import cli, core

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("value", [
    VID, f"https://www.youtube.com/watch?v={VID}&t=42s", f"https://youtu.be/{VID}?si=abc",
    f"youtube.com/shorts/{VID}", f"https://m.youtube.com/watch?feature=share&v={VID}",
    f"https://www.youtube.com/embed/{VID}", f"https://www.youtube.com/live/{VID}",
])
def test_parse_video_id(value):
    assert core.parse_video_id(value) == VID


@pytest.mark.parametrize("value", ["", "hello", "https://vimeo.com/123", "https://youtube.com/@channel"])
def test_parse_video_id_rejects(value):
    with pytest.raises(core.TranscriptError):
        core.parse_video_id(value)


class FakeTranscript:
    def __init__(self, code, generated=False):
        self.language_code, self.is_generated = code, generated

    def fetch(self):
        snips = [SimpleNamespace(text=f"line {i} about\nllamas" if i == 70 else f"line {i}", start=i * 2.0, duration=2.0)
                 for i in range(100)]
        return SimpleNamespace(snippets=snips, language="English" if self.language_code == "en" else "German",
                               language_code=self.language_code, is_generated=self.is_generated)


class FakeList:
    def __init__(self, codes):
        self.items = [FakeTranscript(c) for c in codes]

    def __iter__(self):
        return iter(self.items)

    def find_transcript(self, langs):
        for lang in langs:
            for t in self.items:
                if t.language_code == lang:
                    return t
        raise NoTranscriptFound(VID, langs, self)


@pytest.fixture
def fake_youtube(monkeypatch):
    state = {"codes": ["en"], "disabled": False}

    class FakeApi:
        def __init__(self, **kw):
            pass

        def list(self, video_id):
            if state["disabled"]:
                raise TranscriptsDisabled(video_id)
            return FakeList(state["codes"])

    monkeypatch.setattr(core, "YouTubeTranscriptApi", FakeApi)
    monkeypatch.setattr(core, "fetch_metadata", lambda vid: {"title": 'Test: "Video" #1', "channel": "Chan"})
    return state


def test_fetch_save_list_search_show(fake_youtube, tmp_path, capsys):
    assert cli.main(["--dir", str(tmp_path), "get", f"https://youtu.be/{VID}"]) == 0
    files = list(tmp_path.glob("*.md"))
    assert [f.name for f in files] == [f"test-video-1--{VID}.md"]
    text = files[0].read_text()
    assert '"title": ' not in text and 'title: "Test: \\"Video\\" #1"' in text
    assert f"[00:00](https://www.youtube.com/watch?v={VID})" in text
    assert f"[02:00](https://www.youtube.com/watch?v={VID}&t=120s)" in text

    meta = core.list_saved(tmp_path)[0]
    assert meta["title"] == 'Test: "Video" #1' and meta["duration"] == "03:20" and meta["words"] == 202

    hits = core.search(tmp_path, "LLAMAS")
    assert len(hits) == 1 and "about llamas" in hits[0]["hits"][0]["snippet"]
    assert core.search(tmp_path, "watch?v") == []  # links aren't searched

    capsys.readouterr()
    cli.main(["--dir", str(tmp_path), "get", VID])
    assert "skip" in capsys.readouterr().out

    cli.main(["--dir", str(tmp_path), "show", VID, "--plain"])
    out = capsys.readouterr().out
    assert out.startswith("line 0 line 1") and "http" not in out


def test_language_fallback_and_strict(fake_youtube, tmp_path):
    fake_youtube["codes"] = ["de"]
    t = core.fetch_transcript(VID, ["en"])
    assert t.language_code == "de"
    with pytest.raises(core.TranscriptError):
        core.fetch_transcript(VID, ["en"], any_language=False)


def test_disabled_reports_failure(fake_youtube, tmp_path, capsys):
    fake_youtube["disabled"] = True
    assert cli.main(["--dir", str(tmp_path), "get", VID]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_stdout_prints_saved_copy(fake_youtube, tmp_path, capsys):
    cli.main(["--dir", str(tmp_path), "get", VID])
    capsys.readouterr()
    fake_youtube["disabled"] = True  # must not hit YouTube again
    assert cli.main(["--dir", str(tmp_path), "get", VID, "--stdout"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("---") and "skip" not in out


def test_lang_before_url(fake_youtube, tmp_path):
    fake_youtube["codes"] = ["en", "de"]
    assert cli.main(["--dir", str(tmp_path), "get", "-l", "de", "en", f"https://youtu.be/{VID}"]) == 0
    meta = core.list_saved(tmp_path)[0]
    assert meta["video_id"] == VID and meta["language_code"] == "de"


def test_mcp_tools(fake_youtube, tmp_path, monkeypatch):
    from ytt import mcp_server as m
    monkeypatch.setenv("YTT_DIR", str(tmp_path))
    md = m.get_transcript(VID)
    assert md.startswith("---") and m.read_transcript(VID) == md
    assert m.list_transcripts()[0]["video_id"] == VID
    assert m.search_transcripts("llamas")[0]["hits"]


PL = "PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF"
VIDS = [VID, "aaaaaaaaaaa", "bbbbbbbbbbb"]


@pytest.mark.parametrize("value, include_watch, expected", [
    (f"https://www.youtube.com/playlist?list={PL}", False, PL),
    (f"youtube.com/playlist?list={PL}&si=x", False, PL),
    (f"https://music.youtube.com/playlist?list={PL}", False, PL),
    (f"https://www.youtube.com/watch?v={VID}&list={PL}", False, None),  # just the video by default
    (f"https://www.youtube.com/watch?v={VID}&list={PL}", True, PL),
    (f"https://youtu.be/{VID}?list={PL}", True, PL),
    (f"https://youtu.be/{VID}", True, None),
    (f"https://vimeo.com/playlist?list={PL}", True, None),
])
def test_playlist_id(value, include_watch, expected):
    assert core.playlist_id(value, include_watch) == expected


@pytest.fixture
def fake_playlist(monkeypatch):
    calls = []

    def fake(value, proxy=None):
        calls.append(value)
        if "BAD" in value:
            raise core.TranscriptError("Could not read playlist BAD")
        return "My list", VIDS

    monkeypatch.setattr(core, "playlist_videos", fake)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    return calls


def test_cli_playlist(fake_youtube, fake_playlist, tmp_path, capsys):
    cli.main(["--dir", str(tmp_path), "get", VID])  # one already saved
    capsys.readouterr()
    assert cli.main(["--dir", str(tmp_path), "get", f"https://www.youtube.com/playlist?list={PL}"]) == 0
    out, err = capsys.readouterr()
    assert "My list: 3 videos" in err and "2 saved, 1 already saved, 0 failed" in err
    assert {m["video_id"] for m in core.list_saved(tmp_path)} == set(VIDS)


def test_cli_watch_link_needs_flag(fake_youtube, fake_playlist, tmp_path):
    link = f"https://www.youtube.com/watch?v={VID}&list={PL}"
    cli.main(["--dir", str(tmp_path), "get", link])
    assert fake_playlist == [] and len(core.list_saved(tmp_path)) == 1
    cli.main(["--dir", str(tmp_path), "get", "-p", link])
    assert fake_playlist == [link] and len(core.list_saved(tmp_path)) == 3


def test_cli_bad_playlist(fake_youtube, fake_playlist, tmp_path, capsys):
    assert cli.main(["--dir", str(tmp_path), "get", "https://www.youtube.com/playlist?list=BAD"]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_mcp_get_playlist(fake_youtube, fake_playlist, tmp_path, monkeypatch):
    from ytt import mcp_server as m
    monkeypatch.setenv("YTT_DIR", str(tmp_path))
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    m.get_transcript(VID)
    res = m.get_playlist(PL, max_videos=2)
    assert res["playlist"] == "My list" and res["total_videos"] == 3 and res["fetched"] == 2
    assert [v["status"] for v in res["videos"]] == ["already_saved", "saved"]
    assert res["videos"][1]["words"] == 202 and m.read_transcript("aaaaaaaaaaa")


def test_cli_playlist_limit(fake_youtube, fake_playlist, tmp_path, capsys):
    cli.main(["--dir", str(tmp_path), "get", "--limit", "2", f"https://www.youtube.com/playlist?list={PL}"])
    assert "taking the first 2" in capsys.readouterr().err and len(core.list_saved(tmp_path)) == 2
