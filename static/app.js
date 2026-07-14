const inputPath = document.getElementById("input-path");
const outputDir = document.getElementById("output-dir");
const fileCount = document.getElementById("file-count");
const statusText = document.getElementById("status-text");
const progressTrack = document.getElementById("progress-track");
const progressFill = document.getElementById("progress-fill");
const logSection = document.getElementById("log-section");
const logPanel = document.getElementById("log-panel");
const convertBtn = document.getElementById("convert-btn");
const openOutputBtn = document.getElementById("open-output-btn");
const openOutputModal = document.getElementById("open-output-modal");
const resetAllModal = document.getElementById("reset-all-modal");
const copyLogBtn = document.getElementById("copy-log");
const debugMode = document.getElementById("debug-mode");
const prefNormalizeDashes = document.getElementById("pref-normalize-dashes");
const prefNormalizeArrows = document.getElementById("pref-normalize-arrows");
const prefPlainInlineCode = document.getElementById("pref-plain-inline-code");
const prefCombineMarkdown = document.getElementById("pref-combine-markdown");
const exportOptions = document.getElementById("export-options");
const subtitle = document.getElementById("subtitle");
const inputLabel = document.getElementById("input-label");
const modeInputs = document.querySelectorAll('input[name="conversion-mode"]');
const sourceInputs = document.querySelectorAll('input[name="input-source"]');
const completionBanner = document.getElementById("completion-banner");
const completionTitle = document.getElementById("completion-title");
const completionMessage = document.getElementById("completion-message");
const completionOutput = document.getElementById("completion-output");
const completionIcon = document.getElementById("completion-icon");
const doneSound = document.getElementById("done-sound");
const confettiCanvas = document.getElementById("confetti-canvas");
const engineStatusActive = document.getElementById("engine-status-active");
const engineActiveLabel = document.getElementById("engine-active-label");
const engineActiveDetail = document.getElementById("engine-active-detail");
const enginePandocValue = document.getElementById("engine-pandoc-value");
const enginePdfValue = document.getElementById("engine-pdf-value");
const enginePandocPill = document.getElementById("engine-pandoc-pill");
const enginePdfPill = document.getElementById("engine-pdf-pill");
const themeToggle = document.getElementById("theme-toggle");
const themeToggleLabel = document.getElementById("theme-toggle-label");
const faviconSvg = document.getElementById("favicon-svg");
const metaThemeColor = document.getElementById("meta-theme-color");

const THEME_STORAGE_KEY = "md-converter-theme";
const PREF_DASHES_STORAGE_KEY = "md-converter-pref-normalize-dashes";
const PREF_ARROWS_STORAGE_KEY = "md-converter-pref-normalize-arrows";
const PREF_PLAIN_INLINE_CODE_STORAGE_KEY = "md-converter-pref-plain-inline-code";
const PREF_COMBINE_MARKDOWN_STORAGE_KEY = "md-converter-pref-combine-markdown";

const MODE_COPY = {
  to_markdown: {
    subtitle: "Convert DOCX and PDF files to Markdown",
    inputFolderBrowse: "Select input folder (DOCX/PDF files)",
    inputFileBrowse: "Select a DOCX or PDF file",
    outputBrowse: "Select output folder for Markdown files",
  },
  to_docx: {
    subtitle: "Convert Markdown files to DOCX",
    inputFolderBrowse: "Select input folder (Markdown files)",
    inputFileBrowse: "Select a Markdown file",
    outputBrowse: "Select output folder for DOCX files",
  },
  to_pdf: {
    subtitle: "Convert Markdown files to PDF",
    inputFolderBrowse: "Select input folder (Markdown files)",
    inputFileBrowse: "Select a Markdown file",
    outputBrowse: "Select output folder for PDF files",
  },
  to_docx_pdf: {
    subtitle: "Convert Markdown files to DOCX and PDF",
    inputFolderBrowse: "Select input folder (Markdown files)",
    inputFileBrowse: "Select a Markdown file",
    outputBrowse: "Select output folder for DOCX and PDF files",
  },
};

let eventSource = null;
let scanTimer = null;
let lastSuggestedOutput = "";
let lastOutputPath = "";
let confettiFrame = null;
let conversionComplete = false;
let logBuffer = [];

function getTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function updateFavicon(theme) {
  if (faviconSvg) {
    faviconSvg.href = theme === "dark" ? "/static/favicon-dark.svg" : "/static/favicon-light.svg";
  }
  if (metaThemeColor) {
    metaThemeColor.setAttribute("content", theme === "dark" ? "#0f1419" : "#f4f6f8");
  }
}

function updateThemeToggle(theme) {
  const isDark = theme === "dark";
  themeToggleLabel.textContent = isDark ? "Light mode" : "Dark mode";
  themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
}

function setTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", nextTheme);
  localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  updateFavicon(nextTheme);
  updateThemeToggle(nextTheme);
}

function toggleTheme() {
  setTheme(getTheme() === "dark" ? "light" : "dark");
}

function readStoredBoolean(key, defaultValue = true) {
  const stored = localStorage.getItem(key);
  if (stored === null) {
    return defaultValue;
  }
  return stored === "true";
}

function saveTextPreferences() {
  localStorage.setItem(PREF_DASHES_STORAGE_KEY, String(prefNormalizeDashes.checked));
  localStorage.setItem(PREF_ARROWS_STORAGE_KEY, String(prefNormalizeArrows.checked));
  localStorage.setItem(PREF_PLAIN_INLINE_CODE_STORAGE_KEY, String(prefPlainInlineCode.checked));
  localStorage.setItem(PREF_COMBINE_MARKDOWN_STORAGE_KEY, String(prefCombineMarkdown.checked));
}

function loadTextPreferences() {
  prefNormalizeDashes.checked = readStoredBoolean(PREF_DASHES_STORAGE_KEY, true);
  prefNormalizeArrows.checked = readStoredBoolean(PREF_ARROWS_STORAGE_KEY, true);
  prefPlainInlineCode.checked = readStoredBoolean(PREF_PLAIN_INLINE_CODE_STORAGE_KEY, false);
  prefCombineMarkdown.checked = readStoredBoolean(PREF_COMBINE_MARKDOWN_STORAGE_KEY, false);
}

function getTextPreferences() {
  return {
    normalize_dashes: prefNormalizeDashes.checked,
    normalize_arrows: prefNormalizeArrows.checked,
    plain_inline_code: prefPlainInlineCode.checked,
    combine_into_single_file: prefCombineMarkdown.checked,
  };
}

function getSelectedMode() {
  const selected = document.querySelector('input[name="conversion-mode"]:checked');
  return selected ? selected.value : "to_markdown";
}

function setConversionMode(mode) {
  const target = document.querySelector(`input[name="conversion-mode"][value="${mode}"]`);
  if (target) {
    target.checked = true;
    updateModeCopy();
  }
}

function getInputSource() {
  const selected = document.querySelector('input[name="input-source"]:checked');
  return selected ? selected.value : "file";
}

function setInputSource(source) {
  const target = document.querySelector(`input[name="input-source"][value="${source}"]`);
  if (target) {
    target.checked = true;
  }
}

function isSingleFileMode() {
  return getInputSource() === "file";
}

function updateModeCopy() {
  const mode = getSelectedMode();
  const copy = MODE_COPY[mode];
  subtitle.textContent = copy.subtitle;
  inputLabel.textContent = isSingleFileMode() ? "Input file" : "Input folder";
  inputPath.placeholder = isSingleFileMode() ? "/path/to/document.pdf" : "/path/to/documents";
  exportOptions.classList.toggle("hidden", mode !== "to_markdown");
  loadEngineStatus();
}

function setEnginePillState(pill, state) {
  pill.classList.remove("pill-ready", "pill-partial", "pill-missing");
  if (state) {
    pill.classList.add(state);
  }
}

function updateEngineStatusUI(data) {
  const active = data.active;
  engineStatusActive.classList.remove("status-ready", "status-partial", "status-fallback");
  engineStatusActive.classList.add(`status-${active.status}`);

  const willUsePrefix =
    active.status === "ready" ? "Will use: " : active.status === "partial" ? "Will use: " : "Will use: ";
  engineActiveLabel.textContent = `${willUsePrefix}${active.label}`;
  engineActiveDetail.textContent = active.detail;

  if (data.pandoc.installed) {
    enginePandocValue.textContent = data.pandoc.version || "Installed";
    setEnginePillState(enginePandocPill, "pill-ready");
  } else {
    enginePandocValue.textContent = "Not installed";
    setEnginePillState(enginePandocPill, "pill-missing");
  }

  if (data.pdf_engine.installed) {
    enginePdfValue.textContent = data.pdf_engine.name;
    setEnginePillState(enginePdfPill, "pill-ready");
  } else if (data.pandoc.installed) {
    enginePdfValue.textContent = "Not found (partial PDF export)";
    setEnginePillState(enginePdfPill, "pill-partial");
  } else {
    enginePdfValue.textContent = "Not found";
    setEnginePillState(enginePdfPill, "pill-missing");
  }
}

async function loadEngineStatus() {
  try {
    const data = await api(`/api/engine-status?mode=${encodeURIComponent(getSelectedMode())}`);
    updateEngineStatusUI(data);
  } catch (error) {
    engineActiveLabel.textContent = "Could not check engine status";
    engineActiveDetail.textContent = error.message;
    engineStatusActive.classList.remove("status-ready", "status-partial");
    engineStatusActive.classList.add("status-fallback");
  }
}

function updateLogVisibility() {
  logSection.classList.toggle("hidden", !debugMode.checked);
  if (debugMode.checked) {
    renderLogPanel();
  }
}

function renderLogPanel() {
  logPanel.textContent = logBuffer.join("\n");
  logPanel.scrollTop = logPanel.scrollHeight;
}

function appendLog(message, isError = false) {
  logBuffer.push(message);
  if (!debugMode.checked) {
    return;
  }
  const line = document.createElement("div");
  line.textContent = message;
  if (isError) {
    line.classList.add("log-line-error");
  }
  logPanel.appendChild(line);
  logPanel.scrollTop = logPanel.scrollHeight;
}

function reportIssue(message) {
  fileCount.textContent = message;
  statusText.textContent = message;
  statusText.classList.add("is-error");
  appendLog(message, true);
}

async function copyLogToClipboard() {
  const text = logBuffer.length ? logBuffer.join("\n") : logPanel.textContent.trim();
  if (!text) {
    reportIssue("No log content to copy.");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    const originalLabel = copyLogBtn.textContent;
    copyLogBtn.textContent = "Copied!";
    setTimeout(() => {
      copyLogBtn.textContent = originalLabel;
    }, 1500);
  } catch (error) {
    reportIssue("Could not copy log to clipboard.");
  }
}

function setProgressActive(active) {
  progressTrack.classList.toggle("is-active", active);
  if (active) {
    progressFill.classList.remove("is-complete", "is-error");
    progressTrack.classList.remove("is-complete-error");
  }
  statusText.classList.toggle("is-working", active);
}

function setProgressComplete(status) {
  progressFill.classList.remove("is-complete", "is-error");
  progressTrack.classList.remove("is-complete-error");
  progressFill.classList.add("is-complete");

  if (status === "partial") {
    progressFill.classList.add("is-error");
    progressTrack.classList.add("is-complete-error");
  }
}

function setProgress(percent) {
  progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function resetProgressVisuals() {
  progressFill.classList.remove("is-complete", "is-error");
  progressTrack.classList.remove("is-active", "is-complete-error");
  progressFill.style.width = "0%";
  statusText.classList.remove("is-success", "is-error", "is-working");
  statusText.textContent = "Ready";
}

function getOutputPath() {
  return (lastOutputPath || outputDir.value).trim();
}

function updateOpenOutputButtons() {
  const canOpen = conversionComplete && Boolean(getOutputPath());
  openOutputBtn.disabled = !canOpen;
  openOutputModal.disabled = !canOpen;
}

async function openOutputFolder(folderPath = getOutputPath()) {
  if (!folderPath) {
    reportIssue("No output folder selected yet.");
    return;
  }

  try {
    await api("/api/open-folder", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    });
  } catch (error) {
    reportIssue(error.message);
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function pickFolder(title) {
  const data = await api("/api/pick-folder", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  return data.path || "";
}

async function pickFile(title) {
  const data = await api("/api/pick-file", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  return data.path || "";
}

async function scanInput() {
  const path = inputPath.value.trim();
  if (!path) {
    fileCount.textContent = isSingleFileMode() ? "No input file selected" : "No input folder selected";
    return;
  }

  try {
    const data = await api("/api/scan", {
      method: "POST",
      body: JSON.stringify({
        input_path: path,
        mode: getSelectedMode(),
      }),
    });

    if (data.suggested_mode) {
      setConversionMode(data.suggested_mode);
    }

    fileCount.textContent = data.message;

    const currentOutput = outputDir.value.trim();
    if (!currentOutput || currentOutput === lastSuggestedOutput || data.mode_changed) {
      outputDir.value = data.suggested_output;
      lastSuggestedOutput = data.suggested_output;
    }
  } catch (error) {
    fileCount.textContent = error.message;
  }
}

function scheduleScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(scanInput, 300);
}

function playDoneSound() {
  try {
    doneSound.currentTime = 0;
    const playPromise = doneSound.play();
    if (playPromise) {
      playPromise.catch(() => {});
    }
  } catch (error) {
    // Ignore autoplay restrictions.
  }
}

function launchConfetti() {
  const ctx = confettiCanvas.getContext("2d");
  const pieces = Array.from({ length: 120 }, () => ({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight - window.innerHeight,
    size: 6 + Math.random() * 8,
    tilt: Math.random() * Math.PI,
    speed: 2 + Math.random() * 4,
    spin: 0.04 + Math.random() * 0.08,
    color: ["#2563eb", "#22c55e", "#f59e0b", "#ec4899", "#8b5cf6"][Math.floor(Math.random() * 5)],
  }));

  confettiCanvas.width = window.innerWidth;
  confettiCanvas.height = window.innerHeight;

  let frame = 0;
  const maxFrames = 160;

  function draw() {
    ctx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);
    pieces.forEach((piece) => {
      piece.y += piece.speed;
      piece.x += Math.sin(frame * piece.spin) * 1.5;
      piece.tilt += piece.spin;
      ctx.save();
      ctx.translate(piece.x, piece.y);
      ctx.rotate(piece.tilt);
      ctx.fillStyle = piece.color;
      ctx.fillRect(-piece.size / 2, -piece.size / 2, piece.size, piece.size * 0.6);
      ctx.restore();
    });
    frame += 1;
    if (frame < maxFrames) {
      confettiFrame = requestAnimationFrame(draw);
    } else {
      ctx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);
      confettiFrame = null;
    }
  }

  if (confettiFrame) {
    cancelAnimationFrame(confettiFrame);
  }
  draw();
}

function showCompletion(payload) {
  const isSuccess = payload.status === "success";
  const isPartial = payload.status === "partial";

  completionTitle.textContent = isSuccess
    ? "All done!"
    : isPartial
      ? "Finished with some errors"
      : "Conversion finished";

  completionMessage.textContent = payload.message;
  completionOutput.textContent = payload.output_path
    ? `Saved to: ${payload.output_path}`
    : "";

  completionIcon.textContent = isSuccess ? "✓" : isPartial ? "!" : "•";
  completionIcon.classList.toggle("partial", isPartial);

  completionBanner.classList.remove("hidden");

  if (isSuccess || isPartial) {
    playDoneSound();
  }
  if (isSuccess) {
    launchConfetti();
  }
}

function hideCompletion() {
  completionBanner.classList.add("hidden");
}

function resetAll() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  if (confettiFrame) {
    cancelAnimationFrame(confettiFrame);
    confettiFrame = null;
  }

  const ctx = confettiCanvas.getContext("2d");
  ctx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);

  setConversionMode("to_markdown");
  setInputSource("file");
  inputPath.value = "";
  outputDir.value = "";
  debugMode.checked = false;
  prefNormalizeDashes.checked = true;
  prefNormalizeArrows.checked = true;
  prefPlainInlineCode.checked = false;
  prefCombineMarkdown.checked = false;
  saveTextPreferences();
  lastSuggestedOutput = "";
  lastOutputPath = "";
  conversionComplete = false;
  logBuffer = [];
  convertBtn.disabled = false;

  logPanel.textContent = "";
  hideCompletion();
  resetProgressVisuals();
  updateModeCopy();
  updateLogVisibility();

  fileCount.textContent = isSingleFileMode() ? "No input file selected" : "No input folder selected";
  updateOpenOutputButtons();
}

function connectEvents() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource("/api/events");

  eventSource.onmessage = (event) => {
    const payload = JSON.parse(event.data);

    if (payload.type === "log") {
      appendLog(payload.message, payload.level === "ERROR" || payload.level === "CRITICAL");
    }

    if (payload.type === "status") {
      statusText.textContent = payload.message;
    }

    if (payload.type === "progress") {
      setProgress(payload.percent);
    }

    if (payload.type === "done") {
      convertBtn.disabled = false;
      setProgressActive(false);
      setProgress(100);
      setProgressComplete(payload.status);

      if (payload.status === "success") {
        statusText.textContent = "Conversion complete!";
        statusText.classList.add("is-success");
      } else if (payload.status === "partial") {
        statusText.textContent = "Finished with some errors";
        statusText.classList.add("is-error");
      } else {
        statusText.textContent = payload.message;
      }

      conversionComplete = true;
      if (payload.output_path) {
        lastOutputPath = payload.output_path;
      }
      updateOpenOutputButtons();
      showCompletion(payload);
      eventSource.close();
      eventSource = null;
    }

    if (payload.type === "error") {
      convertBtn.disabled = false;
      setProgressActive(false);
      conversionComplete = false;
      updateOpenOutputButtons();
      reportIssue(payload.message);
      eventSource.close();
      eventSource = null;
    }
  };

  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  };
}

async function startConversion() {
  const inputValue = inputPath.value.trim();
  const outputValue = outputDir.value.trim();

  if (!inputValue) {
    reportIssue(
      isSingleFileMode() ? "Please select an input file." : "Please select an input folder."
    );
    return;
  }

  await scanInput();

  hideCompletion();
  resetProgressVisuals();
  conversionComplete = false;
  updateOpenOutputButtons();
  convertBtn.disabled = true;
  setProgress(0);
  setProgressActive(true);
  statusText.textContent = "Starting…";
  connectEvents();

  try {
    await api("/api/convert", {
      method: "POST",
      body: JSON.stringify({
        input_path: inputValue,
        output_dir: outputValue,
        mode: getSelectedMode(),
        debug: debugMode.checked,
        ...getTextPreferences(),
      }),
    });
  } catch (error) {
    convertBtn.disabled = false;
    setProgressActive(false);
    conversionComplete = false;
    updateOpenOutputButtons();
    reportIssue(error.message);
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }
}

document.getElementById("browse-input").addEventListener("click", async () => {
  try {
    const copy = MODE_COPY[getSelectedMode()];
    const title = isSingleFileMode() ? copy.inputFileBrowse : copy.inputFolderBrowse;
    const path = isSingleFileMode() ? await pickFile(title) : await pickFolder(title);
    if (path) {
      inputPath.value = path;
      await scanInput();
    }
  } catch (error) {
    reportIssue(error.message);
  }
});

document.getElementById("browse-output").addEventListener("click", async () => {
  try {
    const copy = MODE_COPY[getSelectedMode()];
    const path = await pickFolder(copy.outputBrowse);
    if (path) {
      outputDir.value = path;
      lastSuggestedOutput = path;
    }
  } catch (error) {
    reportIssue(error.message);
  }
});

modeInputs.forEach((input) => {
  input.addEventListener("change", () => {
    updateModeCopy();
    scheduleScan();
  });
});

sourceInputs.forEach((input) => {
  input.addEventListener("change", () => {
    inputPath.value = "";
    fileCount.textContent = isSingleFileMode() ? "No input file selected" : "No input folder selected";
    updateModeCopy();
  });
});

debugMode.addEventListener("change", updateLogVisibility);
prefNormalizeDashes.addEventListener("change", saveTextPreferences);
prefNormalizeArrows.addEventListener("change", saveTextPreferences);
prefPlainInlineCode.addEventListener("change", saveTextPreferences);
prefCombineMarkdown.addEventListener("change", saveTextPreferences);
document.getElementById("reset-btn").addEventListener("click", resetAll);
if (resetAllModal) {
  resetAllModal.addEventListener("click", resetAll);
}
document.getElementById("open-output-btn").addEventListener("click", () => openOutputFolder());
document.getElementById("open-output-modal").addEventListener("click", () => openOutputFolder());
themeToggle.addEventListener("click", toggleTheme);
copyLogBtn.addEventListener("click", copyLogToClipboard);

inputPath.addEventListener("input", scheduleScan);
outputDir.addEventListener("input", updateOpenOutputButtons);
convertBtn.addEventListener("click", startConversion);

document.getElementById("clear-log").addEventListener("click", () => {
  logBuffer = [];
  logPanel.textContent = "";
});

document.getElementById("dismiss-completion").addEventListener("click", hideCompletion);

completionBanner.addEventListener("click", (event) => {
  if (event.target === completionBanner) {
    hideCompletion();
  }
});

updateModeCopy();
updateLogVisibility();
loadTextPreferences();
updateOpenOutputButtons();
updateFavicon(getTheme());
updateThemeToggle(getTheme());
loadEngineStatus();
