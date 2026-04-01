const photo = document.getElementById("photo");
const emptyState = document.getElementById("empty-state");
const nameTag = document.getElementById("name-tag");
const touseBtn = document.getElementById("touse-btn");
const bouseBtn = document.getElementById("bouse-btn");
const uploadForm = document.getElementById("upload-form");
const uploadNote = document.getElementById("upload-note");
const lbOverall = document.getElementById("lb-overall");
const lbTousers = document.getElementById("lb-tousers");
const lbBousers = document.getElementById("lb-bousers");
const myVote = document.getElementById("my-vote");
const nameInput = uploadForm.querySelector("input[name='name']");
const affiliationSelect = document.getElementById("affiliation-select");
const fileInput = document.getElementById("file-input");
const dropZone = document.getElementById("drop-zone");
const dropZonePreview = document.getElementById("drop-zone-preview");
const dropZoneImg = document.getElementById("drop-zone-img");
const dropZoneClear = document.getElementById("drop-zone-clear");
const cropModal = document.getElementById("crop-modal");
const cropImg = document.getElementById("crop-img");
const cropConfirm = document.getElementById("crop-confirm");
const cropCancel = document.getElementById("crop-cancel");
const leaderboardToggle = document.getElementById("leaderboard-toggle");
const lbTabs = document.querySelectorAll(".lb-tab");
const lbAffilFilter = document.getElementById("lb-affil-filter");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const commentsList = document.getElementById("comments-list");
const commentForm = document.getElementById("comment-form");
const commentInput = document.getElementById("comment-input");
const commentNote = document.getElementById("comment-note");
const imageFrame = document.querySelector(".image-frame");

let currentImageId = null;
let isVoting = false;
let pendingCroppedDataUrl = null;
let pendingFileName = null;
let cropperInstance = null;
let nsfwModel = null;

if (typeof nsfwjs !== "undefined") {
  nsfwjs.load("https://unpkg.com/nsfwjs/quant_nsfw_mobilenet/").then(m => {
    nsfwModel = m;
  }).catch(() => {});
}

function openCropModal(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    pendingFileName = file.name;
    if (cropperInstance) {
      cropperInstance.destroy();
      cropperInstance = null;
    }
    cropImg.src = e.target.result;
    cropModal.style.display = "flex";
    cropperInstance = new Cropper(cropImg, {
      viewMode: 2,
      dragMode: "move",
      autoCropArea: 1,
      responsive: true,
    });
  };
  reader.readAsDataURL(file);
}

dropZone.addEventListener("click", () => fileInput.click());

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("drag-over");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith("image/")) {
    openCropModal(file);
  } else if (file) {
    uploadNote.textContent = "only image files are supported";
  }
});

fileInput.addEventListener("change", () => {
  if (fileInput.files && fileInput.files[0]) {
    openCropModal(fileInput.files[0]);
    fileInput.value = "";
  }
});

cropConfirm.addEventListener("click", async () => {
  if (!cropperInstance) return;
  const canvas = cropperInstance.getCroppedCanvas({ maxWidth: 1200, maxHeight: 1200 });

  if (nsfwModel) {
    cropConfirm.disabled = true;
    cropConfirm.textContent = "Checking...";
    try {
      const predictions = await nsfwModel.classify(canvas);
      const score = (cls) => predictions.find(p => p.className === cls)?.probability || 0;
      if (score("Porn") > 0.5 || score("Hentai") > 0.6 || score("Sexy") > 0.75) {
        cropConfirm.disabled = false;
        cropConfirm.textContent = "Use this crop";
        uploadNote.textContent = "image rejected: nudity detected";
        cropModal.style.display = "none";
        cropperInstance.destroy();
        cropperInstance = null;
        return;
      }
    } catch (_) {}
    cropConfirm.disabled = false;
    cropConfirm.textContent = "Use this crop";
  }

  pendingCroppedDataUrl = canvas.toDataURL("image/jpeg", 0.9);
  cropperInstance.destroy();
  cropperInstance = null;
  cropModal.style.display = "none";
  dropZoneImg.src = pendingCroppedDataUrl;
  dropZonePreview.style.display = "inline-block";
  dropZone.querySelector(".drop-zone-text").style.display = "none";
  uploadNote.textContent = "";
});

cropCancel.addEventListener("click", () => {
  if (cropperInstance) {
    cropperInstance.destroy();
    cropperInstance = null;
  }
  cropModal.style.display = "none";
  if (!pendingCroppedDataUrl) {
    pendingFileName = null;
  }
});

dropZoneClear.addEventListener("click", (e) => {
  e.stopPropagation();
  pendingCroppedDataUrl = null;
  pendingFileName = null;
  dropZonePreview.style.display = "none";
  dropZone.querySelector(".drop-zone-text").style.display = "";
});
let leaderboardLimit = 20;

async function adjustImageDisplay(imgEl) {
  const w = imgEl.naturalWidth;
  const h = imgEl.naturalHeight;
  if (w && h) {
    imageFrame.style.aspectRatio = `${w} / ${h}`;
  }
  imgEl.style.objectPosition = "center center";
  if ("FaceDetector" in window) {
    try {
      const detector = new FaceDetector({ fastMode: true });
      const faces = await detector.detect(imgEl);
      if (faces.length > 0) {
        const face = faces.reduce((a, b) =>
          a.boundingBox.width * a.boundingBox.height >= b.boundingBox.width * b.boundingBox.height ? a : b
        );
        const xPct = ((face.boundingBox.left + face.boundingBox.width / 2) / w * 100).toFixed(1);
        const yPct = ((face.boundingBox.top + face.boundingBox.height / 2) / h * 100).toFixed(1);
        imgEl.style.objectPosition = `${xPct}% ${yPct}%`;
      }
    } catch (_) {}
  }
}
const debugMode = new URLSearchParams(window.location.search).get("debug") === "1";

// Track seen image IDs to avoid repeats within a cycle.
// Once every image has been seen, the set resets and the cycle starts over.
let seenIds = new Set();
let totalImageCount = null; // populated from leaderboard meta

const RANK_CLASSES = ["gold", "silver", "bronze"];

function renderBoard(items, container) {
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<div class="lb-empty">No votes yet.</div>';
    return;
  }
  items.forEach((item, index) => {
    const total = item.touse + item.bouse;
    const tousePct = total > 0 ? Math.round((item.touse / total) * 100) : 0;
    const rankClass = index < 3 ? ` ${RANK_CLASSES[index]}` : "";
    const name = item.person_name.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const affilText = item.affiliation ? item.affiliation.replace(/</g, "&lt;") : "";
    const affil = affilText ? `<span class="affiliation-badge" data-affil="${affilText}">${affilText}</span>` : "";
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `
      <div class="rank${rankClass}">#${index + 1}</div>
      <div class="row-thumb-wrap"><img class="row-thumb" src="/uploads/${item.filename}" alt="${name}" /></div>
      <div class="row-name">${name}</div>
      ${affil}
      <div class="row-counts">
        <div class="mini-bar"><div class="mini-bar-fill" style="width:${tousePct}%"></div></div>
        <div class="row-stats"><span class="stat-touse">${item.touse}T</span> <span class="stat-bouse">${item.bouse}B</span></div>
      </div>
    `;
    const thumb = row.querySelector(".row-thumb");
    thumb.onerror = () => { thumb.style.display = "none"; };
    container.appendChild(row);
  });
}

let lbData = null;

async function loadLeaderboard() {
  lbOverall.innerHTML = '<div class="lb-empty">Loading...</div>';
  const ts = Date.now();
  const affil = lbAffilFilter.value;
  const params = new URLSearchParams({ limit: leaderboardLimit, ts });
  if (affil) params.set("affiliation", affil);
  let res;
  try {
    res = await fetch(`/api/leaderboard?${params}`, {
      cache: "no-store",
    });
  } catch (err) {
    lbOverall.innerHTML = '<div class="lb-empty">Failed to load leaderboard.</div>';
    return;
  }
  if (!res.ok) {
    lbOverall.innerHTML = `<div class="lb-empty">Leaderboard error (${res.status}).</div>`;
    return;
  }
  const data = await res.json();
  lbData = data;
  if (data.meta) {
    totalImageCount = data.meta.total_count;
  }
  renderBoard(data.overall || [], lbOverall);
  renderBoard(data.top_tousers || [], lbTousers);
  renderBoard(data.top_bousers || [], lbBousers);
}

// Tab switching
lbTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    lbTabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const which = tab.dataset.tab;
    lbOverall.style.display = which === "overall" ? "" : "none";
    lbTousers.style.display = which === "tousers" ? "" : "none";
    lbBousers.style.display = which === "bousers" ? "" : "none";
  });
});

const commentsCount = document.getElementById("comments-count");

function renderComment(c) {
  const score = c.upvotes - c.downvotes;
  const scoreClass = score > 0 ? " positive" : score < 0 ? " negative" : "";
  const el = document.createElement("div");
  el.className = "comment";
  el.innerHTML = `
    <div class="comment-votes">
      <button class="comment-vote-btn${c.my_vote === "up" ? " active-up" : ""}" data-id="${c.id}" data-dir="up">&#9650;</button>
      <span class="comment-score${scoreClass}">${score}</span>
      <button class="comment-vote-btn${c.my_vote === "down" ? " active-down" : ""}" data-id="${c.id}" data-dir="down">&#9660;</button>
    </div>
    <div class="comment-body"></div>
  `;
  el.querySelector(".comment-body").textContent = c.text;
  return el;
}

async function loadComments(imageId) {
  if (!imageId) return;
  commentsList.innerHTML = '<span class="comment-loading">Loading...</span>';
  try {
    const res = await fetch(`/api/comments?id=${imageId}`);
    if (!res.ok) {
      commentsList.innerHTML = `<span class="comment-empty">Failed to load comments (${res.status}).</span>`;
      return;
    }
    const data = await res.json();
    commentsList.innerHTML = "";
    commentsCount.textContent = data.length ? `(${data.length})` : "";
    if (!data.length) {
      commentsList.innerHTML = '<span class="comment-empty">No comments yet. Be the first!</span>';
      return;
    }
    data.forEach((c) => commentsList.appendChild(renderComment(c)));
  } catch (err) {
    console.error("loadComments error:", err);
    commentsList.innerHTML = '<span class="comment-empty">Failed to load comments.</span>';
  }
}

commentsList.addEventListener("click", async (e) => {
  const btn = e.target.closest(".comment-vote-btn");
  if (!btn) return;
  const commentId = Number(btn.dataset.id);
  const dir = btn.dataset.dir;
  try {
    const res = await fetch("/api/comment/vote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment_id: commentId, vote: dir }),
    });
    if (res.ok) {
      await loadComments(currentImageId);
    }
  } catch (_) {}
});

commentForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentImageId) return;
  const text = commentInput.value.trim();
  if (!text) return;
  commentNote.textContent = "";
  try {
    const res = await fetch("/api/comment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: currentImageId, text }),
    });
    if (res.ok) {
      commentInput.value = "";
      await loadComments(currentImageId);
    } else {
      const data = await res.json();
      commentNote.textContent = data.error || "failed to post";
    }
  } catch (err) {
    commentNote.textContent = "failed to post comment";
  }
});

async function loadImageById(id) {
  let res;
  try {
    res = await fetch(`/api/image?id=${id}`);
  } catch (err) { return; }
  const data = await res.json();
  if (data.empty || !data.person_name) return;
  seenIds.add(data.id);
  currentImageId = data.id;
  emptyState.style.display = "none";
  imageFrame.style.aspectRatio = "";
  photo.style.objectPosition = "center center";
  photo.src = `/uploads/${data.filename}`;
  photo.onload = async () => { await adjustImageDisplay(photo); photo.classList.add("loaded"); };
  nameTag.innerHTML = "";
  nameTag.appendChild(document.createTextNode(data.person_name));
  if (data.affiliation) {
    const badge = document.createElement("span");
    badge.className = "affiliation-badge";
    badge.textContent = data.affiliation;
    nameTag.appendChild(badge);
  }
  nameTag.style.display = "inline-flex";
  myVote.textContent = `Your vote: ${data.my_vote || "—"}`;
  touseBtn.classList.toggle("selected", data.my_vote === "touse");
  bouseBtn.classList.toggle("selected", data.my_vote === "bouse");
  await loadComments(data.id);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

let searchTimer = null;

async function runSearch() {
  const q = searchInput.value.trim();
  if (!q) { searchResults.style.display = "none"; searchResults.innerHTML = ""; return; }
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  const items = await res.json();
    if (!items.length) {
      searchResults.innerHTML = '<div class="search-empty">No results found.</div>';
      searchResults.style.display = "block";
      return;
    }
    searchResults.innerHTML = "";
    items.forEach((item) => {
      const name = item.person_name.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const affil = item.affiliation ? `<span class="affiliation-badge">${item.affiliation.replace(/</g, "&lt;")}</span>` : "";
      const el = document.createElement("div");
      el.className = "search-result-row";
      el.innerHTML = `
        <img class="search-thumb" src="/uploads/${item.filename}" alt="${name}" />
        <div class="search-info">
          <div class="search-name">${name}${affil}</div>
          <div class="search-stats"><span class="stat-touse">${item.touse}T</span> <span class="stat-bouse">${item.bouse}B</span></div>
        </div>
      `;
      el.addEventListener("click", () => {
        loadImageById(item.id);
        searchResults.style.display = "none";
        searchInput.value = "";
      });
      searchResults.appendChild(el);
    });
    searchResults.style.display = "block";
}

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 300);
});


document.addEventListener("click", (e) => {
  if (!searchResults.contains(e.target) && e.target !== searchInput) {
    searchResults.style.display = "none";
  }
});

async function loadRandom() {
  // Keep re-fetching until we get an image we haven't seen this cycle.
  // Bail out after a reasonable number of attempts to avoid infinite loops
  // (e.g. if only 1 image exists).
  const maxAttempts = 20;
  let data = null;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let res;
    try {
      res = await fetch("/api/random");
    } catch (err) {
      emptyState.style.display = "flex";
      emptyState.textContent = "Failed to load image.";
      return;
    }

    const candidate = await res.json();

    if (candidate.empty) {
      currentImageId = null;
      photo.classList.remove("loaded");
      photo.removeAttribute("src");
      emptyState.style.display = "flex";
      nameTag.style.display = "none";
      myVote.textContent = "Your vote: —";
      commentsList.innerHTML = "";
      return;
    }

    // If this image hasn't been seen yet in this cycle, use it.
    if (!seenIds.has(candidate.id)) {
      data = candidate;
      break;
    }

    // If we've now seen every image, reset the cycle and use this one.
    const knownTotal = totalImageCount || 0;
    if (knownTotal > 0 && seenIds.size >= knownTotal) {
      seenIds.clear();
      data = candidate;
      break;
    }
  }

  // Fallback: if all attempts returned seen images (e.g. very few images),
  // reset and just use the last candidate by re-fetching fresh.
  if (!data) {
    seenIds.clear();
    let res;
    try {
      res = await fetch("/api/random");
    } catch (err) {
      emptyState.style.display = "flex";
      emptyState.textContent = "Failed to load image.";
      return;
    }
    data = await res.json();
    if (data.empty) {
      currentImageId = null;
      photo.classList.remove("loaded");
      photo.removeAttribute("src");
      emptyState.style.display = "flex";
      nameTag.style.display = "none";
      myVote.textContent = "Your vote: —";
      commentsList.innerHTML = "";
      return;
    }
  }

  // Mark this image as seen in the current cycle.
  seenIds.add(data.id);

  currentImageId = data.id;
  emptyState.style.display = "none";
  imageFrame.style.aspectRatio = "";
  photo.style.objectPosition = "center center";
  photo.src = `/uploads/${data.filename}`;
  photo.onload = async () => {
    await adjustImageDisplay(photo);
    photo.classList.add("loaded");
  };
  if (!data.person_name) {
    nameTag.style.display = "none";
    uploadNote.textContent = "upload error: missing name for this image";
    return;
  }
  const photoAffil = document.getElementById("photo-affiliation");
  if (data.affiliation) {
    photoAffil.textContent = data.affiliation;
    photoAffil.setAttribute("data-affil", data.affiliation);
    photoAffil.style.display = "";
  } else {
    photoAffil.textContent = "";
    photoAffil.style.display = "none";
  }
  nameTag.textContent = data.person_name;
  nameTag.style.display = "inline-flex";
  myVote.textContent = `Your vote: ${data.my_vote || "—"}`;
  touseBtn.classList.toggle("selected", data.my_vote === "touse");
  bouseBtn.classList.toggle("selected", data.my_vote === "bouse");
  await loadComments(data.id);
}

 async function vote(type) {
    if (!currentImageId || isVoting) return;
    isVoting = true;
    touseBtn.disabled = true;
    bouseBtn.disabled = true;
    const res = await fetch("/api/vote", {                                           
      method: "POST",
      headers: { "Content-Type": "application/json" },                               
      body: JSON.stringify({ image_id: currentImageId, vote: type }),
    });                                                                              
    if (res.ok) {
      const data = await res.json();                                                 
      const total = data.touse + data.bouse;                
      const tousePct = total > 0 ? Math.round((data.touse / total) * 100) : 50;
      const bousePct = 100 - tousePct;                                               
      const voteResult = document.getElementById("vote-result");                     
      const voteBarTouse = document.getElementById("vote-bar-touse");                
      const voteCounts = document.getElementById("vote-counts");                     
      voteResult.style.display = "block";                   
      voteBarTouse.style.width = tousePct + "%";                                     
      voteCounts.innerHTML = `<span>${tousePct}% touse</span><span>${bousePct}%      
  bouse</span>`;
      await new Promise(r => setTimeout(r, 1800));                                   
      voteResult.style.display = "none";                                             
      await loadRandom();
      await loadLeaderboard();                                                       
    }                                                       
    touseBtn.disabled = false;                                                       
    bouseBtn.disabled = false;
    isVoting = false;                                                                
  }                                    

touseBtn.addEventListener("click", () => vote("touse"));
bouseBtn.addEventListener("click", () => vote("bouse"));

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const trimmedName = nameInput.value.trim();
  if (!trimmedName) {
    uploadNote.textContent = "name is required";
    return;
  }
  if (!pendingCroppedDataUrl) {
    uploadNote.textContent = "image is required";
    return;
  }
  uploadNote.textContent = "uploading...";
  // Always send a .jpg filename since we export as JPEG from the canvas
  const uploadFilename = (pendingFileName || "upload").replace(/\.[^.]*$/, "") + ".jpg";
  let res;
  try {
    res = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: trimmedName,
        affiliation: affiliationSelect.value || null,
        filename: uploadFilename,
        data_url: pendingCroppedDataUrl,
      }),
    });
  } catch (err) {
    uploadNote.textContent = "network error — try again";
    return;
  }
  if (!res.ok) {
    let message = `upload failed (${res.status})`;
    try {
      const data = await res.json();
      if (data && data.error) message = data.error;
    } catch (_) {
      try {
        const text = await res.text();
        if (text) message = text.slice(0, 120);
      } catch (_2) {}
    }
    uploadNote.textContent = message;
    return;
  }
  uploadNote.textContent = "uploaded";
  uploadForm.reset();
  pendingCroppedDataUrl = null;
  pendingFileName = null;
  dropZonePreview.style.display = "none";
  dropZone.querySelector(".drop-zone-text").style.display = "";
  // Reset the cycle so the newly uploaded image can appear soon.
  seenIds.clear();
  await loadRandom();
  await loadLeaderboard();
  setTimeout(() => (uploadNote.textContent = ""), 1500);
});

loadRandom();
loadLeaderboard();

leaderboardToggle.addEventListener("click", async () => {
  leaderboardLimit = leaderboardLimit === 20 ? 100 : 20;
  leaderboardToggle.textContent = leaderboardLimit === 20 ? "Show top 100" : "Show top 20";
  await loadLeaderboard();
});

lbAffilFilter.addEventListener("change", () => loadLeaderboard());