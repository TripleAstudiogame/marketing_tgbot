(function () {
  const vaultInput = document.getElementById("vault-path-input");
  const vaultLabel = document.getElementById("selected-vault-label");
  const modal = document.getElementById("folder-modal");
  const currentInput = document.getElementById("folder-current-path");
  const folderList = document.getElementById("folder-list");
  const driveStrip = document.getElementById("drive-strip");
  const candidates = document.getElementById("vault-candidates");
  let currentPath = vaultInput ? vaultInput.value : "";
  let parentPath = "";

  function setVaultPath(path) {
    if (!path) return;
    vaultInput.value = path;
    vaultLabel.textContent = path;
    document.querySelectorAll(".vault-option").forEach((item) => {
      item.classList.toggle("selected", item.dataset.path === path);
    });
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function renderDrives(drives) {
    driveStrip.innerHTML = "";
    drives.forEach((drive) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "drive-button";
      button.textContent = drive.name;
      button.addEventListener("click", () => loadFolder(drive.path));
      driveStrip.appendChild(button);
    });
  }

  function renderFolders(items) {
    folderList.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = "<strong>Папок не найдено</strong><span>Можно выбрать текущую папку сверху.</span>";
      folderList.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `folder-row ${item.is_candidate ? "candidate" : ""}`;
      button.innerHTML = `
        <span>
          <strong>${item.name}</strong>
          <small>${item.path}</small>
        </span>
        <em>${item.has_obsidian ? ".obsidian" : ""}${item.markdown_count ? ` · ${item.markdown_count} md` : ""}</em>
      `;
      button.addEventListener("dblclick", () => {
        setVaultPath(item.path);
        closeModal();
      });
      button.addEventListener("click", () => loadFolder(item.path));
      folderList.appendChild(button);
    });
  }

  async function loadFolder(path) {
    currentPath = path || "";
    currentInput.value = currentPath || "Диски";
    folderList.innerHTML = '<div class="empty-state"><strong>Загружаю папки...</strong></div>';
    const data = await fetchJson(`/admin/api/filesystem?path=${encodeURIComponent(currentPath)}`);
    currentPath = data.path || "";
    parentPath = data.parent || "";
    currentInput.value = currentPath || "Диски";
    renderDrives(data.drives || []);
    renderFolders(data.directories || []);
  }

  function openModal() {
    modal.hidden = false;
    loadFolder(currentPath || "");
  }

  function closeModal() {
    modal.hidden = true;
  }

  function renderCandidates(items) {
    candidates.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = "<strong>Vault не найден автоматически</strong><span>Открой проводник и выбери папку.</span>";
      candidates.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "vault-option";
      button.dataset.path = item.path;
      button.innerHTML = `
        <span>
          <strong>${item.name}</strong>
          <small>${item.path}</small>
        </span>
        <em>${item.reason}</em>
      `;
      button.addEventListener("click", () => setVaultPath(item.path));
      candidates.appendChild(button);
    });
    setVaultPath(vaultInput.value);
  }

  document.querySelectorAll(".vault-option").forEach((button) => {
    button.addEventListener("click", () => setVaultPath(button.dataset.path));
  });

  document.getElementById("open-folder-browser")?.addEventListener("click", openModal);
  document.getElementById("close-folder-browser")?.addEventListener("click", closeModal);
  document.getElementById("folder-up")?.addEventListener("click", () => {
    if (parentPath) loadFolder(parentPath);
  });
  document.getElementById("select-current-folder")?.addEventListener("click", () => {
    setVaultPath(currentPath);
    closeModal();
  });
  document.getElementById("refresh-vaults")?.addEventListener("click", async () => {
    candidates.innerHTML = '<div class="empty-state"><strong>Ищу vault...</strong><span>Проверяю типичные папки Obsidian.</span></div>';
    const data = await fetchJson("/admin/api/vaults/discover");
    renderCandidates(data.candidates || []);
  });
  modal?.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  if (vaultInput) setVaultPath(vaultInput.value);
})();
