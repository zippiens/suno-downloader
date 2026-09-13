let currentSongData = null;

const form = document.getElementById("downloadForm");
const urlInput = document.getElementById("urlInput");
const pasteBtn = document.getElementById("pasteBtn");
const fetchBtn = document.getElementById("fetchBtn");
const alertBox = document.getElementById("alertBox");
const resultCard = document.getElementById("resultCard");
const coverImg = document.getElementById("coverImg");
const songTitle = document.getElementById("songTitle");
const songCreator = document.getElementById("songCreator");
const songTags = document.getElementById("songTags");
const audioPlayer = document.getElementById("audioPlayer");

pasteBtn.addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) urlInput.value = text.trim();
  } catch {
    showAlert("Clipboard diblok browser. Tempel manual dengan Ctrl+V.", "err");
  }
});

function showAlert(message, type = "info") {
  alertBox.className = "alert show " + type;
  alertBox.textContent = message;
}

function hideAlert() {
  alertBox.className = "alert";
}

function cloudfrontUrl(id) {
  return `https://d2lwuy8qc234o3.cloudfront.net/1/clip/${id}.m4a`;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) {
    showAlert("Tempel link lagu Suno dulu.", "err");
    return;
  }
  hideAlert();
  fetchBtn.disabled = true;
  fetchBtn.textContent = "Processing...";
  try {
    const res = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
    const json = await res.json();
    if (!res.ok || !json.success) throw new Error(json.detail || "Gagal ambil info lagu.");
    currentSongData = json.data;
    if (!currentSongData.audio_url && currentSongData.id) {
      currentSongData.audio_url = cloudfrontUrl(currentSongData.id);
    }
    renderSongPreview(currentSongData);
    showAlert("Track berhasil dimuat. Preview diputar langsung dari CDN Suno.", "ok");
  } catch (err) {
    showAlert(err.message, "err");
    resultCard.classList.remove("show");
  } finally {
    fetchBtn.disabled = false;
    fetchBtn.textContent = "Fetch Track";
  }
});

function renderSongPreview(song) {
  coverImg.src = song.image_url || "";
  songTitle.textContent = song.title || "Suno Track";
  songCreator.textContent = "By: " + (song.creator || "Suno Creator");
  if (song.tags) {
    songTags.textContent = "Style / Genre: " + song.tags;
    songTags.style.display = "block";
  } else {
    songTags.style.display = "none";
  }

  // File asli Suno = Opus di dalam M4A, browser tidak bisa play.
  const qs = new URLSearchParams({
    url: song.canonical_url || "",
    audio_url: song.audio_url || "",
  });
  audioPlayer.src = "/api/stream?" + qs.toString();
  audioPlayer.load();

  resultCard.classList.add("show");
  resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function saveBlob(blob, filename) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}

async function fetchDirectAudio(song) {
  const url = song.audio_url || (song.id ? cloudfrontUrl(song.id) : "");
  if (!url) throw new Error("Audio URL kosong.");
  const res = await fetch(url, { mode: "cors" });
  if (!res.ok) throw new Error("CDN audio HTTP " + res.status);
  const buf = await res.arrayBuffer();
  if (buf.byteLength < 2000) throw new Error("File audio terlalu kecil / diblokir.");
  return buf;
}

async function triggerDownload(format) {
  if (!currentSongData) return;
  const song = currentSongData;
  const name = song.safe_title || "suno-track";
  showAlert("Mengunduh " + format.toUpperCase() + "…", "info");
  try {
    if (format === "m4a") {
      const buf = await fetchDirectAudio(song);
      saveBlob(new Blob([buf], { type: "audio/mp4" }), name + ".m4a");
      showAlert("Original M4A tersimpan.", "ok");
      return;
    }

    // Coba konversi di server. Kalau gagal, tetap kasih file original.
    const qs = new URLSearchParams({
      url: song.canonical_url || "",
      audio_url: song.audio_url || "",
      title: song.title || name,
      format,
    });
    const res = await fetch("/api/download?" + qs.toString());
    const type = res.headers.get("content-type") || "";
    if (res.ok && !type.includes("application/json")) {
      const blob = await res.blob();
      saveBlob(blob, name + "." + format);
      showAlert(format.toUpperCase() + " tersimpan.", "ok");
      return;
    }
    let detail = "konversi server gagal";
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch (_) {}
    showAlert("Konversi " + format + " gagal (" + detail + "). Menyimpan original M4A.", "info");
    const buf = await fetchDirectAudio(song);
    saveBlob(new Blob([buf], { type: "audio/mp4" }), name + ".m4a");
  } catch (err) {
    showAlert("Download gagal: " + err.message, "err");
  }
}

window.triggerDownload = triggerDownload;
