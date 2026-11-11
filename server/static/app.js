/* 抖音视频解析前端逻辑 */
(function () {
  "use strict";

  const els = {
    cookie: document.getElementById("cookie"),
    startBtn: document.getElementById("start-btn"),
    closeBtn: document.getElementById("close-btn"),
    statusDot: document.getElementById("status-dot"),
    statusText: document.getElementById("status-text"),
    statusMode: document.getElementById("status-mode"),
    statusMsg: document.getElementById("status-msg"),
    videoInput: document.getElementById("video-input"),
    resolveBtn: document.getElementById("resolve-btn"),
    resolveBtnText: document.getElementById("resolve-btn-text"),
    result: document.getElementById("result"),
    toast: document.getElementById("toast"),
    themeBtn: document.getElementById("theme-btn"),
    serverHost: document.getElementById("server-host"),
    cookieWarning: document.getElementById("cookie-warning"),
    cookieWarningOk: document.getElementById("cookie-warning-ok"),
  };

  const STATUS_META = {
    idle: { label: "未启动", cls: "idle" },
    launching: { label: "启动中", cls: "busy" },
    ready: { label: "会话就绪", cls: "ok" },
    error: { label: "启动失败", cls: "err" },
  };

  const THEME_KEY = "douyin-parser-theme";
  const SVG_NS = "http://www.w3.org/2000/svg";

  let busy = false;
  // 记录本次页面会话启动时使用的 Cookie，用于判断 Cookie 是否被修改
  let lastStartedCookie = null;
  let toastTimer = null;

  // ------------------------------------------------------------------
  // 工具
  // ------------------------------------------------------------------
  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  async function api(path, options) {
    const opts = options || {};
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    const resp = await fetch("/api" + path, init);
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      data = null;
    }
    if (!resp.ok) {
      let detail = "HTTP " + resp.status;
      if (data && (data.detail || data.message)) {
        detail = data.detail || data.message;
      }
      throw new Error(detail);
    }
    return data;
  }

  function showToast(message, type) {
    els.toast.textContent = message;
    els.toast.className = "toast show " + (type || "ok");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      els.toast.className = "toast";
    }, 4000);
  }

  function setBusy(value) {
    busy = value;
    els.startBtn.disabled = value;
    els.resolveBtn.disabled = value;
    els.resolveBtnText.textContent = value ? "处理中..." : "解析视频";
  }

  function openCookieWarning() {
    if (!els.cookieWarning) return;
    els.cookieWarning.hidden = false;
    els.cookie.focus();
  }

  function closeCookieWarning() {
    if (els.cookieWarning) els.cookieWarning.hidden = true;
  }

  function ensureCookie() {
    if (els.cookie.value.trim() === "") {
      openCookieWarning();
      return false;
    }
    return true;
  }

  function makeEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function icon(name) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function iconButton(name, label) {
    const btn = makeEl("button", "icon-btn sm");
    btn.type = "button";
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.appendChild(icon(name));
    return btn;
  }

  function iconLink(href, name, label) {
    const link = makeEl("a", "icon-btn sm");
    link.href = href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.setAttribute("aria-label", label);
    link.title = label;
    link.appendChild(icon(name));
    return link;
  }

  function formatDuration(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    const pad = function (n) {
      return String(n).padStart(2, "0");
    };
    return hours > 0
      ? hours + ":" + pad(minutes) + ":" + pad(seconds)
      : pad(minutes) + ":" + pad(seconds);
  }

  function copyText(text) {
    if (!text) return;

    function fallback() {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(area);
      showToast(ok ? "已复制链接" : "复制失败，请手动选择链接", ok ? "ok" : "err");
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showToast("已复制链接", "ok");
      }, fallback);
    } else {
      fallback();
    }
  }

  // ------------------------------------------------------------------
  // 主题
  // ------------------------------------------------------------------
  const root = document.documentElement;
  const mq = window.matchMedia("(prefers-color-scheme: dark)");

  function readTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  function writeTheme(value) {
    try {
      localStorage.setItem(THEME_KEY, value);
    } catch (e) {
      /* 忽略 */
    }
  }

  function effectiveTheme() {
    const attr = root.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") return attr;
    return mq.matches ? "dark" : "light";
  }

  function updateThemeButton() {
    if (!els.themeBtn) return;
    const label =
      effectiveTheme() === "dark" ? "切换到浅色主题" : "切换到深色主题";
    els.themeBtn.setAttribute("aria-label", label);
    els.themeBtn.setAttribute("title", label);
  }

  function initTheme() {
    const stored = readTheme();
    if (stored === "dark" || stored === "light") {
      root.setAttribute("data-theme", stored);
    }
    updateThemeButton();

    if (els.themeBtn) {
      els.themeBtn.addEventListener("click", function () {
        const next = effectiveTheme() === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        writeTheme(next);
        updateThemeButton();
      });
    }

    if (mq.addEventListener) {
      mq.addEventListener("change", updateThemeButton);
    }
  }

  // ------------------------------------------------------------------
  // 状态同步
  // ------------------------------------------------------------------
  function applyStatus(s) {
    if (!s) return;
    const meta = STATUS_META[s.status] || { label: s.status, cls: "idle" };
    els.statusDot.className = "dot " + meta.cls;
    els.statusText.textContent = meta.label;

    if (els.statusMode) {
      els.statusMode.hidden = s.status === "idle";
      els.statusMode.textContent = s.mode === "headless" ? "无头" : "有头";
    }

    els.statusMsg.textContent = s.message || s.error || "";
  }

  async function refreshStatus() {
    try {
      const s = await api("/session");
      applyStatus(s);
      return s;
    } catch (e) {
      return null;
    }
  }

  async function startSession() {
    const cookie = els.cookie.value.trim();
    const s = await api("/session", {
      method: "POST",
      body: { cookie: cookie },
    });
    lastStartedCookie = cookie;
    applyStatus(s);
    return s;
  }

  async function waitForReady(timeoutMs) {
    const deadline = Date.now() + (timeoutMs || 6 * 60 * 1000);
    while (Date.now() < deadline) {
      const s = await refreshStatus();
      if (s) {
        if (s.status === "ready") return s;
        if (s.status === "error") {
          throw new Error(s.error || s.message || "会话启动失败");
        }
        if (s.status === "idle") {
          throw new Error("会话已关闭");
        }
      }
      await sleep(1200);
    }
    throw new Error("等待会话就绪超时");
  }

  // ------------------------------------------------------------------
  // 事件
  // ------------------------------------------------------------------
  async function onStartClick() {
    if (busy) return;
    if (!ensureCookie()) return;
    setBusy(true);
    try {
      await startSession();
      await waitForReady();
      showToast("会话已就绪", "ok");
    } catch (e) {
      showToast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  async function onCloseClick() {
    try {
      const s = await api("/session", { method: "DELETE" });
      applyStatus(s);
      lastStartedCookie = null;
      showToast("会话已关闭", "ok");
    } catch (e) {
      showToast(e.message, "err");
    }
  }

  async function onResolveClick() {
    if (busy) return;
    const input = els.videoInput.value.trim();
    if (!input) {
      showToast("请输入视频链接或 ID", "err");
      return;
    }

    const cookieNow = els.cookie.value.trim();
    const s = await refreshStatus();
    const cookieChanged =
      lastStartedCookie !== null && lastStartedCookie !== cookieNow;
    const needRestart = !s || s.status !== "ready" || cookieChanged;

    if (needRestart && cookieNow === "") {
      openCookieWarning();
      return;
    }

    setBusy(true);
    try {
      if (needRestart) {
        await startSession();
        await waitForReady();
      }

      const data = await api("/resolve", {
        method: "POST",
        body: { input: input },
      });
      renderResult(data);
      showToast("解析成功", "ok");

      if (window.matchMedia("(max-width: 940px)").matches) {
        const reduce = window.matchMedia(
          "(prefers-reduced-motion: reduce)"
        ).matches;
        els.result.scrollIntoView({
          behavior: reduce ? "auto" : "smooth",
          block: "nearest",
        });
      }
    } catch (e) {
      showToast(e.message, "err");
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 结果渲染（只用 textContent，避免注入）
  // ------------------------------------------------------------------
  function metaChip(iconName, text) {
    const chip = makeEl("span", "meta-chip");
    chip.appendChild(icon(iconName));
    chip.appendChild(makeEl("span", null, text));
    return chip;
  }

  function detailsFold(iconName, title, metaText) {
    const fold = makeEl("details", "fold");
    const summary = makeEl("summary");

    const titleEl = makeEl("span", "fold-title");
    titleEl.appendChild(icon(iconName));
    titleEl.appendChild(document.createTextNode(title));
    summary.appendChild(titleEl);

    summary.appendChild(makeEl("span", "fold-meta", metaText));

    const chev = icon("chevron");
    chev.classList.add("chev");
    summary.appendChild(chev);

    fold.appendChild(summary);

    const body = makeEl("div", "fold-body");
    fold.appendChild(body);

    return { element: fold, body: body };
  }

  function renderResult(d) {
    const box = els.result;
    box.innerHTML = "";

    const view = makeEl("div", "view");
    const card = makeEl("article", "video-card");

    // 封面：优先真实封面，失败时回落到渐变封面
    const cover = makeEl("div", "cover");
    cover.setAttribute("aria-hidden", "true");
    cover.appendChild(makeEl("span", "cover-orb orb-a"));
    cover.appendChild(makeEl("span", "cover-orb orb-b"));

    if (d.cover) {
      const img = document.createElement("img");
      img.className = "cover-img";
      img.alt = "";
      img.loading = "lazy";
      img.src = d.cover;
      img.addEventListener("error", function () {
        img.remove();
      });
      cover.appendChild(img);
    }

    const play = makeEl("span", "cover-play");
    const ring = makeEl("span", "cover-play-ring");
    ring.appendChild(icon("play"));
    play.appendChild(ring);
    cover.appendChild(play);

    if (d.duration_ms) {
      cover.appendChild(
        makeEl("span", "cover-duration", formatDuration(d.duration_ms))
      );
    }

    card.appendChild(cover);

    const main = makeEl("div", "video-main");
    main.appendChild(makeEl("h3", "video-title", d.title || "（无标题）"));

    const meta = makeEl("div", "meta-row");
    meta.appendChild(metaChip("user", d.author || "未知作者"));
    if (d.duration_ms) {
      meta.appendChild(metaChip("clock", formatDuration(d.duration_ms)));
    }
    if (d.aweme_id) {
      const idChip = makeEl("span", "meta-chip mono");
      idChip.appendChild(makeEl("span", null, "ID " + d.aweme_id));
      meta.appendChild(idChip);
    }
    main.appendChild(meta);

    if (d.video_url) {
      const encodedUrl = encodeURIComponent(d.video_url);

      const urlRow = makeEl("div", "url-row");
      urlRow.appendChild(makeEl("span", "url-label", "直链"));
      const urlText = makeEl("span", "url-text", d.video_url);
      urlText.title = d.video_url;
      urlRow.appendChild(urlText);

      const copyBtn = iconButton("copy", "复制直链");
      copyBtn.addEventListener("click", function () {
        copyText(d.video_url);
      });
      urlRow.appendChild(copyBtn);

      urlRow.appendChild(
        iconLink("/api/stream?url=" + encodedUrl, "external", "在新窗口打开")
      );
      main.appendChild(urlRow);

      const actions = makeEl("div", "video-actions");
      const filename = d.title || d.aweme_id || "douyin_video";

      const download = makeEl("a", "btn primary btn-sm");
      download.href =
        "/api/download?url=" +
        encodedUrl +
        "&filename=" +
        encodeURIComponent(filename);
      download.appendChild(icon("download"));
      download.appendChild(document.createTextNode("下载视频"));
      actions.appendChild(download);

      const copyOriginal = makeEl("button", "btn ghost btn-sm");
      copyOriginal.type = "button";
      copyOriginal.appendChild(icon("copy"));
      copyOriginal.appendChild(document.createTextNode("复制原始链接"));
      copyOriginal.addEventListener("click", function () {
        copyText(d.video_url);
      });
      actions.appendChild(copyOriginal);

      main.appendChild(actions);
    } else {
      main.appendChild(
        makeEl(
          "p",
          "help",
          "未提取到视频地址（可能是图集作品或需要登录）。"
        )
      );
    }

    card.appendChild(main);
    view.appendChild(card);

    if (d.video_url) {
      const preview = detailsFold(
        "play",
        "在线预览",
        "Range 代理 · 可拖动进度"
      );
      const video = document.createElement("video");
      video.controls = true;
      video.preload = "none";
      video.src = "/api/stream?url=" + encodeURIComponent(d.video_url);
      preview.body.appendChild(video);
      view.appendChild(preview.element);
    }

    const alternatives = (d.video_urls || []).slice(1);
    if (alternatives.length) {
      const alt = detailsFold(
        "layers",
        "备用地址",
        alternatives.length + " 个候选"
      );
      const list = makeEl("ul", "alt-list");

      alternatives.forEach(function (url, index) {
        const li = makeEl("li");
        li.appendChild(
          makeEl("span", "alt-no mono", String(index + 2).padStart(2, "0"))
        );

        const link = makeEl("a", "alt-url", url);
        link.href = "/api/stream?url=" + encodeURIComponent(url);
        link.target = "_blank";
        link.rel = "noreferrer";
        link.title = url;
        li.appendChild(link);

        const dl = makeEl("a", "btn ghost btn-xs", "下载");
        dl.href =
          "/api/download?url=" +
          encodeURIComponent(url) +
          "&filename=" +
          encodeURIComponent((d.title || "douyin_video") + "_" + (index + 2));
        li.appendChild(dl);

        list.appendChild(li);
      });

      alt.body.appendChild(list);
      view.appendChild(alt.element);
    }

    box.appendChild(view);
  }

  // ------------------------------------------------------------------
  // 初始化
  // ------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", async function () {
    initTheme();

    if (els.serverHost) {
      els.serverHost.textContent = location.host || "本地服务";
    }

    els.startBtn.addEventListener("click", onStartClick);
    els.closeBtn.addEventListener("click", onCloseClick);
    els.resolveBtn.addEventListener("click", onResolveClick);
    els.videoInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") onResolveClick();
    });

    if (els.cookieWarningOk) {
      els.cookieWarningOk.addEventListener("click", closeCookieWarning);
    }
    if (els.cookieWarning) {
      els.cookieWarning.addEventListener("click", function (e) {
        if (e.target === els.cookieWarning) closeCookieWarning();
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeCookieWarning();
    });

    await refreshStatus();
  });
})();
