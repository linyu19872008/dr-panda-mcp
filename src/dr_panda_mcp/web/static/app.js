/*
 * DrPanda MCP 配置台脚本（无依赖、自托管、同源）。
 *
 * 约束（docs/verify/frontend-js-policy.md v3）：
 * 配置台交互需要 JavaScript。认证、CSRF、Host/Origin、字段校验、只读闸门仍只在服务端执行。
 * 请求只允许同源，且必须带 CSRF。
 */
(() => {
  "use strict";

  const body = document.body;
  const msg = (form, key) =>
    (form && form.dataset[key]) || (body && body.dataset[key]) || "";

  // 表单提交成功、或主动跳转（登录/安装完成/会话过期）前清掉未保存标记。
  // 否则 beforeunload 会把「保存后跳转」也当成放弃修改，弹出浏览器原生确认框。
  const clearUnsaved = (form) => {
    if (form instanceof HTMLFormElement) delete form.dataset.dirty;
  };

  // ---------------------------------------------------------------------
  // 原生 dialog（保持原有行为）
  // ---------------------------------------------------------------------
  const openDialog = (id) => {
    const dialog = document.getElementById(id);
    if (!dialog || typeof dialog.showModal !== "function") return false;
    if (dialog.open) dialog.close();
    dialog.showModal();
    return true;
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target instanceof Element ? event.target.closest("[data-dialog-open]") : null;
    if (!(trigger instanceof HTMLElement)) return;
    const id = trigger.dataset.dialogOpen;
    if (!id) return;
    // JS 不可用/不支持 dialog 时保留 href，走无 JS 回退页面。
    if (openDialog(id)) event.preventDefault();
  });

  document.querySelectorAll("[data-dialog-close]").forEach((control) => {
    control.addEventListener("click", (event) => {
      const dialog = control.closest("dialog");
      // 弹窗已经关闭时不要拦截链接，否则“返回列表”会变成死按钮。
      if (!dialog || !dialog.open) return;
      event.preventDefault();
      dialog.close();
      if (
        control.dataset.dialogClose === "navigate" &&
        control instanceof HTMLAnchorElement
      ) {
        window.location.assign(control.href);
      }
    });
  });

  // 服务端渲染的服务端结果默认带 open，脚本加载后转为真正的 modal。
  document.querySelectorAll("dialog.modal[data-open-on-load]").forEach((dialog) => {
    try {
      dialog.close();
      dialog.showModal();
    } catch (_) {
      // 保留 open 状态，至少内容可读。
    }
  });

  document.querySelectorAll("dialog.modal").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  const copyText = async (value) => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch (_) {
        // 权限被拒绝时改用选区复制。
      }
    }
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    area.remove();
    return ok;
  };

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) return;
    const source = document.getElementById(button.dataset.copyTarget || "");
    if (!source) return;
    const status = button.parentElement
      ? button.parentElement.querySelector("[data-copy-status]")
      : null;
    button.hidden = false;
    button.addEventListener("click", async () => {
      const value = source.textContent || "";
      const ok = await copyText(value);
      if (status) status.textContent = ok ? button.dataset.copied || "" : button.dataset.failed || "";
    });
  });

  // ---------------------------------------------------------------------
  // 普通表单提交加载态
  // ---------------------------------------------------------------------
  // 注意：提交按钮自身的 name/value 必须保住。表单数据在 submit 事件之后
  // 构造，被禁用的提交按钮不再算提交按钮，它的 name/value 会从请求体里消失
  // （“点测试连接变成保存”“完成安装不生效”都是这个原因）。
  // 这里先把 submitter 镜像成隐藏域，再禁用按钮，防重复提交与语义两不误。
  const mirrorSubmitter = (form, submitter) => {
    if (!submitter || !submitter.name) return;
    const mirror = document.createElement("input");
    mirror.type = "hidden";
    mirror.name = submitter.name;
    mirror.value = submitter.value;
    form.appendChild(mirror);
  };

  document.querySelectorAll("form[data-submit-loading]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      // 异步表单自行管理按钮状态，避免失败后按钮停留在禁用态。
      if (form.matches("[data-async-form]")) return;
      mirrorSubmitter(form, event.submitter);
      form.setAttribute("aria-busy", "true");
      form.querySelectorAll('button[type="submit"]').forEach((button) => {
        button.disabled = true;
        if (button.dataset.loadingLabel) button.textContent = button.dataset.loadingLabel;
      });
    });
  });

  // ---------------------------------------------------------------------
  // 同源 JSON 请求（渐进增强底座）
  // ---------------------------------------------------------------------
  class ApiError extends Error {
    constructor(kind, data) {
      super(kind);
      this.kind = kind;
      this.data = data || null;
    }
  }

  const formBody = (form, extra) => {
    const params = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
      if (typeof value === "string") params.append(key, value);
    });
    Object.entries(extra || {}).forEach(([key, value]) => params.set(key, value));
    return params;
  };

  const postForm = async (form, url, options = {}) => {
    const timeoutMs = options.timeoutMs || 25000;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        method: "POST",
        body: formBody(form, options.extra),
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      const type = response.headers.get("content-type") || "";
      let data = null;
      if (type.includes("application/json")) {
        try {
          data = await response.json();
        } catch (_) {
          data = null;
        }
      }
      if (!data || typeof data !== "object") throw new ApiError("bad_response", null);
      if (data.code === "UNAUTHORIZED") {
        clearUnsaved(form);
        window.location.assign(data.login || "/login");
        throw new ApiError("unauthorized", data);
      }
      if (!response.ok || !data.ok) throw new ApiError("rejected", data);
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error && error.name === "AbortError") throw new ApiError("timeout", null);
      throw new ApiError("network", null);
    } finally {
      window.clearTimeout(timer);
    }
  };

  const errorMessage = (form, error) => {
    if (error.kind === "timeout") return msg(form, "msgTimeout") || "请求超时，请稍后重试。";
    if (error.kind === "network") return msg(form, "msgNetwork") || "网络异常，请检查连接后重试。";
    if (error.kind === "expired") return msg(form, "msgExpired") || "页面已过期，请刷新后重试。";
    if (error.data && error.data.message) return error.data.message;
    return msg(form, "msgGeneric") || "操作失败，请稍后重试。";
  };

  const clearFieldErrors = (root) => {
    root.querySelectorAll("[data-field-error]").forEach((el) => el.remove());
    root.querySelectorAll('[aria-invalid="true"]').forEach((el) => {
      el.removeAttribute("aria-invalid");
      el.removeAttribute("aria-describedby");
    });
  };

  const applyFieldErrors = (root, errors) => {
    clearFieldErrors(root);
    let first = null;
    Object.entries(errors || {}).forEach(([key, message]) => {
      if (key === "_form") return;
      const input =
        root.querySelector(`[name="secret_${key}"]`) || root.querySelector(`[name="${key}"]`);
      if (!input) return;
      const container =
        input.closest(".field") ||
        input.closest(".settings-field-copy") ||
        input.closest(".settings-field-row") ||
        input.parentElement;
      input.setAttribute("aria-invalid", "true");
      const error = document.createElement("p");
      error.className = "field__error";
      error.dataset.fieldError = "1";
      error.setAttribute("role", "alert");
      error.textContent = message;
      if (container) container.appendChild(error);
      first = first || error;
    });
    if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
  };

  const focusResult = (element) => {
    if (!(element instanceof HTMLElement)) return;
    element.tabIndex = -1;
    try {
      element.focus({ preventScroll: true });
    } catch (_) {
      // 老浏览器不支持 preventScroll 时忽略。
    }
  };

  const setNotice = (element, tone, text) => {
    if (!element) return;
    element.hidden = false;
    element.className = `alert alert--${tone}`;
    const slot = element.querySelector("[data-notice-text]") || element.querySelector(".alert__body");
    if (slot) slot.textContent = text;
    focusResult(element);
  };

  const hideNotice = (element) => {
    if (!element) return;
    element.hidden = true;
  };

  const pageError = () => document.querySelector("[data-live-error]");

  const notifyError = (message) => setNotice(pageError(), "danger", message);

  // 按钮加载态：只有带 loading-label 的按钮才替换文案，且恢复时还原原始 child，
  // 避免把开关这类“图标 + 文字”按钮的内部结构写成纯文本。
  const busyStates = new WeakMap();
  const setButtonLabel = (button, text) => {
    const label = button.querySelector(".btn__label");
    if (label) label.textContent = text;
    else button.textContent = text;
  };

  const busyButton = (button, on) => {
    if (!button) return;
    if (on) {
      busyStates.set(button, { html: button.innerHTML, disabled: button.disabled });
      button.disabled = true;
      if (button.dataset.loadingLabel) setButtonLabel(button, button.dataset.loadingLabel);
      return;
    }
    const previous = busyStates.get(button);
    if (!previous) return;
    if (button.dataset.loadingLabel) button.innerHTML = previous.html;
    button.disabled = previous.disabled;
    busyStates.delete(button);
  };

  const updateStats = (stats) => {
    if (!stats) return;
    document.querySelectorAll("[data-stat]").forEach((el) => {
      const key = el.dataset.stat;
      if (typeof stats[key] !== "number") return;
      el.textContent = String(stats[key]);
      const card = el.closest(".stat");
      if (card && key === "failed") card.classList.toggle("stat--danger", stats[key] > 0);
      if (card && key === "key_issues") card.classList.toggle("stat--warning", stats[key] > 0);
    });
  };

  const handleApiError = (form, error) => {
    if (error.kind === "rejected" && error.data && error.data.errors) {
      applyFieldErrors(form, error.data.errors);
    }
    if (error.kind !== "unauthorized") notifyError(errorMessage(form, error));
  };

  // ---------------------------------------------------------------------
  // 目标新建/编辑：测试连接 → 保存门槛
  // ---------------------------------------------------------------------
  const initTargetForm = (form) => {
    const saveButton = form.querySelector("[data-save-button]");
    const probeButton = form.querySelector("[data-probe-button]");
    const hint = form.querySelector("[data-gate-hint]");
    const resultRegion = form.querySelector("[data-probe-result]");
    const alertBox = form.querySelector("[data-probe-alert]");
    const titleSlot = form.querySelector("[data-probe-title]");
    const detailSlot = form.querySelector("[data-probe-detail]");
    const metaSlot = form.querySelector("[data-probe-meta]");
    const probeTimeout = Number(form.dataset.probeTimeoutMs) || 25000;
    if (!saveButton || !probeButton) return;

    const hints = {
      pending: form.dataset.gateHintPending || "",
      clean: form.dataset.gateHintClean || "",
      saved: form.dataset.gateHintSaved || "",
      dirty: form.dataset.gateHintDirty || "",
    };
    const okTitle = form.dataset.probeOkTitle || "";
    const failTitle = form.dataset.probeFailTitle || "";
    const durationLabel = form.dataset.durationLabel || "";
    let tested = null;
    let busy = false;

    const gateControls = () =>
      Array.from(form.elements).filter((el) => {
        if (!(el instanceof HTMLElement)) return false;
        if (el.matches('[type="hidden"], [type="submit"], [type="button"], [type="reset"]')) {
          return false;
        }
        if (el.closest('[data-gate="off"]')) return false;
        return true;
      });

    const snapshot = () =>
      gateControls().map((el) => [
        el.name,
        el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value,
      ]);

    const baseline = form.dataset.gateBaseline === "saved" ? snapshot() : null;

    const isClean = () => {
      const current = JSON.stringify(snapshot());
      if (tested !== null && current === JSON.stringify(tested)) return "tested";
      if (baseline !== null && current === JSON.stringify(baseline)) return "saved";
      return "";
    };

    const refreshGate = () => {
      if (busy) return;
      const state = isClean();
      const clean = state !== "";
      saveButton.disabled = !clean;
      saveButton.setAttribute("aria-disabled", clean ? "false" : "true");
      if (!hint) return;
      if (state === "tested") hint.textContent = hints.clean;
      else if (state === "saved") hint.textContent = hints.saved;
      else if (tested !== null || baseline !== null) hint.textContent = hints.dirty;
      else hint.textContent = hints.pending;
    };

    const installSlot = form.querySelector("[data-probe-install]");
    const installForm = document.querySelector("[data-probe-install-form]");
    // The submit button lives in the main form; only the hidden fields live
    // in the external install form (nested forms are invalid HTML).
    const installButton = form.querySelector("[data-probe-install-button]");

    const renderResult = (tone, title, detail, showInstall = false) => {
      if (!resultRegion || !alertBox) return;
      resultRegion.hidden = false;
      alertBox.className = `alert alert--${tone}`;
      alertBox.setAttribute("role", tone === "danger" ? "alert" : "status");
      alertBox.querySelectorAll("[data-probe-icon]").forEach((icon) => {
        icon.hidden = icon.dataset.probeIcon !== (tone === "success" ? "ok" : "fail");
      });
      if (titleSlot) titleSlot.textContent = title || "";
      if (detailSlot) detailSlot.textContent = detail || "";
      if (metaSlot && tone !== "success") metaSlot.replaceChildren();
      if (installSlot) installSlot.hidden = !showInstall;
      focusResult(resultRegion);
    };

    const fillProbeMeta = (data) => {
      if (!metaSlot) return;
      metaSlot.replaceChildren();
      const instant = (data && (data.checked_at_instant || data.checked_at)) || "";
      if (instant) {
        const node = document.createElement("time");
        node.dataset.seconds = "true";
        if (!applyTime(node, instant, true)) node.textContent = String(data.checked_at || instant);
        metaSlot.append(node);
      }
      if (data && typeof data.duration_ms === "number") {
        if (metaSlot.childNodes.length) metaSlot.append(" · ");
        metaSlot.append(`${durationLabel} ${data.duration_ms} ms`);
      }
    };

    const setBusy = (value) => {
      busy = value;
      form.setAttribute("aria-busy", value ? "true" : "false");
      [probeButton, saveButton, installButton].forEach((button) => {
        if (button) button.disabled = value;
      });
    };

    const doProbe = async () => {
      if (busy) return;
      setBusy(true);
      const probeLabel = probeButton.textContent;
      probeButton.textContent = probeButton.dataset.loadingLabel || probeLabel;
      try {
        const data = await postForm(form, form.dataset.probeUrl, {
          timeoutMs: probeTimeout,
        });
        tested = snapshot();
        renderResult("success", okTitle, data.message || "");
        fillProbeMeta(data);
      } catch (error) {
        tested = null;
        if (error.kind === "rejected" && error.data && error.data.errors) {
          applyFieldErrors(form, error.data.errors);
        }
        renderResult(
          "danger",
          failTitle,
          errorMessage(form, error),
          Boolean(error.data && error.data.install_extra),
        );
      } finally {
        setBusy(false);
        probeButton.textContent = probeLabel;
        probeButton.disabled = false;
        refreshGate();
      }
    };

    const doInstall = async () => {
      if (busy || !installForm || !installButton) return;
      setBusy(true);
      busyButton(installButton, true);
      try {
        const data = await postForm(installForm, installForm.getAttribute("action"), {
          timeoutMs: 130000,
        });
        renderResult("success", data.message || okTitle, "");
        setBusy(false);
        busyButton(installButton, false);
        await doProbe();
        return;
      } catch (error) {
        renderResult(
          "danger",
          failTitle,
          errorMessage(installForm, error),
          Boolean(error.data && error.data.install_extra),
        );
      } finally {
        setBusy(false);
        busyButton(installButton, false);
      }
    };

    if (installForm) {
      installForm.addEventListener("submit", (event) => {
        event.preventDefault();
        doInstall();
      });
    }

    const doSave = async () => {
      if (busy || saveButton.disabled) return;
      setBusy(true);
      const saveLabel = saveButton.textContent;
      saveButton.textContent = saveButton.dataset.loadingLabel || saveLabel;
      try {
        const data = await postForm(form, form.getAttribute("action"));
        if (data.redirect) {
          clearUnsaved(form);
          window.location.assign(data.redirect);
          return;
        }
        clearUnsaved(form);
        window.location.reload();
      } catch (error) {
        if (error.kind === "rejected" && error.data) {
          const payload = error.data;
          if (payload.errors) applyFieldErrors(form, payload.errors);
          if (payload.phase === "probe") tested = null;
          renderResult(
            "danger",
            failTitle,
            payload.message || errorMessage(form, error),
            Boolean(payload.install_extra),
          );
        } else {
          renderResult("danger", failTitle, errorMessage(form, error));
        }
      } finally {
        setBusy(false);
        saveButton.textContent = saveLabel;
        refreshGate();
      }
    };

    probeButton.addEventListener("click", (event) => {
      event.preventDefault();
      doProbe();
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      doSave();
    });
    form.addEventListener("input", refreshGate);
    form.addEventListener("change", refreshGate);
    refreshGate();
  };

  // ---------------------------------------------------------------------
  // 列表行内动作：测试、启停
  // ---------------------------------------------------------------------
  const updateTestCell = (row, data) => {
    if (!row) return;
    const cell = row.querySelector("[data-test-cell]");
    if (!cell) return;
    const status = cell.querySelector("[data-test-status]");
    const label = cell.querySelector("[data-test-label]");
    const time = cell.querySelector("[data-test-time]");
    const details = cell.querySelector("[data-test-details]");
    const failed = data.test_ok === false;
    if (status) status.className = `status status--${failed ? "error" : "ok"}`;
    if (label) {
      label.textContent = failed ? label.dataset.error || "" : label.dataset.ok || "";
    }
    if (time) {
      const instant = data.tested_at || data.test_time;
      const shown = instant && applyTime(time, instant, false);
      if (!shown) time.textContent = data.test_time || "";
      time.hidden = !(shown || data.test_time);
    }
    if (details) renderTestError(details, data.test_error, data.test_command);
  };

  const renderTestError = (details, message, command) => {
    const box = details.querySelector("[data-test-error-box]");
    if (!box) return;
    const show = Boolean(message || command);
    details.hidden = !show;
    box.replaceChildren();
    if (!show) return;
    if (message) {
      const paragraph = document.createElement("p");
      paragraph.className = "details__message";
      paragraph.dataset.testMessage = "";
      paragraph.textContent = message;
      box.appendChild(paragraph);
    }
    const installId = command && details.dataset.installDialog;
    if (!installId) return;
    const line = document.createElement("div");
    line.className = "install-line";
    const install = document.createElement("button");
    install.type = "button";
    install.className = "btn btn--secondary btn--sm btn--stable";
    install.dataset.dialogOpen = installId;
    const installLabel = document.createElement("span");
    installLabel.className = "btn__label";
    installLabel.textContent = details.dataset.installLabel || "安装";
    install.append(installLabel);
    line.append(install);
    box.appendChild(line);
  };

  const rowFor = (form) => {
    const row = form.closest("tr");
    if (row) return row;
    const id = form.dataset.targetId;
    if (!id || typeof CSS === "undefined" || !CSS.escape) return null;
    return document.querySelector(`tr[data-target-id="${CSS.escape(id)}"]`);
  };

  const closeDialog = (form) => {
    const dialog = form.closest("dialog");
    if (dialog && dialog.open) dialog.close();
  };

  const updateToggle = (form, data) => {
    const button = form.querySelector("button");
    if (!button) return;
    button.classList.toggle("is-on", Boolean(data.enabled));
    button.setAttribute("aria-pressed", data.enabled ? "true" : "false");
    const label = button.querySelector(".switch__label-text");
    if (label) label.textContent = data.label || "";
    const title = data.enabled ? button.dataset.onTitle : button.dataset.offTitle;
    if (title) button.title = title;
    const action = form.getAttribute("action") || "";
    if (/\/(enable|disable)$/.test(action)) {
      form.setAttribute(
        "action",
        action.replace(/\/(enable|disable)$/, data.enabled ? "/disable" : "/enable"),
      );
    }
  };

  const initRowActions = () => {
    document.querySelectorAll("[data-row-action]").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (form.dataset.busy) return;
        const button = form.querySelector('button[type="submit"]');
        if (!button) return;
        const row = rowFor(form);
        form.dataset.busy = "1";
        busyButton(button, true);
        const timeoutMs = Number(form.dataset.timeoutMs);
        const options = Number.isFinite(timeoutMs) && timeoutMs > 0 ? { timeoutMs } : {};
        try {
          const data = await postForm(form, form.getAttribute("action"), options);
          updateStats(data.stats);
          if (form.dataset.rowAction === "test" || form.dataset.rowAction === "install") {
            updateTestCell(row, data);
          } else if (form.dataset.rowAction === "toggle") updateToggle(form, data);
          if (form.dataset.rowAction === "install") closeDialog(form);
          hideNotice(pageError());
        } catch (error) {
          if (error.data && (error.data.test_error || error.data.test_command)) {
            updateTestCell(row, error.data);
            updateStats(error.data.stats);
          }
          if (form.dataset.rowAction === "install") closeDialog(form);
          handleApiError(form, error);
        } finally {
          delete form.dataset.busy;
          busyButton(button, false);
        }
      });
    });
  };

  // ---------------------------------------------------------------------
  // 系统配置：保存本组
  // ---------------------------------------------------------------------
  const initSettingsForm = (form) => {
    const notice = document.querySelector("[data-settings-notice]");
    const submit = form.querySelector('button[type="submit"]');
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.busy) return;
      form.dataset.busy = "1";
      busyButton(submit, true);
      try {
        const data = await postForm(form, form.getAttribute("action"));
        clearFieldErrors(form);
        clearUnsaved(form);
        setNotice(notice, "success", data.message || "");
        hideNotice(pageError());
      } catch (error) {
        if (error.kind === "rejected" && error.data && error.data.errors) {
          applyFieldErrors(form, error.data.errors);
        }
        if (error.kind !== "unauthorized") {
          setNotice(notice, "danger", errorMessage(form, error));
        }
      } finally {
        delete form.dataset.busy;
        busyButton(submit, false);
      }
    });
  };

  // ---------------------------------------------------------------------
  // 登录 / 修改密码：内联错误，成功后跳转
  // ---------------------------------------------------------------------
  const initRedirectForm = (form, noticeElement) => {
    const submit = form.querySelector('button[type="submit"]');
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.dataset.busy) return;
      form.dataset.busy = "1";
      busyButton(submit, true);
      hideNotice(noticeElement);
      try {
        const data = await postForm(form, form.getAttribute("action"));
        clearUnsaved(form);
        window.location.assign(data.redirect || "/");
      } catch (error) {
        if (error.kind === "unauthorized") return;
        setNotice(noticeElement, "danger", errorMessage(form, error));
      } finally {
        delete form.dataset.busy;
        busyButton(submit, false);
      }
    });
  };

  // ---------------------------------------------------------------------
  // 安装向导：测试连接 → 完成安装
  // ---------------------------------------------------------------------
  const initSetupForm = (form) => {
    const result = document.querySelector("[data-setup-result]");
    const finish = form.querySelector('[data-setup-action="finish"]');
    const test = form.querySelector('[data-setup-action="test"]');
    let baseline = formBody(form).toString();
    let tested = Boolean(finish && finish.dataset.canFinish === "true");

    const refresh = () => {
      if (!finish) return;
      const ready = tested && formBody(form).toString() === baseline;
      finish.disabled = !ready;
      finish.setAttribute("aria-disabled", ready ? "false" : "true");
    };

    const run = async (button, action) => {
      if (form.dataset.busy) return;
      form.dataset.busy = "1";
      busyButton(button, true);
      try {
        const data = await postForm(form, form.getAttribute("action"), { extra: { action } });
        if (data.redirect) {
          clearUnsaved(form);
          window.location.assign(data.redirect);
          return;
        }
        setNotice(result, "success", data.message || "");
        if (action === "test" && data.can_finish) {
          baseline = formBody(form).toString();
          tested = true;
        }
      } catch (error) {
        if (error.kind === "unauthorized") return;
        setNotice(result, "danger", errorMessage(form, error));
        if (action === "test") tested = false;
      } finally {
        delete form.dataset.busy;
        busyButton(button, false);
        refresh();
      }
    };

    test?.addEventListener("click", (event) => {
      event.preventDefault();
      run(test, "test");
    });
    form.addEventListener("input", refresh);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (finish && finish.disabled) return;
      run(finish, "finish");
    });
    refresh();
  };

  const initThemeSwitch = () => {
    const form = document.querySelector("form.theme-switch");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = event.submitter;
      if (!(button instanceof HTMLButtonElement)) return;
      const root = document.documentElement;
      const previousTheme = root.getAttribute("data-theme");
      const buttons = Array.from(form.querySelectorAll("button"));
      const previousPressed = buttons.map((item) => item.getAttribute("aria-pressed"));
      const mode = button.value;
      if (mode === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", mode);
      buttons.forEach((item) => {
        const on = item === button;
        item.classList.toggle("is-active", on);
        item.setAttribute("aria-pressed", on ? "true" : "false");
      });
      try {
        await postForm(form, form.getAttribute("action"), { extra: { mode } });
      } catch (_) {
        if (previousTheme) root.setAttribute("data-theme", previousTheme);
        else root.removeAttribute("data-theme");
        buttons.forEach((item, index) => {
          const pressed = previousPressed[index] === "true";
          item.classList.toggle("is-active", pressed);
          item.setAttribute("aria-pressed", pressed ? "true" : "false");
        });
      }
    });
  };

  const initLeaveGuard = () => {
    const message = (body && body.dataset.msgDirty) || "";
    // 与页面初始值比较，只有真的改了才标记「未保存」：改回原值会撤销标记。
    const fingerprint = (form) => {
      const params = new URLSearchParams();
      new FormData(form).forEach((value, key) => {
        if (typeof value === "string") params.append(key, value);
      });
      return params.toString();
    };
    document.querySelectorAll("[data-leave-guard]").forEach((form) => {
      const baseline = fingerprint(form);
      const refresh = () => {
        if (fingerprint(form) === baseline) delete form.dataset.dirty;
        else form.dataset.dirty = "1";
      };
      form.addEventListener("input", refresh);
      form.addEventListener("change", refresh);
    });
    const dirtyForm = () => document.querySelector('[data-leave-guard][data-dirty="1"]');
    const allow = () => {
      const form = dirtyForm();
      if (!form) return true;
      if (window.confirm(message)) {
        delete form.dataset.dirty;
        return true;
      }
      return false;
    };
    document.addEventListener("click", (event) => {
      const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(link instanceof HTMLAnchorElement)) return;
      if (link.target === "_blank" || link.hasAttribute("download")) return;
      if (link.hasAttribute("data-dialog-open")) return;
      const href = link.getAttribute("href") || "";
      if (!href || href.startsWith("#")) return;
      if (!allow()) event.preventDefault();
    });
    document.querySelectorAll("form.lang-switch").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (!allow()) event.preventDefault();
      });
    });
    window.addEventListener("beforeunload", (event) => {
      if (!dirtyForm()) return;
      event.preventDefault();
      event.returnValue = "";
    });
  };

  // ---------------------------------------------------------------------
  // 钟面时间：库存是 UTC，显示换成浏览器本地时区，悬停保留 UTC。
  // ---------------------------------------------------------------------
  const padTime = (value) => String(value).padStart(2, "0");

  const formatClock = (date, seconds, utc) => {
    const year = utc ? date.getUTCFullYear() : date.getFullYear();
    const month = padTime((utc ? date.getUTCMonth() : date.getMonth()) + 1);
    const day = padTime(utc ? date.getUTCDate() : date.getDate());
    const hour = padTime(utc ? date.getUTCHours() : date.getHours());
    const minute = padTime(utc ? date.getUTCMinutes() : date.getMinutes());
    const second = padTime(utc ? date.getUTCSeconds() : date.getSeconds());
    const clock = seconds ? `${hour}:${minute}:${second}` : `${hour}:${minute}`;
    return `${year}-${month}-${day} ${clock}${utc ? " UTC" : ""}`;
  };

  const parseInstant = (value) => {
    if (!value) return null;
    const labeled = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))? UTC$/.exec(value);
    if (labeled) {
      return new Date(Date.UTC(+labeled[1], +labeled[2] - 1, +labeled[3], +labeled[4], +labeled[5], +(labeled[6] || 0)));
    }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  const applyTime = (node, instant, seconds) => {
    const date = parseInstant(instant);
    if (!date) return false;
    const withSeconds = Boolean(seconds);
    node.textContent = formatClock(date, withSeconds, false);
    node.title = formatClock(date, withSeconds, true);
    if ("dateTime" in node) node.dateTime = date.toISOString().replace(/\.\d{3}Z$/, "Z");
    return true;
  };

  const applyLocalTimes = (root) => {
    (root || document).querySelectorAll("time[datetime]").forEach((node) => {
      if (!node.dateTime) return;
      applyTime(node, node.dateTime, node.dataset.seconds === "true");
    });
  };

  // 目标表单里新建环境：保存后写进所属环境下拉，已填的连接留在原页。
  const applyCreatedEnvironment = (data) => {
    const field = document.querySelector("[data-environment-field]");
    if (!field || !data || !Array.isArray(data.environments)) return;
    let select = field.querySelector('select[name="environment"]');
    if (!select) {
      select = document.createElement("select");
      select.className = "input select";
      select.id = "field-environment";
      select.name = "environment";
      select.required = true;
      select.setAttribute("aria-required", "true");
      select.dataset.gate = "off";
      const label = field.querySelector(".field__label");
      if (label && label.tagName === "SPAN") {
        const next = document.createElement("label");
        next.className = label.className;
        next.htmlFor = select.id;
        next.innerHTML = label.innerHTML;
        if (!next.querySelector(".required")) {
          const star = document.createElement("span");
          star.className = "required";
          star.setAttribute("aria-hidden", "true");
          star.textContent = "*";
          next.appendChild(star);
        }
        label.replaceWith(next);
      }
      const readonly = field.querySelector("[data-environment-label]");
      if (readonly) readonly.replaceWith(select);
      else field.insertBefore(select, field.querySelector(".field__hint"));
      field.querySelectorAll('input[type="hidden"][name="environment"]').forEach((node) => {
        node.remove();
      });
      const link = field.querySelector('[data-dialog-open="env-drawer"]');
      if (link) link.remove();
    }
    select.replaceChildren();
    data.environments.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = item.label;
      option.selected = item.key === data.environment;
      select.appendChild(option);
    });
    const targetForm = document.querySelector("[data-target-form]");
    if (targetForm instanceof HTMLFormElement) targetForm.dataset.dirty = "1";
  };

  const initEnvCreate = () => {
    const form = document.querySelector("form[data-env-create]");
    if (!(form instanceof HTMLFormElement)) return;
    const notice = form.querySelector("[data-env-error]");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button =
        event.submitter instanceof HTMLButtonElement
          ? event.submitter
          : form.querySelector('button[type="submit"]');
      busyButton(button, true);
      clearFieldErrors(form);
      hideNotice(notice);
      try {
        const data = await postForm(form, form.getAttribute("action") || "/environments");
        applyCreatedEnvironment(data);
        form.reset();
        const dialog = form.closest("dialog");
        if (dialog instanceof HTMLDialogElement && dialog.open) dialog.close();
      } catch (error) {
        if (error.kind === "unauthorized") return;
        const errors = error.data && error.data.errors;
        if (errors) applyFieldErrors(form, errors);
        const formMessage = errors && errors._form;
        if (formMessage) setNotice(notice, "danger", formMessage);
        else if (!errors) setNotice(notice, "danger", errorMessage(form, error));
      } finally {
        busyButton(button, false);
      }
    });
  };

  // ---------------------------------------------------------------------
  // 初始化
  // ---------------------------------------------------------------------
  try {
    applyLocalTimes(document);
    initEnvCreate();
    const targetForm = document.querySelector("[data-target-form]");
    if (targetForm) initTargetForm(targetForm);
    initRowActions();
    const settingsForm = document.querySelector("[data-settings-form]");
    if (settingsForm) initSettingsForm(settingsForm);
    const loginForm = document.querySelector("[data-login-form]");
    if (loginForm) initRedirectForm(loginForm, document.querySelector("[data-login-error]"));
    const passwordForm = document.querySelector("[data-password-form]");
    if (passwordForm) {
      initRedirectForm(passwordForm, document.querySelector("[data-password-error]"));
    }
    const setupForm = document.querySelector("[data-setup-form]");
    if (setupForm) initSetupForm(setupForm);
    initThemeSwitch();
    initLeaveGuard();
  } catch (error) {
    // 脚本失败时保持普通表单可用：把被脚本禁用的按钮恢复。
    document.querySelectorAll("button[disabled][data-save-button]").forEach((button) => {
      button.disabled = false;
    });
    if (window.console && window.console.error) window.console.error(error);
  }
})();

// 错误页/表单回到浏览器时，把焦点放到第一个错误字段。
(() => {
  const invalid = document.querySelector('[aria-invalid="true"]');
  if (invalid instanceof HTMLElement) invalid.focus();
})();

// TLS 条件显示：仅在启用 TLS 时展示 CA/mTLS 字段。
// 无 JS 时高级区仍显示全部字段，由服务端做最终校验。
(() => {
  const checkbox = document.querySelector('input[name="ssl"], input[name="tls"]');
  const protocol = document.querySelector('select[name="security_protocol"]');
  if (!checkbox && !protocol) return;
  const names = ["ca_pem", "secret_client_cert", "secret_client_key"];
  const fields = names
    .map((name) => document.querySelector(`[name="${name}"]`)?.closest(".field"))
    .filter(Boolean);
  if (!fields.length) return;
  const enabled = () => {
    if (checkbox) return checkbox.checked;
    return protocol?.value === "SSL" || protocol?.value === "SASL_SSL";
  };
  const apply = () => {
    const on = enabled();
    fields.forEach((field) => {
      if (field.querySelector(".field--invalid")) return;
      field.hidden = !on;
    });
  };
  checkbox?.addEventListener("change", apply);
  protocol?.addEventListener("change", apply);
  apply();
})();

// Mongo 只显示当前认证方式用到的字段。隐藏字段去掉 required，避免挡住提交。
(() => {
  const mode = document.querySelector('select[name="auth_mode"]');
  if (!mode) return;
  const groups = {
    none: ["user", "auth_source", "secret_uri", "secret_password"],
    password: ["secret_uri"],
    uri: ["host", "port", "user", "auth_source", "secret_password"],
  };
  const names = ["host", "port", "user", "auth_source", "secret_uri", "secret_password"];
  const apply = (clearHidden) => {
    const hide = new Set(groups[mode.value] || []);
    names.forEach((name) => {
      const input = document.querySelector(`[name="${name}"]`);
      const field = input && input.closest(".field");
      if (!input || !field) return;
      const hidden = hide.has(name);
      field.hidden = hidden;
      if (hidden) {
        input.removeAttribute("required");
        input.removeAttribute("aria-required");
        if (clearHidden && input.type !== "checkbox") input.value = "";
      }
    });
  };
  mode.addEventListener("change", () => apply(true));
  apply(false);
})();

// Progressive disclosure: fields with data-show-when="control:value".
(() => {
  const fields = Array.from(document.querySelectorAll("[data-show-when]"));
  if (!fields.length) return;
  const parse = (raw) => {
    const index = raw.indexOf(":");
    if (index <= 0) return null;
    return { name: raw.slice(0, index), value: raw.slice(index + 1) };
  };
  const apply = () => {
    fields.forEach((field) => {
      const rule = parse(field.dataset.showWhen || "");
      if (!rule) return;
      const control = document.querySelector(`[name="${rule.name}"]`);
      if (!(control instanceof HTMLElement)) return;
      const current =
        control instanceof HTMLInputElement && control.type === "checkbox"
          ? control.checked
            ? "on"
            : "off"
          : control.value;
      const visible = current === rule.value;
      field.hidden = !visible;
      if (!visible && !field.querySelector(".field--invalid")) {
        field.querySelectorAll("input, textarea, select").forEach((input) => {
          input.removeAttribute("required");
          input.removeAttribute("aria-required");
        });
      }
    });
  };
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.name) return;
    if (fields.some((field) => (field.dataset.showWhen || "").startsWith(`${target.name}:`))) {
      apply();
    }
  });
  apply();
})();

// Nacos: warn when api_version=v3 and scope mode is all.
(() => {
  const form = document.querySelector("form[data-target-form]");
  const api = document.querySelector('select[name="api_version"]');
  const dataScope = document.querySelector('select[name="data_scope"]');
  const serviceScope = document.querySelector('select[name="service_scope"]');
  if (!form || !api || (!dataScope && !serviceScope)) return;
  const ensureHint = (select) => {
    if (!(select instanceof HTMLSelectElement)) return null;
    const field = select.closest(".field");
    if (!field) return null;
    let hint = field.querySelector("[data-nacos-v3-hint]");
    if (!hint) {
      hint = document.createElement("p");
      hint.className = "field__hint field__hint--warn";
      hint.dataset.nacosV3Hint = "true";
      field.append(hint);
    }
    return hint;
  };
  const apply = () => {
    const isV3 = api.value === "v3";
    [
      [dataScope, form.dataset.nacosV3DataHint || ""],
      [serviceScope, form.dataset.nacosV3ServiceHint || ""],
    ].forEach(([select, message]) => {
      const hint = ensureHint(select);
      if (!hint) return;
      const show = isV3 && select && select.value === "all";
      hint.hidden = !show;
      hint.textContent = show ? message : "";
    });
  };
  [api, dataScope, serviceScope].forEach((el) => el && el.addEventListener("change", apply));
  apply();
})();

// Audit filters: changing a select submits immediately (chips already navigate).
(() => {
  document.querySelectorAll("form[data-auto-submit]").forEach((form) => {
    form.querySelectorAll("[data-auto-submit-control]").forEach((control) => {
      control.addEventListener("change", () => {
        if (typeof form.requestSubmit === "function") form.requestSubmit();
        else form.submit();
      });
    });
  });
})();
