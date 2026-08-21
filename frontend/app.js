(() => {
  const form = document.querySelector("#travel-form");
  const status = document.querySelector("#status");
  const error = document.querySelector("#error");
  const result = document.querySelector("#result");
  const markdown = document.querySelector("#markdown");
  const warnings = document.querySelector("#warnings");
  const sources = document.querySelector("#sources");
  const degraded = document.querySelector("#degraded");
  const departureInput = form.querySelector("input[name=departure_date]");
  const submit = form.querySelector("button[type=submit]");

  function todayIso() {
    const today = new Date();
    const month = String(today.getMonth() + 1).padStart(2, "0");
    const day = String(today.getDate()).padStart(2, "0");
    return `${today.getFullYear()}-${month}-${day}`;
  }

  departureInput.min = todayIso();

  function setTextList(element, values, emptyText) {
    const nodes = (values && values.length ? values : [emptyText]).map((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      return item;
    });
    element.replaceChildren(...nodes);
  }

  function setError(message) {
    error.textContent = message;
    error.hidden = false;
    result.hidden = true;
  }

  function renderDocument(documentData) {
    const parsed = marked.parse(documentData.markdown || "");
    const clean = DOMPurify.sanitize(parsed, {
      FORBID_TAGS: ["script", "style", "svg", "math"],
      FORBID_ATTR: [/^on/i],
    });
    markdown.innerHTML = clean;
    setTextList(warnings, documentData.warnings, "暂无待核验事项");
    setTextList(sources, (documentData.sources || []).map((source) => {
      const updated = source.source_updated_at ? `（更新时间：${source.source_updated_at}）` : "";
      return `${source.name}${updated}`;
    }), "暂无来源信息");
    setTextList(degraded, (documentData.degraded_agents || []).map((agent) => `${agent}：结果已降级，请核验"待核验事项"。"`), documentData.status === "failed" ? "规划生成失败，以下内容仅供核验。" : "当前结果未标记为降级");
    error.hidden = true;
    result.hidden = false;
  }

  function requestBody(formData) {
    const body = Object.fromEntries(formData.entries());
    const departure = new Date(`${body.departure_date}T00:00:00`);
    const today = new Date(`${todayIso()}T00:00:00`);
    if (!body.departure_date || Number.isNaN(departure.getTime()) || departure < today) {
      throw new Error("出行日期不得早于今天。");
    }
    const travelers = Number(body.travelers);
    const days = Number(body.days);
    const budget = body.budget === "" ? undefined : Number(body.budget);
    if (!Number.isInteger(travelers) || travelers < 1 || travelers > 20) {
      throw new Error("出行人数必须是 1 至 20 的整数。");
    }
    if (!Number.isInteger(days) || days < 1 || days > 14) {
      throw new Error("出行天数必须是 1 至 14 的整数。");
    }
    if (budget !== undefined && (!Number.isFinite(budget) || !Number.isInteger(budget) || budget < 0 || budget > 200000)) {
      throw new Error("预算必须是 0 至 200000 的整数。");
    }
    body.travelers = travelers;
    body.days = days;
    if (budget === undefined) delete body.budget;
    else body.budget = budget;
    body.preferences = body.preferences ? body.preferences.split(",").map((item) => item.trim()).filter(Boolean) : [];
    return body;
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

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "正在生成旅行规划…";
    error.hidden = true;
    submit.disabled = true;
    try {
      const body = requestBody(new FormData(form));
      const response = await fetch("/api/travel-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await nonOkMessage(response));
      const documentData = await response.json();
      renderDocument(documentData);
      if (documentData.status === "failed") {
        status.textContent = "规划生成失败，页面内容仅供核验。";
      } else if (documentData.status === "degraded") {
        status.textContent = "规划已生成，部分信息需要核验。";
      } else if (documentData.status === "success") {
        status.textContent = "规划已生成。";
      } else {
        status.textContent = "规划状态无法确认，请核验页面内容。";
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "请求失败，请稍后重试。");
      status.textContent = "";
    } finally {
      submit.disabled = false;
    }
  });
})();
