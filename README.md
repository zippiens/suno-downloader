# Suno Stealth Downloader (Railway-ready)

Web downloader lagu Suno publik: paste `suno.com/song/...` atau `suno.com/s/...`, preview, unduh MP3 / WAV / original.

## Deploy ke Railway (paling gampang)

1. Buat repo GitHub baru, upload semua isi folder ini ke **root** repo.
2. Buka https://railway.app → **New Project** → **Deploy from GitHub repo**.
3. Pilih repo. Railway deteksi `Dockerfile` (FFmpeg sudah di-install di image).
4. Setelah build hijau, buka service → **Settings** → **Networking** → **Generate Domain**.
5. Cek health: `https://<domain>/health`

Tidak wajib ada environment variable.

Kalau build tanpa Docker / pakai Railpack, tambah variable:

```
RAILPACK_DEPLOY_APT_PACKAGES=ffmpeg
```

Start command cadangan:

```
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 180
```

## Deploy lewat Railway CLI

```bash
npm i -g @railway/cli
railway login
cd suno-downloader
railway init
railway up
railway domain
```

## Jalanin lokal

Butuh Python 3.10+ dan FFmpeg.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Buka http://127.0.0.1:5000

## Catatan
- Hanya lagu publik.
- Konversi MP3/WAV pakai FFmpeg di server.
- Hormati ToS Suno dan hak kreator.
