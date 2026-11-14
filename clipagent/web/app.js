/* clipagent — interface web (vanilla JS, zéro dépendance). */
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { mode: "url", jobId: null, source: null, startedAt: null, timer: null };

  /* ================= Utilitaires ================= */
  const escapeHtml = (text) =>
    String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }

  function formatBytes(bytes) {
    const units = ["o", "Ko", "Mo", "Go"];
    let value = bytes || 0;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
    return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function toast(title, message, kind = "") {
    const box = document.createElement("div");
    box.className = `toast ${kind}`;
    box.innerHTML = `<b>${escapeHtml(title)}</b>${escapeHtml(message || "")}`;
    $("toasts").appendChild(box);
    setTimeout(() => {
      box.style.transition = "opacity .3s, transform .3s";
      box.style.opacity = "0";
      box.style.transform = "translateY(8px)";
      setTimeout(() => box.remove(), 320);
    }, kind === "error" ? 7000 : 4200);
  }

  /* ================= Thème ================= */
  const savedTheme = localStorage.getItem("clipagent-theme");
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;
  const syncThemeButton = () => {
    $("btn-theme").textContent = document.documentElement.dataset.theme === "light" ? "☀️" : "🌙";
  };
  syncThemeButton();
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("clipagent-theme", next);
    syncThemeButton();
  });

  /* ================= Santé / fournisseur ================= */
  async function loadHealth() {
    const chips = $("health-chips");
    try {
      // Les pastilles s'affichent tout de suite : le test du fournisseur LLM
      // peut prendre plusieurs secondes (il est fait séparément).
      const health = await fetch("/api/health").then((r) => r.json());
      const items = [
        { key: "ia", label: "IA", on: health.llm },
        { key: "ffmpeg", label: "ffmpeg", on: health.ffmpeg },
        { key: "whisper", label: "Whisper", on: health.whisper },
        { key: "opencv", label: "OpenCV", on: health.opencv },
        { key: "model", label: "modèle", on: null },
      ];
      chips.innerHTML = items
        .map((i) => `<span class="chip ${i.on === null ? "" : i.on ? "on" : "off"}" data-key="${i.key}"><i></i>${escapeHtml(i.label)}</span>`)
        .join("");
      chips.title = `${health.free_disk_mb} Mo libres`;

      fetch("/api/provider")
        .then((r) => r.json())
        .then((provider) => {
          const chip = chips.querySelector('[data-key="model"]');
          if (!chip) return;
          const label = provider.model ? provider.model.split("/").pop().slice(0, 18) : "modèle";
          chip.innerHTML = `<i></i>${escapeHtml(label)}`;
          chip.className = `chip ${provider.reachable ? "on" : "off"}`;
          chip.title = `${provider.base_url || ""} — ${provider.reachable ? "joignable" : provider.error || "indisponible"}`;
        })
        .catch(() => {});
    } catch (err) {
      chips.innerHTML = '<span class="chip off"><i></i>API injoignable</span>';
    }
  }

  /* ================= Styles ================= */
  async function loadStyles() {
    try {
      const data = await (await fetch("/api/styles")).json();
      const select = $("input-style");
      select.innerHTML = "";
      data.styles.forEach((style) => {
        const option = document.createElement("option");
        option.value = style.name;
        option.textContent = style.label;
        option.title = style.description;
        select.appendChild(option);
      });
      select.value = "streamer";
      select.addEventListener("change", () => {
        const chosen = data.styles.find((s) => s.name === select.value);
        if (chosen) toast("Style sélectionné", chosen.description);
      });
    } catch (err) {
      console.error(err);
    }
  }

  /* ================= Source ================= */
  document.querySelectorAll("#source-tabs button").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#source-tabs button").forEach((t) => t.setAttribute("aria-selected", "false"));
      tab.setAttribute("aria-selected", "true");
      state.mode = tab.dataset.mode;
      $("field-url").classList.toggle("hidden", state.mode !== "url");
      $("field-file").classList.toggle("hidden", state.mode !== "file");
      $("field-transcript").classList.toggle("hidden", state.mode !== "transcript");
    });
  });

  function wireDrop(dropId, inputId, labelId) {
    const drop = $(dropId);
    const input = $(inputId);
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      if (e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        input.dispatchEvent(new Event("change"));
      }
    });
    input.addEventListener("change", () => {
      const file = input.files[0];
      const label = $(labelId);
      if (!label) return;
      label.querySelector("strong").textContent = file ? file.name : "Déposer un fichier ici";
      label.querySelector("span").textContent = file
        ? `${formatBytes(file.size)} · prêt`
        : "ou cliquer pour parcourir";
    });
  }

  wireDrop("drop-file", "input-file", "drop-file");
  wireDrop("drop-transcript", "input-transcript", "drop-transcript");

  /* ================= Upload ================= */
  async function uploadFile(file) {
    const data = new FormData();
    data.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: data });
    if (!res.ok) throw new Error("Téléversement impossible");
    return (await res.json()).path;
  }

  /* ================= Lancement ================= */
  async function start() {
    const button = $("btn-start");
    const hint = $("start-hint");
    hint.textContent = "";
    hint.style.color = "";

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
      button.textContent = "Préparation…";
      hint.textContent = "Préparation de la source…";

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
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Erreur ${res.status}`);
      }
      const job = await res.json();
      state.jobId = job.id;
      state.startedAt = Date.now();
      location.hash = `job=${job.id}`;
      showSkeletons();
      watch(job.id);
      toast("Tâche lancée", `Identifiant ${job.id.slice(0, 8)}`, "ok");
    } catch (err) {
      hint.textContent = err.message;
      hint.style.color = "var(--danger)";
      toast("Échec du lancement", err.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "▶ Lancer le clipping";
    }
  }

  $("btn-start").addEventListener("click", start);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      start();
    }
  });

  /* ================= Suivi (SSE) ================= */
  function watch(jobId) {
    if (state.source) state.source.close();
    const badge = $("job-badge");
    badge.textContent = jobId.slice(0, 8);
    badge.className = "chip on";
    $("pulse").hidden = false;
    $("metrics").hidden = false;
    $("m-steps").textContent = "1";

    const source = new EventSource(`/api/jobs/${jobId}/events`);
    state.source = source;

    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      $("bar").style.width = `${Math.round((data.progress || 0) * 100)}%`;
      $("message").textContent = data.message || "";
      $("logs").textContent = (data.logs || []).join("\n") || "—";
      $("logs").scrollTop = $("logs").scrollHeight;

      const elapsed = state.startedAt ? (Date.now() - state.startedAt) / 1000 : 0;
      $("m-elapsed").textContent = formatTime(elapsed);
      $("m-steps").textContent = String((data.logs || []).length);

      if (data.status === "done") {
        badge.textContent = "terminé";
        badge.className = "chip on";
        $("pulse").hidden = true;
        source.close();
        renderResults(jobId, data.result);
        loadHistory();
        toast("Clipping terminé", `${(data.result?.clips || []).length} extrait(s) prêt(s)`, "ok");
        fetch(`/api/jobs/${jobId}/usage`)
          .then((r) => r.json())
          .then((usage) => { $("m-size").textContent = `${usage.disk_mb} Mo`; })
          .catch(() => {});
      } else if (data.status === "error") {
        badge.textContent = "erreur";
        badge.className = "chip off";
        $("pulse").hidden = true;
        source.close();
        $("message").textContent = data.error || "Erreur";
        toast("Échec du clipping", data.error || "", "error");
      } else if (data.status === "cancelled") {
        badge.textContent = "annulé";
        badge.className = "chip";
        $("pulse").hidden = true;
        source.close();
      }
    };
    source.onerror = () => {
      $("pulse").hidden = true;
      source.close();
    };
  }

  /* ================= Résultats ================= */
  function showSkeletons() {
    $("results").innerHTML = Array.from({ length: 4 })
      .map(() => '<div class="skeleton sk-card"></div>')
      .join("");
  }

  function renderResults(jobId, result) {
    const box = $("results");
    box.innerHTML = "";
    $("m-clips").textContent = String((result?.clips || []).length);

    if (!result || !result.clips || result.clips.length === 0) {
      box.innerHTML = '<div class="empty">Aucun extrait produit.</div>';
      return;
    }

    result.clips.forEach((clip, index) => {
      const hasFile = Boolean(clip.path);
      const source = hasFile ? `/api/jobs/${jobId}/clips/${clip.index}` : "";
      const card = document.createElement("div");
      card.className = "clip";
      card.style.animationDelay = `${index * 55}ms`;
      card.innerHTML = `
        <div class="thumb">
          ${hasFile ? `<video controls preload="metadata" playsinline src="${source}"></video>` : ""}
          <span class="badge-top">#${clip.index}</span>
          <span class="dur">${Math.round(clip.duration)} s</span>
        </div>
        <div class="meta">
          <div class="title">${escapeHtml(clip.title || "Extrait")}</div>
          <div class="sub">${formatTime(clip.start)} → ${formatTime(clip.end)} · score ${(clip.score ?? 0).toFixed(2)}</div>
          ${clip.hook ? `<div class="hook">🪝 ${escapeHtml(clip.hook)}</div>` : ""}
          <div class="actions">
            <a href="/api/jobs/${jobId}/report" target="_blank" rel="noopener">Rapport</a>
            ${hasFile ? `<a href="${source}" download>Télécharger</a>` : ""}
          </div>
        </div>`;
      box.appendChild(card);
    });

    const best = document.createElement("div");
    best.className = "best";
    best.innerHTML = `
      <div>
        <b>Best-of — tous les extraits</b>
        <span>${result.clips.length} clips concaténés en une seule vidéo</span>
      </div>
      <div class="actions">
        <a class="ghost" href="/api/jobs/${jobId}/report" target="_blank" rel="noopener">Rapport</a>
        <a class="ghost" href="/api/jobs/${jobId}/best-of" download>Télécharger</a>
      </div>`;
    box.appendChild(best);

    $("btn-copy-report").hidden = false;
    $("btn-download-all").hidden = false;
    $("btn-download-all").onclick = () => {
      result.clips.forEach((clip, index) => {
        setTimeout(() => {
          const link = document.createElement("a");
          link.href = `/api/jobs/${jobId}/clips/${clip.index}`;
          link.download = "";
          document.body.appendChild(link);
          link.click();
          link.remove();
        }, index * 350);
      });
    };
  }

  $("btn-copy-report").addEventListener("click", async () => {
    if (!state.jobId) return;
    try {
      const text = await (await fetch(`/api/jobs/${state.jobId}/report`)).text();
      await navigator.clipboard.writeText(text);
      toast("Rapport copié", "Presse-papiers mis à jour", "ok");
    } catch (err) {
      toast("Copie impossible", String(err.message || err), "error");
    }
  });

  /* ================= Historique ================= */
  async function loadHistory() {
    try {
      const jobs = await (await fetch("/api/jobs")).json();
      const box = $("history");
      if (!jobs.length) {
        box.innerHTML = '<div class="empty" style="padding:18px;">Aucune tâche.</div>';
        return;
      }
      box.innerHTML = "";
      jobs.slice(0, 12).forEach((job) => {
        const button = document.createElement("button");
        const kind = job.status === "done" ? "terminé" : job.status === "error" ? "erreur" : job.status;
        button.innerHTML = `<span class="tag">${escapeHtml(kind)}</span>
          <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(job.message || job.id)}</span>
          <span style="color:var(--muted)">${formatTime(new Date(job.created_at).getTime() / 1000)}</span>`;
        button.addEventListener("click", () => openJob(job.id));
        box.appendChild(button);
      });
    } catch (err) {
      console.error(err);
    }
  }

  async function openJob(jobId) {
    try {
      const job = await (await fetch(`/api/jobs/${jobId}`)).json();
      state.jobId = jobId;
      state.startedAt = new Date(job.created_at).getTime();
      location.hash = `job=${jobId}`;
      $("bar").style.width = `${Math.round((job.progress || 0) * 100)}%`;
      $("message").textContent = job.message || "";
      $("logs").textContent = (job.logs || []).join("\n") || "—";
      $("metrics").hidden = false;
      $("pulse").hidden = job.status !== "running";
      $("job-badge").textContent = jobId.slice(0, 8);
      if (job.result) renderResults(jobId, job.result);
      if (job.status === "running") watch(jobId);
    } catch (err) {
      toast("Tâche introuvable", String(err.message || err), "error");
    }
  }

  $("btn-refresh-history").addEventListener("click", loadHistory);

  /* ================= Démarrage ================= */
  loadHealth();
  loadStyles();
  loadHistory();
  setInterval(loadHealth, 30000);

  // Hook d'automatisation (tests e2e, pilotage depuis la console).
  window.clipagent = { start, watch, openJob, renderResults, loadHistory, toast };

  const hashJob = (location.hash || "").match(/job=([a-f0-9]+)/i);
  if (hashJob) openJob(hashJob[1]);
})();
