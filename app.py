#!/usr/bin/env python3
"""Suno Stealth Downloader — local/self-hosted clone."""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote

import requests
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://suno.com/",
        "Origin": "https://suno.com",
    }
)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
SHORT_RE = re.compile(r"suno\.com/s/([A-Za-z0-9_-]+)", re.I)
SONG_RE = re.compile(r"suno\.com/(?:song|hook)/([0-9a-f-]{36})", re.I)


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", " ", name or "suno-track")
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:80] or "suno-track")


def extract_song_id(url: str) -> str | None:
    url = unquote((url or "").strip())
    m = SONG_RE.search(url)
    if m:
        return m.group(1)
    if UUID_RE.fullmatch(url.strip()):
        return url.strip()
    m = SHORT_RE.search(url)
    if m:
        try:
            r = SESSION.get(
                f"https://suno.com/s/{m.group(1)}",
                allow_redirects=False,
                timeout=20,
            )
            loc = r.headers.get("Location") or r.headers.get("location") or ""
            found = SONG_RE.search(loc) or SONG_RE.search(r.url)
            if found:
                return found.group(1)
            # Some shares only resolve when followed once.
            r2 = SESSION.get(
                f"https://suno.com/s/{m.group(1)}",
                allow_redirects=True,
                timeout=20,
            )
            found = SONG_RE.search(r2.url)
            if found:
                return found.group(1)
            # Do NOT scrape random UUIDs from the homepage.
        except requests.RequestException:
            return None
        raise ValueError(
            "Short link suno.com/s/... sekarang butuh buka di browser. "
            "Copy URL lengkap dari address bar: https://suno.com/song/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
    return None


CLOUDFRONT_AUDIO = "https://d2lwuy8qc234o3.cloudfront.net/1/clip/{id}.m4a"
BAD_AUDIO = ("forbidden", "studio-api.prod.suno.com")


def guess_urls(song_id: str) -> dict:
    return {
        "mp3": f"https://cdn1.suno.ai/{song_id}.mp3",
        "m4a": f"https://cdn1.suno.ai/{song_id}.m4a",
        "mp4": f"https://cdn1.suno.ai/{song_id}.mp4",
        "clip": CLOUDFRONT_AUDIO.format(id=song_id),
        "image": f"https://cdn2.suno.ai/image_{song_id}.jpeg",
        "image_large": f"https://cdn2.suno.ai/image_large_{song_id}.jpeg",
        "page": f"https://suno.com/song/{song_id}",
    }


def looks_like_media(data: bytes) -> bool:
    if not data or len(data) < 32:
        return False
    if data[4:8] == b"ftyp" or data[:3] == b"ID3" or data[:4] == b"RIFF" or data[:4] == b"OggS":
        return True
    if data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3" or data[:2] == b"\xff\xfa":
        return True
    return False


def is_playable_audio(url: str | None) -> bool:
    if not url:
        return False
    low = url.lower()
    if any(b in low for b in BAD_AUDIO):
        return False
    return low.startswith("http")


def head_ok(url: str) -> bool:
    try:
        r = SESSION.head(url, timeout=12, allow_redirects=True)
        if r.status_code == 200:
            return True
        r = SESSION.get(url, timeout=12, stream=True)
        ok = r.status_code == 200
        r.close()
        return ok
    except requests.RequestException:
        return False


def fetch_oembed(page_url: str) -> dict:
    try:
        r = SESSION.get(
            "https://suno.com/oembed",
            params={"url": page_url, "format": "json"},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def scrape_page(page_url: str, song_id: str) -> dict:
    data: dict = {}
    try:
        r = SESSION.get(page_url, timeout=20, allow_redirects=True)
        text = r.text or ""
    except requests.RequestException:
        return data

    og_title = re.search(r'property="og:title" content="([^"]+)"', text)
    if og_title:
        data["title"] = og_title.group(1)
    og_image = re.search(r'property="og:image" content="([^"]+)"', text)
    if og_image:
        data["image_url"] = og_image.group(1)

    # Real stream is in media_urls[], audio_url is often a "forbidden" stub now.
    media = re.findall(
        rf'https://d2lwuy8qc234o3\.cloudfront\.net/[^"\\]*{re.escape(song_id)}[^"\\]*',
        text,
    )
    media += re.findall(
        rf'https://cdn1\.suno\.ai/{re.escape(song_id)}\.(?:mp3|m4a)',
        text,
    )
    for u in media:
        if is_playable_audio(u):
            data["audio_url"] = u
            break

    sid_idx = text.find(song_id)
    window = text[max(0, sid_idx - 500) : sid_idx + 4000] if sid_idx >= 0 else text
    tags = re.search(r'"tags"\s*:\s*"([^"]*)"', window)
    if tags:
        data["tags"] = tags.group(1)
    handle = re.search(r'"(?:display_name|handle)"\s*:\s*"([^"]+)"', window)
    if handle:
        data["creator"] = handle.group(1)
    title2 = re.search(r'"title"\s*:\s*"([^"]+)"', window)
    if title2 and "title" not in data:
        t = title2.group(1)
        if t.lower() not in {"suno", "get the full app experience"}:
            data["title"] = t
    return data


def resolve_track(url: str) -> dict:
    song_id = extract_song_id(url)
    if not song_id:
        raise ValueError("Link Suno tidak valid. Pakai suno.com/song/... atau suno.com/s/...")

    guessed = guess_urls(song_id)
    scraped = scrape_page(guessed["page"], song_id)

    # CloudFront "m4a-opus" is not a real MP4 (no ftyp) — ffmpeg/browser reject it.
    # Playable source is the public MP4 on cdn1.suno.ai.
    video = guessed["mp4"] if head_ok(guessed["mp4"]) else None
    audio = None
    for candidate in (guessed["mp3"], guessed["m4a"], video):
        if candidate and head_ok(candidate):
            audio = candidate
            break
    if not audio:
        audio = video or guessed["mp4"]

    image = scraped.get("image_url") or guessed["image_large"]
    title = scraped.get("title") or f"Suno Track {song_id[:8]}"
    if title.lower() in {"get the full app experience", "suno", "suno | ai music generator"}:
        title = f"Suno Track {song_id[:8]}"
    creator = scraped.get("creator") or "Suno Creator"
    tags = scraped.get("tags") or ""

    return {
        "id": song_id,
        "title": title,
        "safe_title": safe_filename(title),
        "creator": creator,
        "tags": tags,
        "image_url": image,
        "audio_url": audio,
        "video_url": video or guessed["mp4"],
        "canonical_url": guessed["page"],
    }


def download_bytes(url: str) -> bytes:
    if not is_playable_audio(url):
        raise RuntimeError("Audio URL tidak valid / diblokir Suno")
    r = SESSION.get(url, timeout=90)
    r.raise_for_status()
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype or "text/xml" in ctype or len(r.content) < 2000:
        raise RuntimeError("CDN menolak file audio (403/HTML). Coba lagu publik lain.")
    if not looks_like_media(r.content):
        raise RuntimeError("File dari CDN bukan media yang bisa di-decode. Pakai URL MP4 cdn1.suno.ai.")
    return r.content


def _ffmpeg(inp: Path, out: Path, extra: list[str]) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(inp), "-vn", *extra, str(out)]
    return subprocess.run(cmd, capture_output=True, text=True)


def transcode(src: bytes, fmt: str) -> tuple[bytes, str]:
    fmt = fmt.lower()
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in.bin"
        inp.write_bytes(src)
        attempts: list[tuple[str, list[str], str]] = []
        if fmt == "m4a":
            attempts.append(("m4a", ["-c:a", "aac", "-b:a", "192k"], "audio/mp4"))
            attempts.append(("m4a", ["-c:a", "copy"], "audio/mp4"))
        elif fmt == "wav":
            attempts.append(("wav", ["-c:a", "pcm_s16le"], "audio/wav"))
        elif fmt == "aac":
            attempts.append(("m4a", ["-c:a", "aac", "-b:a", "192k"], "audio/mp4"))
            attempts.append(("wav", ["-c:a", "pcm_s16le"], "audio/wav"))
        elif fmt == "mp3":
            attempts.append(("mp3", ["-c:a", "libmp3lame", "-b:a", "320k"], "audio/mpeg"))
            attempts.append(("mp3", ["-c:a", "mp3", "-b:a", "192k"], "audio/mpeg"))
            attempts.append(("wav", ["-c:a", "pcm_s16le"], "audio/wav"))
        else:
            raise ValueError("Format harus mp3, wav, atau m4a")

        last_err = "ffmpeg gagal"
        for ext, extra, mime in attempts:
            out = Path(td) / f"out.{ext}"
            proc = _ffmpeg(inp, out, extra)
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 1000:
                return out.read_bytes(), mime
            last_err = (proc.stderr or proc.stdout or last_err)[-500:]
        raise RuntimeError(last_err)


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "status": "online"})


@app.get("/api/info")
def api_info():
    url = request.args.get("url", "")
    try:
        data = resolve_track(url)
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        return jsonify({"success": False, "detail": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "detail": f"Gagal ambil info: {e}"}), 502


@app.get("/api/stream")
def api_stream():
    """Browser cannot play Suno's Opus-in-M4A. Transcode to AAC for preview."""
    url = request.args.get("url", "")
    audio_url = request.args.get("audio_url", "")
    try:
        if audio_url and is_playable_audio(audio_url):
            raw = download_bytes(audio_url)
        else:
            raw = download_bytes(resolve_track(url)["audio_url"])
        body, mime = transcode(raw, "aac")
        return Response(body, content_type=mime)
    except Exception:
        try:
            track = resolve_track(url) if url else None
            src = audio_url or (track["audio_url"] if track else "")
            r = SESSION.get(src, stream=True, timeout=60)
            r.raise_for_status()
            return Response(
                r.iter_content(64 * 1024),
                content_type=r.headers.get("Content-Type", "audio/mp4"),
            )
        except Exception as e:
            return jsonify({"success": False, "detail": str(e)}), 502


@app.get("/api/download")
def api_download():
    url = request.args.get("url", "")
    fmt = (request.args.get("format") or "mp3").lower()
    audio_url = request.args.get("audio_url", "")
    title = request.args.get("title", "")
    try:
        if audio_url and is_playable_audio(audio_url):
            raw = download_bytes(audio_url)
            filename_base = safe_filename(title or "suno-track")
        else:
            track = resolve_track(url)
            raw = download_bytes(track["audio_url"])
            filename_base = track["safe_title"]
        body, mime = transcode(raw, fmt)
        return send_file(
            io.BytesIO(body),
            mimetype=mime,
            as_attachment=True,
            download_name=f"{filename_base}.{fmt}",
        )
    except ValueError as e:
        return jsonify({"success": False, "detail": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "detail": f"Download gagal: {e}"}), 502


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
