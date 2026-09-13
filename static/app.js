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
    renderSongPreview(currentSongData);
    showAlert("Track berhasil dimuat. Pilih format atau dengerin preview.", "ok");
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
  audioPlayer.src = `/api/stream?url=${encodeURIComponent(song.canonical_url)}`;
  audioPlayer.load();
  resultCard.classList.add("show");
  resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function triggerDownload(format) {
  if (!currentSongData) return;
  showAlert("Menyiapkan " + format.toUpperCase() + "... file akan terunduh sebentar lagi.", "info");
  const downloadUrl = `/api/download?url=${encodeURIComponent(currentSongData.canonical_url)}&format=${format}`;
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = `${currentSongData.safe_title}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
