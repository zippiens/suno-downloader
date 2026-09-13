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
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
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
    m = UUID_RE.search(url)
    if m:
        return m.group(0)
    m = SHORT_RE.search(url)
    if m:
        try:
            r = SESSION.get(
                f"https://suno.com/s/{m.group(1)}",
                allow_redirects=True,
                timeout=20,
            )
            found = SONG_RE.search(r.url) or UUID_RE.search(r.url) or UUID_RE.search(r.text or "")
            if found:
                return found.group(1) if found.lastindex else found.group(0)
        except requests.RequestException:
            return None
    return None


def guess_urls(song_id: str) -> dict:
    return {
        "mp3": f"https://cdn1.suno.ai/{song_id}.mp3",
        "m4a": f"https://cdn1.suno.ai/{song_id}.m4a",
        "image": f"https://cdn2.suno.ai/image_{song_id}.jpeg",
        "image_large": f"https://cdn2.suno.ai/image_large_{song_id}.jpeg",
        "page": f"https://suno.com/song/{song_id}",
    }


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


def scrape_page(page_url: str) -> dict:
    data: dict = {}
    try:
        r = SESSION.get(page_url, timeout=20)
        text = r.text or ""
    except requests.RequestException:
        return data

    def grab(key: str) -> str | None:
        pat = rf'\\"{key}\\"\s*:\s*\\"(.*?)\\"'
        m = re.search(pat, text)
        if m:
            return m.group(1).encode("utf-8").decode("unicode_escape")
        pat2 = rf'"{key}"\s*:\s*"(.*?)"'
        m = re.search(pat2, text)
        return m.group(1) if m else None

    for key in ("title", "display_name", "handle", "tags", "prompt", "audio_url", "image_url"):
        val = grab(key)
        if val:
            data[key] = val
    m = re.search(r'og:title" content="([^"]+)"', text)
    if m and "title" not in data:
        data["title"] = m.group(1)
    m = re.search(r'og:image" content="([^"]+)"', text)
    if m and "image_url" not in data:
        data["image_url"] = m.group(1)
    m = re.search(r'(https://cdn[^"\\]+' + re.escape(extract_song_id(page_url) or "") + r'[^"\\]*)', text)
    if m and "audio_url" not in data:
        data["audio_url"] = m.group(1).replace("\\u0026", "&")
    return data


def resolve_track(url: str) -> dict:
    song_id = extract_song_id(url)
    if not song_id:
        raise ValueError("Link Suno tidak valid. Pakai suno.com/song/... atau suno.com/s/...")

    guessed = guess_urls(song_id)
    oembed = fetch_oembed(guessed["page"])
    scraped = scrape_page(guessed["page"])

    audio = scraped.get("audio_url")
    if not audio:
        if head_ok(guessed["mp3"]):
            audio = guessed["mp3"]
        elif head_ok(guessed["m4a"]):
            audio = guessed["m4a"]
        else:
            audio = guessed["mp3"]

    image = (
        scraped.get("image_url")
        or oembed.get("thumbnail_url")
        or guessed["image_large"]
    )
    title = scraped.get("title") or oembed.get("title") or f"Suno Track {song_id[:8]}"
    creator = (
        scraped.get("display_name")
        or scraped.get("handle")
        or oembed.get("author_name")
        or "Suno Creator"
    )
    tags = scraped.get("tags") or ""

    return {
        "id": song_id,
        "title": title,
        "safe_title": safe_filename(title),
        "creator": creator,
        "tags": tags,
        "image_url": image,
        "audio_url": audio,
        "canonical_url": guessed["page"],
    }


def download_bytes(url: str) -> bytes:
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def transcode(src: bytes, fmt: str) -> tuple[bytes, str]:
    fmt = fmt.lower()
    if fmt == "m4a":
        return src, "audio/mp4"
    if fmt not in {"mp3", "wav"}:
        raise ValueError("Format harus mp3, wav, atau m4a")

    suffix_in = ".bin"
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / f"in{suffix_in}"
        out = Path(td) / f"out.{fmt}"
        inp.write_bytes(src)
        cmd = ["ffmpeg", "-y", "-i", str(inp), "-vn"]
        if fmt == "mp3":
            cmd += ["-codec:a", "libmp3lame", "-b:a", "320k"]
        else:
            cmd += ["-codec:a", "pcm_s16le"]
        cmd += [str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(proc.stderr[-800:] or "ffmpeg gagal")
        mime = "audio/mpeg" if fmt == "mp3" else "audio/wav"
        return out.read_bytes(), mime


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
    url = request.args.get("url", "")
    try:
        track = resolve_track(url)
        r = SESSION.get(track["audio_url"], stream=True, timeout=60)
        r.raise_for_status()
        return Response(
            r.iter_content(64 * 1024),
            content_type=r.headers.get("Content-Type", "audio/mpeg"),
        )
    except Exception as e:
        return jsonify({"success": False, "detail": str(e)}), 502


@app.get("/api/download")
def api_download():
    url = request.args.get("url", "")
    fmt = (request.args.get("format") or "mp3").lower()
    try:
        track = resolve_track(url)
        raw = download_bytes(track["audio_url"])
        if fmt == "m4a" and track["audio_url"].endswith(".mp3"):
            # original stream is already mp3 on many tracks; still wrap as-is
            body, mime = raw, "audio/mpeg"
            ext = "mp3"
        else:
            body, mime = transcode(raw, fmt)
            ext = fmt
        filename = f"{track['safe_title']}.{ext}"
        return send_file(
            io.BytesIO(body),
            mimetype=mime,
            as_attachment=True,
            download_name=filename,
        )
    except ValueError as e:
        return jsonify({"success": False, "detail": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "detail": f"Download gagal: {e}"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
