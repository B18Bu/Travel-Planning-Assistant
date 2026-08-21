(() => {
  const app = document.getElementById("app");
  const intro = document.getElementById("intro");
  const topbar = document.querySelector(".topbar");
  const shell = document.querySelector(".shell");
  const main = document.querySelector(".main");
  const form = document.getElementById("travel-form");
  const originInput = document.getElementById("home-origin");
  const destinationInput = document.getElementById("home-dest");
  const departureInput = document.getElementById("home-date");
  const travelersInput = document.getElementById("home-travelers");
  const daysInput = document.getElementById("home-days");
  const budgetInput = document.getElementById("home-budget");
  const preferencesInput = document.getElementById("home-preferences");
  const status = document.getElementById("home-status");
  const error = document.getElementById("home-error");
  const taskView = document.getElementById("view-task");
  const workspace = document.getElementById("workspace");
  const result = taskView;
  const tasks = [];
  let sequence = 0;
  let currentId = null;
  let historyCollapsed = false;
  let pendingDeleteId = null;
  let requestController = null;
  let requestGeneration = 0;

  function todayIso() {
    const today = new Date();
    const month = String(today.getMonth() + 1).padStart(2, "0");
    const day = String(today.getDate()).padStart(2, "0");
    return `${today.getFullYear()}-${month}-${day}`;
  }

  function startExperience() {
    intro.classList.add("hidden");
    workspace.hidden = false;
    intro.setAttribute("aria-hidden", "true");
    topbar.removeAttribute("aria-hidden");
    topbar.removeAttribute("inert");
    shell.removeAttribute("aria-hidden");
    shell.removeAttribute("inert");
    app.classList.add("ready");
    main.focus();
  }

  function showIntro() {
    if (requestController) requestController.abort();
    requestGeneration += 1;
    intro.classList.remove("hidden");
    workspace.hidden = true;
    intro.setAttribute("aria-hidden", "false");
    topbar.setAttribute("aria-hidden", "true");
    topbar.setAttribute("inert", "");
    shell.setAttribute("aria-hidden", "true");
    shell.setAttribute("inert", "");
    app.classList.remove("ready");
  }

  const startExperienceButton = document.getElementById("start-experience");
  const backToIntroButton = document.getElementById("back-to-intro");
  const newPlanButton = document.getElementById("new-plan");

  function startNewPlan() {
    resetPlanForm();
  }

  function resetPlanForm() {
    if (requestController) requestController.abort();
    requestGeneration += 1;
    form.reset();
    departureInput.min = todayIso();
    status.textContent = "";
    error.textContent = "";
    error.hidden = true;
    currentId = null;
    showView("home");
    originInput.focus();
  }

  function setTextList(element, values, emptyText) {
    const nodes = (values && values.length ? values : [emptyText]).map((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      return item;
    });
    element.replaceChildren(...nodes);
  }

  function renderDocumentHtml(markdownText) {
    const parsed = marked.parse(markdownText || "");
    const clean = DOMPurify.sanitize(parsed, {
      FORBID_TAGS: ["script", "style", "svg", "math"],
      FORBID_ATTR: [/^on/i],
    });
    return clean;
  }

  function safeMarkdown(markdownText) {
    const parsed = marked.parse(markdownText || "");
    return DOMPurify.sanitize(parsed, {
      FORBID_TAGS: ["script", "style", "svg", "math"],
      FORBID_ATTR: [/^on/i],
    });
  }

  function appendMetadata(parent, documentData) {
    const metadata = document.createElement("aside");
    metadata.className = "result-meta";
    const sections = [
      ["待核验事项", documentData.warnings, "暂无待核验事项"],
      ["来源与更新时间", (documentData.sources || []).map((source) => {
        const updated = source.source_updated_at ? `（更新时间：${source.source_updated_at}）` : "";
        return `${source.name}${updated}`;
      }), "暂无来源信息"],
      ["降级说明", (documentData.degraded_agents || []).map((agent) => `${agent}：结果已降级，请核验待核验事项。`), documentData.status === "failed" ? "规划生成失败，以下内容仅供核验。" : "当前结果未标记为降级"],
      ["错误信息", documentData.errors, "暂无错误信息"],
    ];
    sections.forEach(([title, values, emptyText]) => {
      const section = document.createElement("section");
      const heading = document.createElement("h3");
      heading.textContent = title;
      const list = document.createElement("ul");
      setTextList(list, values, emptyText);
      section.append(heading, list);
      metadata.append(section);
    });
    parent.appendChild(metadata);
  }

  function renderDocument(task, documentData) {
    task.document = documentData;
    task.status = documentData.status || "failed";
    task.preview = (documentData.markdown || "").replace(/[#*_>`\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 24);
    taskView.replaceChildren();
    const layout = document.createElement("div");
    layout.className = "task-result-layout";
    const message = document.createElement("article");
    message.className = "message";
    const head = document.createElement("div");
    head.className = "msg-head";
    const pill = document.createElement("span");
    pill.className = `pill ${task.status === "success" ? "pill-ai" : "pill-kb"}`;
    pill.textContent = task.status === "success" ? "AI 生成" : task.status === "degraded" ? "部分降级" : "生成失败";
    const title = document.createElement("span");
    title.className = "msg-title";
    title.textContent = `${task.origin} → ${task.destination} 完整方案`;
    head.append(pill, title);
    const body = document.createElement("div");
    body.className = "msg-body";
    body.innerHTML = safeMarkdown(documentData.markdown);
    message.append(head, body);
    const feedback = document.createElement("div");
    feedback.className = "msg-feedback";
    ["like", "dislike"].forEach((kind) => {
      const button = document.createElement("button");
      button.className = `fb-btn ${kind}`;
      button.type = "button";
      button.textContent = kind === "like" ? "有用" : "没用";
      button.addEventListener("click", () => vote(button));
      feedback.appendChild(button);
    });
    message.appendChild(feedback);
    layout.appendChild(message);
    appendMetadata(layout, documentData);
    taskView.appendChild(layout);
    error.hidden = true;
    status.textContent = task.status === "failed" ? "规划生成失败，页面内容仅供核验。" : task.status === "degraded" ? "规划已生成，部分信息需要核验。" : documentData.status === "success" ? "规划已生成。" : "规划状态无法确认，请核验页面内容。";
    showView("task");
    renderNav();
  }

  function setError(message) {
    setRequestError(message);
  }

  function setRequestError(message) {
    error.textContent = message;
    error.hidden = false;
    status.textContent = "";
  }

  async function nonOkMessage(response) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      return `请求失败（${response.status}）`;
    }
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (payload.detail !== undefined) return "请求参数不符合要求。";
    return `请求失败（${response.status}）`;
  }

  function requestBody(formData) {
    const body = Object.fromEntries(formData.entries());
    const departure = new Date(`${body.departure_date}T00:00:00`);
    const today = new Date(`${todayIso()}T00:00:00`);
    if (!body.departure_date || Number.isNaN(departure.getTime()) || departure < today) throw new Error("出行日期不得早于今天。");
    body.travelers = Number(body.travelers);
    body.days = Number(body.days);
    body.budget = body.budget === "" ? undefined : Number(body.budget);
    if (!Number.isInteger(body.travelers) || body.travelers < 1 || body.travelers > 20) throw new Error("出行人数必须是 1 至 20 的整数。");
    if (!Number.isInteger(body.days) || body.days < 1 || body.days > 14) throw new Error("出行天数必须是 1 至 14 的整数。");
    if (body.budget !== undefined && (!Number.isFinite(body.budget) || !Number.isInteger(body.budget) || body.budget < 0 || body.budget > 200000)) throw new Error("预算必须是 0 至 200000 的整数。");
    if (body.budget === undefined) delete body.budget;
    body.preferences = body.preferences ? body.preferences.split(",").map((item) => item.trim()).filter(Boolean) : [];
    return body;
  }

  async function submitPlan(event) {
    event.preventDefault();
    if (requestController) requestController.abort();
    requestController = new AbortController();
    const controller = requestController;
    const generation = ++requestGeneration;
    status.textContent = "正在生成旅行规划…";
    error.hidden = true;
    const task = { id: `t${++sequence}`, origin: originInput.value.trim(), destination: destinationInput.value.trim(), status: "pending", preview: "处理中…", vote: null };
    tasks.push(task);
    currentId = task.id;
    renderNav();
    showView("task");
    renderProcessing(task);
    try {
      const body = requestBody(new FormData(form));
      const response = await fetch("/api/travel-plans", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const documentData = await response.json();
      if (generation !== requestGeneration) return;
      renderDocument(task, documentData);
    } catch (requestError) {
      if (requestError instanceof Error && requestError.name === "AbortError") return;
      if (generation !== requestGeneration) return;
      task.status = "failed";
      task.preview = "请求失败";
      renderNav();
      setRequestError(requestError instanceof Error ? requestError.message : "请求失败，请稍后重试。");
      showView("home");
    } finally {
      if (generation === requestGeneration) requestController = null;
    }
  }

  function renderProcessing(task) {
    taskView.replaceChildren();
    const card = document.createElement("div");
    card.className = "message";
    const title = document.createElement("div");
    title.className = "msg-title";
    title.textContent = `${task.origin} → ${task.destination} 完整方案`;
    const steps = document.createElement("div");
    steps.className = "proc-steps";
    ["理解需求，扩写预测", "多路检索 / 生成规划要点", "组装完整方案"].forEach((label, index) => {
      const step = document.createElement("div");
      step.className = `proc-step${index === 0 ? " active" : ""}`;
      step.textContent = `${index + 1}. ${label}…`;
      steps.appendChild(step);
    });
    card.append(title, steps);
    taskView.appendChild(card);
  }

  function animateStats() {
    document.querySelectorAll(".stat-num[data-target]").forEach((element) => {
      const target = Number(element.dataset.target);
      const suffix = element.dataset.suffix || "";
      const startedAt = performance.now();
      const duration = 900;
      function tick(now) {
        const progress = Math.min((now - startedAt) / duration, 1);
        const value = Math.round(target * (1 - Math.pow(1 - progress, 3)));
        element.textContent = `${value}${suffix}`;
        if (progress < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  }

  function showView(name) {
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    const dashboard = document.getElementById("nav-dashboard");
    if (dashboard) dashboard.classList.toggle("active", name === "dashboard");
    if (name === "dashboard") animateStats();
    if (name !== "dashboard") renderNav();
  }

  function renderNav() {
    const panel = document.getElementById("history-panel");
    const count = document.getElementById("history-count");
    const toggle = document.getElementById("history-toggle");
    const list = document.getElementById("task-list");
    panel.classList.toggle("collapsed", historyCollapsed);
    count.textContent = `${tasks.length} 条`;
    toggle.textContent = historyCollapsed ? "展开" : "收起";
    toggle.setAttribute("aria-expanded", String(!historyCollapsed));
    list.replaceChildren();
    if (!tasks.length) {
      const empty = document.createElement("div");
      empty.className = "side-empty";
      empty.textContent = "暂无查询记录";
      list.appendChild(empty);
      return;
    }
    tasks.forEach((task) => {
      const item = document.createElement("div");
      item.className = `task-item${currentId === task.id ? " active" : ""}`;
      item.setAttribute("role", "button");
      item.tabIndex = 0;
      item.addEventListener("click", () => selectTask(task.id));
      item.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectTask(task.id); } });
      const mainText = document.createElement("span");
      mainText.className = "task-main";
      const taskTitle = document.createElement("span");
      taskTitle.className = "task-title";
      taskTitle.textContent = `${task.origin}→${task.destination}`;
      const preview = document.createElement("span");
      preview.className = "task-preview";
      preview.textContent = task.preview;
      mainText.append(taskTitle, preview);
      const remove = document.createElement("button");
      remove.className = "task-delete";
      remove.type = "button";
      remove.textContent = "删除";
      remove.addEventListener("click", (event) => confirmDelete(task.id, event));
      item.append(mainText, remove);
      list.appendChild(item);
    });
  }

  function toggleHistory() { historyCollapsed = !historyCollapsed; renderNav(); }
  function selectTask(id) {
    const task = tasks.find((item) => item.id === id);
    if (!task) return;
    currentId = id;
    if (task.document) renderDocument(task, task.document);
    else { renderProcessing(task); showView("task"); }
    renderNav();
  }
  function clearTasks() { tasks.length = 0; currentId = null; renderNav(); showView("home"); toast("已清空查询记录"); }
  function confirmDelete(id, event) {
    event.stopPropagation();
    pendingDeleteId = id;
    const task = tasks.find((item) => item.id === id);
    document.getElementById("confirm-text").textContent = task ? `确定删除「${task.origin}→${task.destination}」这条查询记录吗？删除后不可恢复。` : "确定删除这条查询记录吗？删除后不可恢复。";
    document.getElementById("confirm-mask").classList.add("show");
  }
  function closeConfirm(event) {
    if (event && event.target !== event.currentTarget) return;
    pendingDeleteId = null;
    document.getElementById("confirm-mask").classList.remove("show");
  }
  function doDelete() {
    const index = tasks.findIndex((task) => task.id === pendingDeleteId);
    closeConfirm();
    if (index < 0) return;
    const removed = tasks.splice(index, 1)[0];
    if (removed.id === currentId) { currentId = null; showView("home"); }
    renderNav();
  }
  function openSettings() { document.getElementById("settings-mask").classList.add("show"); }
  function closeSettings(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById("settings-mask").classList.remove("show");
  }
  function saveSettings() { closeSettings(); toast("设置为静态占位，当前未接入后端"); }
  function toast(message) {
    let element = document.getElementById("toast");
    if (!element) { element = document.createElement("div"); element.id = "toast"; element.className = "toast"; document.body.appendChild(element); }
    element.textContent = message;
    element.classList.add("show");
    window.setTimeout(() => element.classList.remove("show"), 2200);
  }
  function vote(button) {
    const task = tasks.find((item) => item.id === currentId);
    if (!task) return;
    const kind = button.classList.contains("like") ? "like" : "dislike";
    const selected = button.classList.contains("selected");
    task.vote = selected ? null : kind;
    taskView.querySelectorAll(".fb-btn").forEach((item) => item.classList.toggle("selected", item === button && !selected));
    renderNav();
  }
  function homePlan(event) { submitPlan(event); }
  function homeRegion() { toast("自定义搜索为静态占位，当前未接入知识库接口"); }

  function setupTravelShowcase() {
    const slides = [...document.querySelectorAll(".travel-slide")];
    const dots = [...document.querySelectorAll(".travel-dot")];
    const imageExtensions = ["webp", "jpg", "png"];
    slides.forEach((slide) => {
      const base = slide.dataset.imageBase;
      if (!base) return;
      let extensionIndex = 0;
      const tryNextImage = () => {
        if (extensionIndex >= imageExtensions.length) return;
        const extension = imageExtensions[extensionIndex++];
        const image = new Image();
        image.onload = () => {
          slide.style.backgroundImage = `url(\"/image/${base}.${extension}\")`;
          slide.classList.add("has-image");
        };
        image.onerror = tryNextImage;
        image.src = `/image/${base}.${extension}`;
      };
      tryNextImage();
    });
    if (!slides.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let current = 0;
    window.setInterval(() => {
      current = (current + 1) % slides.length;
      slides.forEach((slide, index) => slide.classList.toggle("is-active", index === current));
      dots.forEach((dot, index) => dot.classList.toggle("is-active", index === current));
    }, 4000);
  }

  departureInput.min = todayIso();
  startExperienceButton.addEventListener("click", startExperience);
  backToIntroButton.addEventListener("click", showIntro);
  newPlanButton.addEventListener("click", startNewPlan);
  form.addEventListener("submit", submitPlan);
  document.getElementById("intro").setAttribute("aria-hidden", "false");
  renderNav();
  setupTravelShowcase();
  window.startExperience = startExperience;
  window.showIntro = showIntro;
  window.showView = showView;
  window.renderNav = renderNav;
  window.resetPlanForm = resetPlanForm;
  window.toggleHistory = toggleHistory;
  window.selectTask = selectTask;
  window.clearTasks = clearTasks;
  window.confirmDelete = confirmDelete;
  window.closeConfirm = closeConfirm;
  window.doDelete = doDelete;
  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.saveSettings = saveSettings;
  window.homePlan = homePlan;
  window.homeRegion = homeRegion;
})();
