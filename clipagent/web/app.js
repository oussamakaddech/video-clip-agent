/* clipagent — interface web (vanilla JS, sans dépendance). */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { mode: "url", jobId: null, eventSource: null };

  // ---------- Santé du service ----------
  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      const parts = [`v${data.version}`];
      parts.push(data.llm ? "IA : activée" : "IA : mode heuristique");
      parts.push(`ffmpeg ${data.ffmpeg ? "✓" : "✗"}`);
      parts.push(`Whisper ${data.whisper ? "✓" : "✗"}`);
      parts.push(`OpenCV ${data.opencv ? "✓" : "✗"}`);
      parts.push(`${data.free_disk_mb} Mo libres`);
      $("health-text").textContent = parts.join(" · ");
      $("health").classList.add(data.llm ? "ok" : "ko");
    } catch (err) {
      $("health-text").textContent = "API injoignable";
      $("health").classList.add("ko");
    }
  }

  // ---------- Styles ----------
  async function loadStyles() {
    try {
      const res = await fetch("/api/styles");
      const data = await res.json();
      const select = $("input-style");
      select.innerHTML = "";
      data.styles.forEach((style) => {
        const option = document.createElement("option");
        option.value = style.name;
        option.textContent = `${style.label} — ${style.description}`;
        select.appendChild(option);
      });
      select.value = "tiktok";
    } catch (err) {
      console.error(err);
    }
  }

  // ---------- Onglets de source ----------
  document.querySelectorAll("#source-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#source-tabs .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.mode = tab.dataset.mode;
      $("field-url").classList.toggle("hidden", state.mode !== "url");
      $("field-file").classList.toggle("hidden", state.mode !== "file");
      $("field-transcript").classList.toggle("hidden", state.mode !== "transcript");
    });
  });

  $("input-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    $("file-name").textContent = file ? `${file.name} (${(file.size / 1048576).toFixed(1)} Mo)` : "Aucun fichier sélectionné.";
  });
  $("input-transcript").addEventListener("change", (e) => {
    const file = e.target.files[0];
    $("transcript-name").textContent = file ? file.name : "Aucun fichier sélectionné.";
  });

  // ---------- Démarrage ----------
  async function uploadFile(file) {
    const data = new FormData();
    data.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: data });
    if (!res.ok) throw new Error("Téléversement impossible");
    return (await res.json()).path;
  }

  $("btn-start").addEventListener("click", async () => {
    const button = $("btn-start");
    const hint = $("start-hint");
    hint.textContent = "";
    hint.classList.remove("error");

    const payload = {
      style: $("input-style").value,
      language: $("input-language").value || null,
      num_clips: Number($("input-num").value),
      min_clip: Number($("input-min").value),
      max_clip: Number($("input-max").value),
      instruction: $("input-instruction").value,
      subtitles: $("input-subs").checked,
      facecam: $("input-facecam").checked ? true : null,
      render: $("input-render").checked,
    };

    try {
      button.disabled = true;
      hint.textContent = "Préparation…";

      if (state.mode === "url") {
        payload.url = $("input-url").value.trim();
        if (!payload.url) throw new Error("Indiquez l'URL de la VOD.");
      } else if (state.mode === "file") {
        const file = $("input-file").files[0];
        if (!file) throw new Error("Sélectionnez une vidéo.");
        payload.video_path = await uploadFile(file);
      } else {
        const file = $("input-transcript").files[0];
        if (!file) throw new Error("Sélectionnez une transcription.");
        payload.transcript_path = await uploadFile(file);
      }

      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail.slice(0, 200));
      }
      const job = await res.json();
      state.jobId = job.id;
      $("results").innerHTML = "";
      watch(job.id);
    } catch (err) {
      hint.textContent = err.message;
      hint.classList.add("error");
      button.disabled = false;
    }
  });

  // ---------- Suivi en direct (SSE) ----------
  function watch(jobId) {
    if (state.eventSource) state.eventSource.close();
    const badge = $("job-badge");
    badge.textContent = jobId.slice(0, 8);
    badge.className = "badge running";

    const source = new EventSource(`/api/jobs/${jobId}/events`);
    state.eventSource = source;

    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      $("bar").style.width = `${Math.round((data.progress || 0) * 100)}%`;
      $("message").textContent = data.message || "";
      $("logs").textContent = (data.logs || []).join("\n");
      $("logs").scrollTop = $("logs").scrollHeight;

      if (data.status === "done") {
        badge.textContent = "terminé";
        badge.className = "badge done";
        source.close();
        $("btn-start").disabled = false;
        renderResults(jobId, data.result);
      } else if (data.status === "error") {
        badge.textContent = "erreur";
        badge.className = "badge error";
        source.close();
        $("btn-start").disabled = false;
        $("message").textContent = data.error || "Erreur";
      } else if (data.status === "cancelled") {
        badge.textContent = "annulé";
        badge.className = "badge";
        source.close();
        $("btn-start").disabled = false;
      }
    };
    source.onerror = () => source.close();
  }

  // ---------- Résultats ----------
  function renderResults(jobId, result) {
    const box = $("results");
    box.innerHTML = "";
    if (!result || !result.clips || result.clips.length === 0) {
      box.innerHTML = '<div class="empty">Aucun extrait produit.</div>';
      return;
    }
    result.clips.forEach((clip) => {
      const card = document.createElement("div");
      card.className = "clip";
      const hasFile = Boolean(clip.path);
      const source = hasFile ? `/api/jobs/${jobId}/clips/${clip.index}` : "";
      card.innerHTML = `
        ${hasFile ? `<video controls preload="metadata" src="${source}"></video>` : ""}
        <div class="meta">
          <div class="title">${escapeHtml(clip.title || "Extrait")}</div>
          <div class="sub">#${clip.index} · ${formatTime(clip.start)} → ${formatTime(clip.end)} · ${Math.round(clip.duration)} s</div>
          ${clip.hook ? `<div class="hook">🪝 ${escapeHtml(clip.hook)}</div>` : ""}
          <div class="actions">
            <a href="/api/jobs/${jobId}/report" target="_blank">Rapport</a>
            ${hasFile ? `<a href="${source}" download>Télécharger</a>` : ""}
          </div>
        </div>`;
      box.appendChild(card);
    });

    const best = document.createElement("div");
    best.className = "clip";
    best.innerHTML = `
      <video controls preload="metadata" src="/api/jobs/${jobId}/best-of"></video>
      <div class="meta">
        <div class="title">Best-of</div>
        <div class="sub">Tous les extraits concaténés</div>
        <div class="actions"><a href="/api/jobs/${jobId}/best-of" download>Télécharger</a></div>
      </div>`;
    box.appendChild(best);
  }

  function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }

  function escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  loadHealth();
  loadStyles();
  setInterval(loadHealth, 30000);
})();
