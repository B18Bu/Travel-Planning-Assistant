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
  const queryInput = document.getElementById("home-query");
  const status = document.getElementById("home-status");
  const error = document.getElementById("home-error");
  const taskView = document.getElementById("view-task");
  const workspace = document.getElementById("workspace");
  const regionInput = document.getElementById("home-region-input");
  const knowledgeResults = document.getElementById("knowledge-results");
  const answerMask = document.getElementById("answer-mask");
  const answerQueryNote = document.getElementById("answer-query-note");
  const answerContent = document.getElementById("answer-content");
  const travelMask = document.getElementById("travel-mask");
  const travelTitle = document.getElementById("travel-title");
  const travelContent = document.getElementById("travel-content");
  const documentUpload = document.getElementById("document-upload");
  const libraryStatus = document.getElementById("library-status");
  const libraryList = document.getElementById("library-list");
  const libraryDetail = document.getElementById("library-detail");
  const ticketForm = document.getElementById("ticket-form");
  const ticketEntryDate = document.getElementById("ticket-entry-date");
  const ticketSubmit = document.getElementById("ticket-submit");
  const ticketServiceStatus = document.getElementById("ticket-service-status");
  const ticketResults = document.getElementById("ticket-results");
  const fliggyConsentMask = document.getElementById("fliggy-consent-mask");
  const hotelForm = document.getElementById("hotel-form");
  const hotelCheckIn = document.getElementById("hotel-check-in");
  const hotelCheckOut = document.getElementById("hotel-check-out");
  const hotelSubmit = document.getElementById("hotel-submit");
  const hotelServiceStatus = document.getElementById("hotel-service-status");
  const hotelResults = document.getElementById("hotel-results");
  const result = taskView;
  const tasks = [];
  let documents = [];
  let documentPollAttempts = 0;
  let documentPollTimer = null;
  let documentRequestGeneration = 0;
  let documentDetailGeneration = 0;
  let activeDocumentDetailId = null;
  let knowledgeRequestGeneration = 0;
  let activeView = "home";
  let sequence = 0;
  let currentId = null;
  let currentSavedPlan = null;
  let historyCollapsed = false;
  let pendingDeleteId = null;
  let requestController = null;
  let requestGeneration = 0;
  let fliggyStatus = { available: false, message: "飞猪门票查询服务尚未配置" };
  let pendingFliggySubmit = false;
  const FLIGGY_CONSENT_KEY = "fliggy-ticket-query-consent";

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
    showView("plan");
    main.focus();
  }

  function showIntro() {
    const leavingGuide = activeView === "guide";
    if (requestController) requestController.abort();
    requestGeneration += 1;
    if (activeView === "library") cancelLibraryRequests();
    if (leavingGuide) knowledgeRequestGeneration += 1;
    activeView = "intro";
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
    showView("plan");
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
    travelTitle.textContent = `${task.origin} → ${task.destination} · 出行规划`;
    travelContent.replaceChildren();
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
    travelContent.appendChild(message);
    appendMetadata(travelContent, documentData);
    error.hidden = true;
    status.textContent = task.status === "failed" ? "规划生成失败，页面内容仅供核验。" : task.status === "degraded" ? "规划已生成，部分信息需要核验。" : documentData.status === "success" ? "规划已生成。" : "规划状态无法确认，请核验页面内容。";
    travelMask.classList.add("show");
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

  function nonOkPayloadMessage(payload, statusCode) {
    if (typeof payload?.detail === "string" && payload.detail) return payload.detail;
    if (payload?.detail !== undefined) return "请求参数不符合要求。";
    return `请求失败（${statusCode}）`;
  }

  async function nonOkMessage(response) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      return `请求失败（${response.status}）`;
    }
    return nonOkPayloadMessage(payload, response.status);
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
    status.textContent = "正在理解你的旅行需求…";
    error.hidden = true;
    const task = { id: `t${++sequence}`, origin: "待解析", destination: "待解析", query: queryInput.value.trim(), status: "pending", preview: "处理中…", vote: null };
    tasks.push(task);
    currentId = task.id;
    renderNav();
    renderProcessing(task);
    try {
      const parseResponse = await fetch("/api/travel-plans/parse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: queryInput.value.trim() }), signal: controller.signal });
      if (!parseResponse.ok) throw new Error(await nonOkMessage(parseResponse));
      const parsed = await parseResponse.json();
      const missing = [...(parsed.missing_fields || []), ...(parsed.ambiguous_fields || [])];
      if (missing.length) {
        const labels = { origin: "始发地", destination: "目的地", departure_date: "出行日期", travelers: "出行人数", days: "出行天数" };
        throw new Error(`以下字段是必填项或信息不明确：${[...new Set(missing)].map((field) => labels[field] || field).join("、")}`);
      }
      originInput.value = parsed.origin;
      destinationInput.value = parsed.destination;
      departureInput.value = parsed.departure_date;
      travelersInput.value = parsed.travelers;
      daysInput.value = parsed.days;
      budgetInput.value = parsed.budget ?? "";
      preferencesInput.value = (parsed.preferences || []).join(",");
      task.origin = parsed.origin;
      task.destination = parsed.destination;
      renderNav();
      const body = requestBody(new FormData(form));
      const response = await fetch("/api/travel-plans", { method: "POST", headers: { "Content-Type": "application/json", "X-Travel-Query": queryInput.value.trim() }, body: JSON.stringify(body), signal: controller.signal });
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
      closeTravelModal();
      const message = requestError instanceof Error ? requestError.message : "请求失败，请稍后重试。";
      setRequestError(message);
      if (message.includes("必填项") || message.includes("不明确")) window.alert(message);
      showView("plan");
    } finally {
      if (generation === requestGeneration) requestController = null;
    }
  }

  function renderProcessing(task) {
    travelTitle.textContent = `${task.origin} → ${task.destination} · 出行规划`;
    travelContent.replaceChildren();
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
    travelContent.appendChild(card);
    travelMask.classList.add("show");
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

  function cancelLibraryRequests() {
    cancelDocumentPolling();
    documentDetailGeneration += 1;
    activeDocumentDetailId = null;
  }

  function hasFliggyConsent() {
    try {
      return sessionStorage.getItem(FLIGGY_CONSENT_KEY) === "accepted";
    } catch {
      return false;
    }
  }

  function saveFliggyConsent() {
    try {
      sessionStorage.setItem(FLIGGY_CONSENT_KEY, "accepted");
      return true;
    } catch {
      return false;
    }
  }

  async function loadFliggyStatus() {
    ticketSubmit.disabled = true;
    ticketServiceStatus.textContent = "正在检查飞猪门票查询服务…";
    try {
      const response = await fetch("/api/fliggy/status");
      const payload = await response.json();
      fliggyStatus = {
        available: payload.available === true,
        message: typeof payload.message === "string" ? payload.message : "飞猪门票查询服务暂不可用",
      };
    } catch {
      fliggyStatus = { available: false, message: "飞猪门票查询服务暂不可用" };
    }
    ticketServiceStatus.textContent = fliggyStatus.message;
    ticketSubmit.disabled = !fliggyStatus.available;
    if (!fliggyStatus.available) {
      ticketResults.replaceChildren();
      ticketResults.hidden = true;
    }
  }

  function closeFliggyConsent(event) {
    if (event && event.target !== event.currentTarget) return;
    pendingFliggySubmit = false;
    fliggyConsentMask.classList.remove("show");
  }

  function acceptFliggyConsent() {
    if (!saveFliggyConsent()) {
      closeFliggyConsent();
      return;
    }
    fliggyConsentMask.classList.remove("show");
    if (pendingFliggySubmit) submitTicketSearch();
    pendingFliggySubmit = false;
  }

  function requestFliggyConsent() {
    if (hasFliggyConsent()) return true;
    pendingFliggySubmit = true;
    fliggyConsentMask.classList.add("show");
    return false;
  }

  async function submitTicketSearch(event) {
    if (event) event.preventDefault();
    if (!fliggyStatus.available) return;
    if (!requestFliggyConsent()) return;
    ticketSubmit.disabled = true;
    ticketServiceStatus.textContent = "正在查询飞猪门票信息…";
    ticketResults.replaceChildren();
    ticketResults.hidden = true;
    try {
      const formData = new FormData(ticketForm);
      const response = await fetch("/api/fliggy/tickets/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenic_keyword: formData.get("scenic_keyword"),
          city_name: formData.get("city_name") || "",
          entry_date: formData.get("entry_date"),
          visitor_count: Number(formData.get("visitor_count")),
        }),
      });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      renderTicketResults(payload);
    } catch (requestError) {
      ticketServiceStatus.textContent = `实时查询暂不可用：${documentErrorMessage(requestError, "请稍后重试。")}`;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn-ghost";
      retry.textContent = "重试";
      retry.addEventListener("click", () => submitTicketSearch());
      ticketResults.replaceChildren(retry);
      ticketResults.hidden = false;
    } finally {
      ticketSubmit.disabled = !fliggyStatus.available;
    }
  }

  function renderTicketResults(payload) {
    ticketResults.replaceChildren();
    if (payload.data_status === "flyai_text") {
      const pois = Array.isArray(payload.poi_results) ? payload.poi_results : [];
      if (pois.length) {
        pois.forEach((poi) => {
          const card = document.createElement("article");
          card.className = "fliggy-ticket-card";
          const title = document.createElement("h3");
          title.textContent = poi.poi_name || "门票信息";
          const meta = document.createElement("p");
          meta.textContent = [poi.category, poi.address].filter(Boolean).join(" · ");
          card.appendChild(title);
          if (meta.textContent) card.appendChild(meta);
          const price = document.createElement("p");
          price.textContent = poi.price_text
            ? `参考价：${poi.price_text}${poi.ticket_name ? `（${poi.ticket_name}）` : ""}，以飞猪官方页面为准`
            : "价格信息暂不可用";
          card.appendChild(price);
          if (poi.ticket_name && !poi.price_text) {
            const ticket = document.createElement("p");
            ticket.textContent = `票种：${poi.ticket_name}`;
            card.appendChild(ticket);
          }
          if (poi.description) {
            const desc = document.createElement("p");
            desc.textContent = poi.description;
            card.appendChild(desc);
          }
          ticketResults.appendChild(card);
        });
      } else {
        const card = document.createElement("article");
        card.className = "fliggy-ticket-card";
        const title = document.createElement("h3");
        title.textContent = payload.scenic_keyword || "门票信息";
        const summary = document.createElement("p");
        summary.textContent = payload.summary || "未找到相关门票信息，请调整关键词后重试。";
        const meta = document.createElement("p");
        const source = typeof payload.source_name === "string" ? payload.source_name : "飞猪 AI 开放平台";
        const retrievedAt = typeof payload.retrieved_at === "string" ? payload.retrieved_at : "";
        meta.textContent = `来源：${source}${retrievedAt ? ` · 查询时间：${retrievedAt}` : ""}`;
        card.append(title, summary, meta);
        ticketResults.appendChild(card);
      }
      (Array.isArray(payload.warnings) ? payload.warnings : ["FlyAI 文本检索结果，不代表实时可售状态。"]).forEach((text) => {
        const warning = document.createElement("p");
        warning.className = "fliggy-notice";
        warning.textContent = text;
        ticketResults.appendChild(warning);
      });
      ticketResults.hidden = false;
      return;
    }
    const tickets = Array.isArray(payload.tickets) ? payload.tickets : [];
    if (!tickets.length) {
      const empty = document.createElement("p");
      empty.textContent = "未找到已接入的门票商品，请调整关键词后重试。";
      ticketResults.appendChild(empty);
    }
    tickets.forEach((ticket) => {
      const card = document.createElement("article");
      card.className = "fliggy-ticket-card";
      const imageUrls = Array.isArray(ticket.image_urls) ? ticket.image_urls : [];
      if (imageUrls.length && payload.image_display_allowed === true) {
        const image = document.createElement("img");
        image.src = imageUrls[0];
        image.alt = ticket.item_name || "门票商品图片";
        image.loading = "lazy";
        card.appendChild(image);
      }
      const title = document.createElement("h3");
      title.textContent = ticket.item_name || "未命名门票商品";
      const meta = document.createElement("p");
      meta.textContent = [ticket.ticket_type, ticket.entry_date, ticket.entry_type].filter(Boolean).join(" · ");
      const price = document.createElement("p");
      price.textContent = ticket.price_amount === undefined ? "价格信息暂不可用" : `价格：${(Number(ticket.price_amount) / 100).toFixed(2)} ${ticket.currency || "CNY"}`;
      const stock = document.createElement("p");
      stock.textContent = ticket.stock_status === "empty" ? "库存为 0" : ticket.stock_status === "unknown" ? "库存信息暂不可用" : `库存：${ticket.stock ?? "信息暂不可用"}`;
      card.append(title, meta, price, stock);
      const note = document.createElement("p");
      note.textContent = payload.data_status === "mock" ? "当前为演示数据，不代表飞猪实时价格、库存或可售状态。" : "价格和库存仅代表查询时刻，不代表最终可售或预订成功。";
      card.appendChild(note);
      ticketResults.appendChild(card);
    });
    (Array.isArray(payload.warnings) ? payload.warnings : ["本系统仅提供门票信息查询，请通过飞猪官方渠道完成购买。"]).forEach((text) => {
      const warning = document.createElement("p");
      warning.className = "fliggy-notice";
      warning.textContent = text;
      ticketResults.appendChild(warning);
    });
    ticketResults.hidden = false;
  }

  function isHttpsUrl(value) {
    if (typeof value !== "string" || !value) return false;
    try {
      return new URL(value, window.location.href).protocol === "https:";
    } catch {
      return false;
    }
  }

  function formatHotelTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "未知" : formatIndexTime(date);
  }

  function hotelSourceTags(hotel) {
    if (hotel.match_status === "poi_only") return ["高德POI"];
    if (hotel.match_status === "flyai_only") return ["FlyAI"];
    if (hotel.match_status === "matched") return ["FlyAI", "高德POI"];
    const tags = [];
    if (hotel.poi_source === "amap") tags.push("高德POI");
    if (hotel.price_source === "flyai") tags.push("FlyAI");
    return tags;
  }

  function buildHotelBody(formData) {
    const city = String(formData.get("city_name") || "").trim();
    if (!city) throw new Error("请输入城市。");
    const checkInValue = String(formData.get("check_in") || "");
    const checkOutValue = String(formData.get("check_out") || "");
    const checkIn = new Date(`${checkInValue}T00:00:00`);
    const checkOut = new Date(`${checkOutValue}T00:00:00`);
    const today = new Date(`${todayIso()}T00:00:00`);
    if (!checkInValue || Number.isNaN(checkIn.getTime()) || checkIn < today) throw new Error("入住日期不得早于今天。");
    if (!checkOutValue || Number.isNaN(checkOut.getTime())) throw new Error("离店日期格式不正确。");
    if (checkOut <= checkIn) throw new Error("离店日期必须晚于入住日期。");
    return { city_name: city, check_in: checkInValue, check_out: checkOutValue };
  }

  function renderHotelServiceError(message, withRetry) {
    hotelServiceStatus.textContent = message;
    hotelResults.replaceChildren();
    if (withRetry) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn-ghost";
      retry.textContent = "重试";
      retry.addEventListener("click", () => submitHotelSearch());
      hotelResults.appendChild(retry);
    }
    hotelResults.hidden = false;
  }

  async function submitHotelSearch(event) {
    if (event) event.preventDefault();
    let body;
    try {
      body = buildHotelBody(new FormData(hotelForm));
    } catch (validationError) {
      hotelServiceStatus.textContent = documentErrorMessage(validationError, "请检查输入后重试。");
      return;
    }
    hotelSubmit.disabled = true;
    hotelServiceStatus.textContent = "正在查询酒店…";
    hotelResults.replaceChildren();
    hotelResults.hidden = true;
    try {
      const response = await fetch("/api/fliggy/hotels/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (response.status === 503) {
        renderHotelServiceError("酒店推荐服务尚未配置，暂时无法查询。", false);
        return;
      }
      if (response.status === 502) {
        renderHotelServiceError("上游酒店查询服务暂不可用，请稍后重试。", true);
        return;
      }
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      renderHotelResults(payload);
    } catch (requestError) {
      hotelServiceStatus.textContent = `酒店查询失败：${documentErrorMessage(requestError, "请稍后重试。")}`;
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn-ghost";
      retry.textContent = "重试";
      retry.addEventListener("click", () => submitHotelSearch());
      hotelResults.replaceChildren(retry);
      hotelResults.hidden = false;
    } finally {
      hotelSubmit.disabled = false;
    }
  }

  function renderHotelResults(payload) {
    hotelResults.replaceChildren();
    const hotels = Array.isArray(payload.hotels) ? payload.hotels : [];
    if (!hotels.length) {
      const empty = document.createElement("p");
      empty.className = "hotel-empty";
      empty.textContent = "未找到匹配的酒店，请调整城市或日期后重试。";
      hotelResults.appendChild(empty);
    }
    hotels.forEach((hotel) => {
      const card = document.createElement("article");
      card.className = "hotel-card";
      const imageUrl = hotel.flyai_main_pic;
      if (isHttpsUrl(imageUrl)) {
        const image = document.createElement("img");
        image.src = imageUrl;
        image.alt = hotel.hotel_name || "酒店图片";
        image.loading = "lazy";
        image.addEventListener("error", () => image.remove());
        card.appendChild(image);
      }
      const title = document.createElement("h3");
      title.textContent = hotel.hotel_name || "未命名酒店";
      const tags = document.createElement("div");
      tags.className = "hotel-tags";
      hotelSourceTags(hotel).forEach((label) => {
        const tag = document.createElement("span");
        tag.className = `hotel-tag ${label === "FlyAI" ? "hotel-tag-flyai" : "hotel-tag-amap"}`;
        tag.textContent = label;
        tags.appendChild(tag);
      });
      const addressText = hotel.amap_address || "位置暂无匹配";
      const address = document.createElement("p");
      address.textContent = `地址：${addressText}`;
      const price = document.createElement("p");
      price.className = "hotel-price";
      price.textContent = hotel.flyai_price == null ? "价格暂不可用" : `价格：${Number(hotel.flyai_price).toFixed(2)} 元`;
      const meta = document.createElement("p");
      const metaParts = [];
      if (hotel.flyai_score != null) metaParts.push(`评分：${Number(hotel.flyai_score).toFixed(1)}`);
      if (hotel.flyai_star != null) metaParts.push(`星级：${hotel.flyai_star} 星`);
      meta.textContent = metaParts.length ? metaParts.join(" · ") : "暂无评分与星级信息";
      let detailLink = null;
      if (isHttpsUrl(hotel.detail_url)) {
        detailLink = document.createElement("a");
        detailLink.className = "hotel-detail-link";
        detailLink.href = hotel.detail_url;
        detailLink.target = "_blank";
        detailLink.rel = "noopener noreferrer";
        detailLink.textContent = "官方详情";
      }
      card.append(title, tags, address, price, meta);
      if (detailLink) card.appendChild(detailLink);
      hotelResults.appendChild(card);
    });
    const timeNote = document.createElement("p");
    timeNote.className = "hotel-query-time";
    const flyaiTime = payload.flyai_retrieved_at ? formatHotelTime(payload.flyai_retrieved_at) : "未知";
    if (payload.poi_unavailable === true) {
      timeNote.textContent = `FlyAI 查询时间：${flyaiTime} · 高德 POI 暂不可用`;
    } else if (payload.amap_retrieved_at) {
      timeNote.textContent = `查询时间：FlyAI ${flyaiTime} · 高德 ${formatHotelTime(payload.amap_retrieved_at)}`;
    } else {
      timeNote.textContent = `查询时间：FlyAI ${flyaiTime}`;
    }
    hotelResults.appendChild(timeNote);
    hotelResults.hidden = false;
  }

  function showView(name) {
    activeView = name;
    if (name !== "library") cancelLibraryRequests();
    if (name !== "guide") knowledgeRequestGeneration += 1;
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    const dashboard = document.getElementById("nav-dashboard");
    const library = document.getElementById("nav-library");
    const plan = document.getElementById("nav-plan");
    const plans = document.getElementById("nav-plans");
    const guide = document.getElementById("nav-guide");
    const ticket = document.getElementById("nav-ticket");
    const hotel = document.getElementById("nav-hotel");
    if (dashboard) dashboard.classList.toggle("active", name === "dashboard");
    if (library) library.classList.toggle("active", name === "library");
    if (plan) plan.classList.toggle("active", name === "plan");
    if (plans) plans.classList.toggle("active", name === "plans");
    if (guide) guide.classList.toggle("active", name === "guide");
    if (ticket) ticket.classList.toggle("active", name === "ticket");
    if (hotel) hotel.classList.toggle("active", name === "hotel");
    if (name === "ticket") loadFliggyStatus();
    if (name === "dashboard") loadDashboardStats();
    if (name === "library") loadDocuments();
    if (name === "plans") loadSavedPlans();
    if (name !== "dashboard") renderNav();
  }

  async function loadSavedPlans() {
    const container = document.getElementById("saved-plans");
    if (!container) return;
    try {
      const response = await fetch("/api/travel-plans/saved");
      if (!response.ok) throw new Error("方案列表暂不可用");
      const plans = await response.json();
      container.replaceChildren();
      if (!plans.length) { container.textContent = "暂无已保存方案。"; return; }
      plans.forEach((plan) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "saved-plan-item";
        button.textContent = `${plan.query || "未命名方案"} · v${plan.version}`;
        button.addEventListener("click", () => openSavedPlan(plan.plan_id));
        container.appendChild(button);
      });
    } catch (requestError) { container.textContent = requestError.message; }
  }

  async function openSavedPlan(planId) {
    const response = await fetch(`/api/travel-plans/saved/${encodeURIComponent(planId)}`);
    if (!response.ok) return;
    const record = await response.json();
    currentSavedPlan = record;
    const task = { id: record.plan_id, origin: record.request.origin, destination: record.request.destination, document: record.document, status: record.document.status, preview: "已保存方案", vote: null };
    tasks.push(task); currentId = task.id; renderDocument(task, record.document); showView("task");
  }

  async function submitPlanRevision() {
    const query = document.getElementById("plan-revision-query")?.value.trim();
    if (!currentSavedPlan || !query) return;
    const response = await fetch(`/api/travel-plans/saved/${encodeURIComponent(currentSavedPlan.plan_id)}/revisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, version: currentSavedPlan.version }) });
    if (!response.ok) { window.alert(await nonOkMessage(response)); return; }
    currentSavedPlan = await response.json();
    const task = tasks.find((item) => item.id === currentSavedPlan.plan_id);
    if (task) { task.document = currentSavedPlan.document; task.origin = currentSavedPlan.request.origin; task.destination = currentSavedPlan.request.destination; renderDocument(task, task.document); }
    document.getElementById("plan-revision-query").value = "";
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
    tasks.slice(-3).forEach((task) => {
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
      taskTitle.textContent = task.kind === "knowledge" ? `🔍 ${task.query}` : `${task.origin}→${task.destination}`;
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
    if (task.kind === "knowledge") {
      openAnswerModal(task);
    } else if (task.document) {
      renderDocument(task, task.document);
    } else {
      renderProcessing(task);
    }
    renderNav();
  }
  async function clearTasks() {
    tasks.length = 0;
    currentId = null;
    renderNav();
    showView("plan");
    const synced = await clearKnowledgeRecords();
    toast(synced ? "已清空查询记录" : "查询记录已清空，但同步失败，刷新后可能重新出现");
  }
  function confirmDelete(id, event) {
    event.stopPropagation();
    pendingDeleteId = id;
    const task = tasks.find((item) => item.id === id);
    const label = task ? (task.kind === "knowledge" ? `「${task.query}」` : `「${task.origin}→${task.destination}」`) : "";
    document.getElementById("confirm-text").textContent = `确定删除${label}这条查询记录吗？删除后不可恢复。`;
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
    if (removed.id === currentId) { currentId = null; showView("plan"); }
    if (removed.kind === "knowledge") deleteKnowledgeRecord(removed.id);
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
    travelContent.querySelectorAll(".fb-btn").forEach((item) => item.classList.toggle("selected", item === button && !selected));
    renderNav();
  }
  function homePlan(event) { submitPlan(event); }

  function documentErrorMessage(requestError, fallback) {
    return requestError instanceof Error && requestError.message ? requestError.message : fallback;
  }

  function setLibraryStatus(message, isError = false) {
    libraryStatus.textContent = message;
    libraryStatus.classList.toggle("library-status-error", isError);
  }

  function documentStatusLabel(statusValue) {
    return { pending: "等待处理", processing: "处理中", ready: "已处理", failed: "处理失败" }[statusValue] || "状态未知";
  }

  function renderDocumentDetail(documentData, chunks) {
    libraryDetail.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = `${documentData.filename} 的内容块`;
    const chunkList = document.createElement("div");
    chunkList.className = "library-chunks";
    if (!chunks.length) {
      const empty = document.createElement("p");
      empty.textContent = "暂无可展示的内容块。";
      chunkList.appendChild(empty);
    }
    chunks.forEach((chunk) => {
      const item = document.createElement("article");
      item.className = "library-chunk";
      const meta = document.createElement("p");
      meta.textContent = `${chunk.chunk_type || "text"} · ${chunk.source_page ? `第 ${chunk.source_page} 页` : chunk.source_section || "未标注位置"}`;
      const content = document.createElement("p");
      content.textContent = chunk.content || "";
      item.append(meta, content);
      chunkList.appendChild(item);
    });
    libraryDetail.append(heading, chunkList);
    libraryDetail.hidden = false;
    main.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function showDocumentDetail(documentData) {
    const generation = ++documentDetailGeneration;
    activeDocumentDetailId = documentData.id;
    try {
      const response = await fetch(`/api/documents/${documentData.id}/chunks`);
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const chunks = await response.json();
      if (generation !== documentDetailGeneration || activeView !== "library" || activeDocumentDetailId !== documentData.id) return;
      renderDocumentDetail(documentData, Array.isArray(chunks) ? chunks : []);
    } catch (requestError) {
      if (generation !== documentDetailGeneration || activeView !== "library" || activeDocumentDetailId !== documentData.id) return;
      setLibraryStatus(`无法加载文档详情：${documentErrorMessage(requestError, "文档服务暂不可用。")}`, true);
    }
  }

  function renderDocuments() {
    libraryList.replaceChildren();
    if (!documents.length) {
      const empty = document.createElement("p");
      empty.className = "library-empty";
      empty.textContent = "暂无已上传文档。";
      libraryList.appendChild(empty);
      return;
    }
    documents.forEach((documentData) => {
      const card = document.createElement("article");
      card.className = "library-card";
      const title = document.createElement("h3");
      title.textContent = documentData.filename || "未命名文档";
      const meta = document.createElement("p");
      meta.textContent = `${documentStatusLabel(documentData.status)} · ${documentData.chunk_count || 0} 个内容块`;
      const actions = document.createElement("div");
      actions.className = "library-actions";
      const detail = document.createElement("button");
      detail.type = "button";
      detail.textContent = "查看详情";
      detail.disabled = documentData.status !== "ready";
      detail.addEventListener("click", () => showDocumentDetail(documentData));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "删除";
      remove.addEventListener("click", () => deleteDocument(documentData.id));
      actions.append(detail, remove);
      card.append(title, meta, actions);
      libraryList.appendChild(card);
    });
  }

  function cancelDocumentPolling() {
    documentRequestGeneration += 1;
    window.clearTimeout(documentPollTimer);
    documentPollTimer = null;
  }

  function scheduleDocumentPoll() {
    const requiresPolling = documents.some((documentData) => documentData.status === "pending" || documentData.status === "processing");
    if (activeView !== "library" || !requiresPolling) return;
    if (documentPollAttempts < 30) {
      documentPollAttempts += 1;
    } else {
      setLibraryStatus("文档处理仍未完成，请稍后刷新查看状态。", true);
      return;
    }
    window.clearTimeout(documentPollTimer);
    documentPollTimer = window.setTimeout(() => {
      documentPollTimer = null;
      loadDocuments(true);
    }, 2000);
  }

  async function loadDocuments(isPolling = false, preserveStatus = false) {
    if (activeView !== "library") return;
    if (!isPolling) {
      documentPollAttempts = 0;
      cancelDocumentPolling();
    }
    const generation = ++documentRequestGeneration;
    try {
      const response = await fetch("/api/documents");
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      if (generation !== documentRequestGeneration || activeView !== "library") return;
      documents = Array.isArray(payload) ? payload : [];
      updateKnowledgeFoot(payload);
      renderDocuments();
      if (!preserveStatus) setLibraryStatus(documents.length ? "文档列表已更新。" : "可上传 Word 或 PDF 文档。");
      scheduleDocumentPoll();
    } catch (requestError) {
      if (generation !== documentRequestGeneration || activeView !== "library") return;
      setLibraryStatus(`文档库服务不可用：${documentErrorMessage(requestError, "请稍后重试。")}`, true);
    }
  }

  async function updateKnowledgeFoot(payload) {
    try {
      if (!payload) {
        const response = await fetch("/api/documents");
        if (!response.ok) return;
        payload = await response.json();
      }
      if (!Array.isArray(payload)) return;
      const docs = payload;
      const totalChunks = docs.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
      const summary = document.getElementById("kb-summary");
      const lastIndex = document.getElementById("kb-last-index");
      if (summary) summary.textContent = `📚 知识库 · ${docs.length} 份文档 / ${totalChunks} 个内容块`;
      if (lastIndex) {
        const times = docs.map((doc) => doc.updated_at).filter((value) => typeof value === "string");
        if (times.length) {
          const latest = new Date(Math.max(...times.map((value) => new Date(value).getTime())));
          if (!Number.isNaN(latest.getTime())) {
            lastIndex.textContent = `🔄 最近索引 · ${formatIndexTime(latest)}`;
            return;
          }
        }
        lastIndex.textContent = "🔄 最近索引 · 暂无";
      }
    } catch {
      // 知识库统计加载失败保留默认文案。
    }
  }

  function formatIndexTime(date) {
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  async function uploadDocument() {
    const files = Array.from(documentUpload.files || []);
    if (!files.length) return;
    cancelDocumentPolling();
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    setLibraryStatus("正在上传文档…");
    try {
      const response = await fetch("/api/documents/batch", { method: "POST", body: formData });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error(`请求失败（${response.status}）`);
      }
      if (!Array.isArray(payload.items)) {
        throw new Error(response.ok ? "批量上传响应无效" : nonOkPayloadMessage(payload, response.status));
      }
      const resultByIndex = new Map(payload.items.map((result) => [result.index, result]));
      const summaries = files.map((file, offset) => {
        const result = resultByIndex.get(offset + 1);
        const statusText = result?.status === "accepted" ? "已提交" : result?.status === "unavailable" ? "暂不可用" : "未通过";
        const detail = result?.error ? `：${result.error}` : "";
        return `${file.name}：${statusText}${detail}`;
      });
      documentUpload.value = "";
      setLibraryStatus(summaries.join("\n"), !response.ok);
      if (payload.items.some((result) => result.status === "accepted")) await loadDocuments(false, true);
    } catch (requestError) {
      documentUpload.value = "";
      setLibraryStatus(`上传失败：${documentErrorMessage(requestError, "文档服务暂不可用。")}`, true);
    }
  }

  async function deleteDocument(documentId) {
    try {
      const response = await fetch(`/api/documents/${documentId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      if (documentId === activeDocumentDetailId) {
        documentDetailGeneration += 1;
        activeDocumentDetailId = null;
        libraryDetail.hidden = true;
      }
      await loadDocuments();
    } catch (requestError) {
      setLibraryStatus(`删除失败：${documentErrorMessage(requestError, "文档服务暂不可用。")}`, true);
    }
  }

  function renderKnowledgeResults(results) {
    knowledgeResults.replaceChildren();
    if (!results.length) {
      const empty = document.createElement("p");
      empty.textContent = "未找到匹配的已处理文档内容。";
      knowledgeResults.appendChild(empty);
    }
    results.forEach((item) => {
      const card = document.createElement("article");
      card.className = "knowledge-result";
      const source = item.source || {};
      const header = document.createElement("div");
      header.className = "knowledge-result-header";
      const meta = document.createElement("span");
      meta.className = "knowledge-result-meta";
      const locations = [
        source.page ? `第 ${source.page} 页` : "",
        source.section || "",
        source.table ? `表 ${source.table}` : "",
        source.figure ? `图 ${source.figure}` : "",
      ].filter(Boolean);
      const location = locations.length ? locations.join(" · ") : "未标注位置";
      meta.textContent = `${item.chunk_type || "text"} · ${source.document_name || "未知来源"} · ${location}`;
      const badge = document.createElement("span");
      badge.className = `match-badge match-${item.matched_by || "semantic"}`;
      badge.textContent = item.matched_by === "both" ? "混合" : item.matched_by === "keyword" ? "关键词" : "语义";
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.className = "knowledge-detail-btn";
      detailButton.textContent = "查看详情 ▾";
      detailButton.addEventListener("click", () => {
        content.hidden = !content.hidden;
        detailButton.textContent = content.hidden ? "查看详情 ▾" : "收起 ▴";
      });
      header.append(meta, badge, detailButton);
      const content = document.createElement("p");
      content.className = "knowledge-result-content";
      content.textContent = item.content || "";
      content.hidden = true;
      card.append(header, content);
      knowledgeResults.appendChild(card);
    });
    knowledgeResults.hidden = false;
  }

  function openAnswerModal(record) {
    answerQueryNote.textContent = record.query ? `查询：${record.query}` : "";
    answerContent.replaceChildren();
    if (record.answer) {
      const markdown = document.createElement("div");
      markdown.className = "answer-markdown";
      markdown.innerHTML = safeMarkdown(record.answer);
      answerContent.appendChild(markdown);
    } else {
      const note = document.createElement("p");
      note.className = "answer-hint";
      note.textContent = record.answerStatus === "unavailable"
        ? "大模型未配置或生成失败，以下为原始检索片段。"
        : "该记录未生成完整回答。";
      answerContent.appendChild(note);
      (record.results || []).forEach((item) => {
        const card = document.createElement("article");
        card.className = "knowledge-result";
        const source = item.source || {};
        const meta = document.createElement("p");
        const locations = [
          source.page ? `第 ${source.page} 页` : "",
          source.section || "",
          source.table ? `表 ${source.table}` : "",
          source.figure ? `图 ${source.figure}` : "",
        ].filter(Boolean);
        meta.textContent = `${item.chunk_type || "text"} · ${source.document_name || "未知来源"} · ${(locations.length ? locations.join(" · ") : "未标注位置")}`;
        const content = document.createElement("p");
        content.textContent = item.content || "";
        card.append(meta, content);
        answerContent.appendChild(card);
      });
    }
    if (record.id) {
      renderFeedback(record, answerContent);
    }
    answerMask.classList.add("show");
  }

  function closeAnswerModal(event) {
    if (event && event.target !== event.currentTarget) return;
    answerMask.classList.remove("show");
  }

  function closeTravelModal(event) {
    if (event && event.target !== event.currentTarget) return;
    travelMask.classList.remove("show");
  }

  function addKnowledgeTask(record) {
    const task = {
      kind: "knowledge",
      id: record.id,
      query: record.query,
      preview: record.answer ? record.answer.replace(/[#*_>`\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 24) : "未生成完整回答",
      answer: record.answer,
      answerStatus: record.answerStatus,
      results: record.results || [],
      rating: record.rating || null,
    };
    tasks.push(task);
    currentId = task.id;
    renderNav();
  }

  async function loadKnowledgeRecords() {
    try {
      const response = await fetch("/api/knowledge-records");
      if (!response.ok) return;
      const payload = await response.json();
      if (!Array.isArray(payload)) return;
      const known = new Set(tasks.filter((task) => task.kind === "knowledge").map((task) => task.id));
      payload.forEach((record) => {
        if (known.has(record.id)) return;
        tasks.push({
          kind: "knowledge",
          id: record.id,
          query: record.query,
          preview: record.answer ? record.answer.replace(/[#*_>`\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 24) : "未生成完整回答",
          answer: record.answer,
          answerStatus: record.answer_status,
          results: record.results || [],
          rating: record.rating || null,
        });
      });
      renderNav();
    } catch {
      // 记录加载失败静默降级，仅影响回看。
    }
  }

  async function deleteKnowledgeRecord(recordId) {
    try {
      const response = await fetch(`/api/knowledge-records/${recordId}`, { method: "DELETE" });
      if (!response.ok) toast("删除同步失败，刷新后可能重新出现");
    } catch {
      toast("删除同步失败，刷新后可能重新出现");
    }
  }

  async function clearKnowledgeRecords() {
    try {
      const response = await fetch("/api/knowledge-records", { method: "DELETE" });
      return response.ok;
    } catch {
      return false;
    }
  }

  async function generateAnswer(task, button) {
    const generation = knowledgeRequestGeneration;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "正在生成完整回答…";
    try {
      const response = await fetch("/api/knowledge-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: task.query, document_ids: [], generate_markdown: true, record_id: task.id }),
      });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      if (generation !== knowledgeRequestGeneration || activeView !== "guide") return;
      task.answer = payload.answer;
      task.answerStatus = payload.answer_status;
      task.results = payload.results || task.results;
      if (payload.answer) {
        button.textContent = "查看完整回答";
        renderNav();
        if (generation === knowledgeRequestGeneration) {
          openAnswerModal(task);
        }
      } else if (generation === knowledgeRequestGeneration) {
        button.textContent = originalText;
        const hint = document.createElement("p");
        hint.className = "answer-hint";
        hint.textContent = "大模型生成失败，可稍后重试。";
        button.parentElement.appendChild(hint);
      }
    } catch (requestError) {
      if (generation !== knowledgeRequestGeneration || activeView !== "guide") return;
      button.textContent = originalText;
      const hint = document.createElement("p");
      hint.className = "answer-hint";
      hint.textContent = `生成失败：${documentErrorMessage(requestError, "请稍后重试。")}`;
      button.parentElement.appendChild(hint);
    } finally {
      if (generation === knowledgeRequestGeneration && activeView === "guide" && button.isConnected) button.disabled = false;
    }
  }

  async function openRecordsModal() {
    const mask = document.getElementById("records-mask");
    const list = document.getElementById("records-list");
    mask.classList.add("show");
    list.replaceChildren();
    const loading = document.createElement("p");
    loading.textContent = "正在加载记录…";
    list.appendChild(loading);
    try {
      const response = await fetch("/api/knowledge-records");
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      list.replaceChildren();
      if (!Array.isArray(payload) || !payload.length) {
        const empty = document.createElement("p");
        empty.textContent = "暂无查询记录。";
        list.appendChild(empty);
        return;
      }
      payload.forEach((record) => {
        const item = document.createElement("div");
        item.className = "record-manage-item";
        const main = document.createElement("div");
        main.className = "record-manage-main";
        const title = document.createElement("span");
        title.className = "record-manage-title";
        title.textContent = `🔍 ${record.query}`;
        const meta = document.createElement("span");
        meta.className = "record-manage-meta";
        meta.textContent = `${record.answer_status === "generated" ? "已回答" : "未回答"} · ${Array.isArray(record.results) ? record.results.length : 0} 条片段`;
        main.append(title, meta);
        if (record.answer) {
          const answerPreview = document.createElement("span");
          answerPreview.className = "record-manage-preview";
          answerPreview.textContent = record.answer.replace(/[#*_>`\n]/g, " ").replace(/\s+/g, " ").trim().slice(0, 44);
          main.appendChild(answerPreview);
        }
        const actions = document.createElement("div");
        actions.className = "record-manage-actions";
        const view = document.createElement("button");
        view.type = "button";
        view.textContent = "查看";
        view.addEventListener("click", () => openAnswerModal({
          id: record.id, query: record.query, answer: record.answer,
          answerStatus: record.answer_status, results: record.results, rating: record.rating,
        }));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "record-manage-delete";
        remove.textContent = "删除";
        remove.addEventListener("click", () => deleteRecordFromManage(record.id, item));
        actions.append(view, remove);
        item.append(main, actions);
        list.appendChild(item);
      });
    } catch (requestError) {
      list.replaceChildren();
      const error = document.createElement("p");
      error.textContent = `加载失败：${documentErrorMessage(requestError, "请稍后重试。")}`;
      list.appendChild(error);
    }
  }

  function closeRecordsModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById("records-mask").classList.remove("show");
  }

  async function deleteRecordFromManage(recordId, item) {
    try {
      const response = await fetch(`/api/knowledge-records/${recordId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      item.remove();
      const index = tasks.findIndex((task) => task.kind === "knowledge" && task.id === recordId);
      if (index >= 0) {
        const removed = tasks.splice(index, 1)[0];
        if (removed.id === currentId) currentId = null;
        renderNav();
      }
      toast("已删除记录");
    } catch (requestError) {
      toast(`删除失败：${documentErrorMessage(requestError, "请稍后重试。")}`);
    }
  }

  function renderFeedback(task, container) {
    const feedback = document.createElement("div");
    feedback.className = "knowledge-feedback";
    const label = document.createElement("span");
    label.className = "feedback-label";
    label.textContent = "这个结果对你有帮助吗？";
    const like = document.createElement("button");
    like.type = "button";
    like.className = "fb-btn like";
    like.textContent = "有用";
    const dislike = document.createElement("button");
    dislike.type = "button";
    dislike.className = "fb-btn dislike";
    dislike.textContent = "没用";
    if (task.rating === "like" || task.rating === "dislike") {
      (task.rating === "like" ? like : dislike).classList.add("selected");
      like.disabled = true;
      dislike.disabled = true;
    }
    like.addEventListener("click", () => submitFeedback(task, "like", like, dislike));
    dislike.addEventListener("click", () => submitFeedback(task, "dislike", like, dislike));
    feedback.append(label, like, dislike);
    container.appendChild(feedback);
  }

  async function submitFeedback(task, rating, like, dislike) {
    try {
      const response = await fetch(`/api/knowledge-records/${task.id}/rating`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      task.rating = rating;
      like.disabled = true;
      dislike.disabled = true;
      (rating === "like" ? like : dislike).classList.add("selected");
      toast("已记录评价");
    } catch (requestError) {
      toast(`评价失败：${documentErrorMessage(requestError, "请稍后重试。")}`);
    }
  }

  async function loadDashboardStats() {
    try {
      const response = await fetch("/api/knowledge-stats");
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const stats = await response.json();
      setStatNumber("dash-total", stats.total_feedback, "");
      setStatNumber("dash-good", Math.round(stats.good_rate * 100), "%");
      setStatNumber("dash-ai", Math.round(stats.ai_good_rate * 100), "%");
      setBar("bar-kb-fill", "bar-kb-val", stats.good_rate, stats.like_count, stats.dislike_count);
      setBar("bar-ai-fill", "bar-ai-val", stats.ai_good_rate, stats.ai_like_count, stats.ai_dislike_count);
      renderStatsRows("dash-by-region", stats.by_region);
      renderStatsRows("dash-by-document", stats.by_document);
      animateStats();
    } catch {
      // 统计加载失败保留空态。
    }
  }

  function setStatNumber(cardId, value, suffix) {
    const element = document.getElementById(cardId);
    if (!element) return;
    element.dataset.target = String(value);
    element.dataset.suffix = suffix;
    element.textContent = `0${suffix}`;
  }

  function setBar(fillId, valId, rate, like, dislike) {
    const fill = document.getElementById(fillId);
    const val = document.getElementById(valId);
    if (!fill || !val) return;
    const percent = Math.round(rate * 100);
    fill.style.setProperty("--w", `${percent}%`);
    val.textContent = rate > 0 ? `${percent}% · ${like}👍 / ${dislike}👎` : "暂无评价";
  }

  function renderStatsRows(tableId, counts) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    if (!tbody) return;
    tbody.replaceChildren();
    if (!Array.isArray(counts) || !counts.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "暂无评价数据";
      row.appendChild(cell);
      tbody.appendChild(row);
      return;
    }
    counts.forEach((item) => {
      const goodRate = item.total ? Math.round((item.like / item.total) * 100) : 0;
      const rowClass = goodRate >= 80 ? "num-good" : goodRate >= 60 ? "num-mid" : "num-bad";
      const row = document.createElement("tr");
      const nameCell = document.createElement("td");
      nameCell.textContent = item.name;
      const likeCell = document.createElement("td");
      likeCell.textContent = `👍 ${item.like}`;
      const dislikeCell = document.createElement("td");
      dislikeCell.textContent = `👎 ${item.dislike}`;
      const totalCell = document.createElement("td");
      totalCell.textContent = String(item.total);
      const rateCell = document.createElement("td");
      const rateSpan = document.createElement("span");
      rateSpan.className = rowClass;
      rateSpan.textContent = `${goodRate}%`;
      rateCell.appendChild(rateSpan);
      row.append(nameCell, likeCell, dislikeCell, totalCell, rateCell);
      tbody.appendChild(row);
    });
  }

  async function homeRegion() {
    const query = regionInput.value.trim();
    if (!query) {
      knowledgeResults.hidden = true;
      toast("请输入要检索的地区或问题");
      return;
    }
    const generation = ++knowledgeRequestGeneration;
    knowledgeResults.hidden = false;
    knowledgeResults.replaceChildren();
    const loading = document.createElement("p");
    loading.textContent = "正在检索…";
    knowledgeResults.appendChild(loading);
    try {
      const response = await fetch("/api/knowledge-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, document_ids: [] }),
      });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const payload = await response.json();
      if (generation !== knowledgeRequestGeneration || activeView !== "guide") return;
      renderKnowledgeResults(Array.isArray(payload.results) ? payload.results : []);
      if (Array.isArray(payload.results) && payload.results.length) {
        const task = {
          id: payload.record_id || `k${++sequence}`,
          query: payload.query,
          answer: payload.answer,
          answerStatus: payload.answer_status,
          results: payload.results,
          rating: null,
        };
        addKnowledgeTask(task);
        const answerButton = document.createElement("button");
        answerButton.type = "button";
        answerButton.className = "answer-open-btn";
        answerButton.textContent = payload.answer ? "查看完整回答" : "生成完整回答";
        answerButton.addEventListener("click", () => {
          if (task.answer) {
            openAnswerModal(task);
          } else {
            generateAnswer(task, answerButton);
          }
        });
        knowledgeResults.appendChild(answerButton);
        if (!payload.answer) {
          generateAnswer(task, answerButton);
        }
        renderFeedback(task, knowledgeResults);
      }
    } catch (requestError) {
      if (generation !== knowledgeRequestGeneration || activeView !== "guide") return;
      knowledgeResults.replaceChildren();
      const message = document.createElement("p");
      message.textContent = `知识检索服务不可用：${documentErrorMessage(requestError, "请稍后重试。")}`;
      knowledgeResults.appendChild(message);
    }
  }

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
  ticketEntryDate.min = todayIso();
  hotelCheckIn.min = todayIso();
  hotelCheckOut.min = todayIso();

  startExperienceButton.addEventListener("click", startExperience);
  backToIntroButton.addEventListener("click", showIntro);
  newPlanButton.addEventListener("click", startNewPlan);
  form.addEventListener("submit", submitPlan);
  document.getElementById("plan-revision-submit")?.addEventListener("click", submitPlanRevision);
  ticketForm.addEventListener("submit", submitTicketSearch);
  hotelForm.addEventListener("submit", submitHotelSearch);
  documentUpload.addEventListener("change", uploadDocument);
  document.getElementById("intro").setAttribute("aria-hidden", "false");
  renderNav();
  setupTravelShowcase();
  loadKnowledgeRecords();
  updateKnowledgeFoot();
  window.startExperience = startExperience;
  window.showIntro = showIntro;
  window.showView = showView;
  window.closeFliggyConsent = closeFliggyConsent;
  window.acceptFliggyConsent = acceptFliggyConsent;
  window.renderNav = renderNav;
  window.resetPlanForm = resetPlanForm;
  window.toggleHistory = toggleHistory;
  window.selectTask = selectTask;
  window.clearTasks = clearTasks;
  window.confirmDelete = confirmDelete;
  window.closeConfirm = closeConfirm;
  window.doDelete = doDelete;
  window.closeAnswerModal = closeAnswerModal;
  window.openRecordsModal = openRecordsModal;
  window.closeRecordsModal = closeRecordsModal;
  window.closeTravelModal = closeTravelModal;
  window.openSettings = openSettings;
  window.closeSettings = closeSettings;
  window.saveSettings = saveSettings;
  window.homePlan = homePlan;
  window.homeRegion = homeRegion;
  window.loadDocuments = loadDocuments;
  window.deleteDocument = deleteDocument;
})();
