const statusIcons = {
  pending: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5l3.2 1.9"/></svg>`,
  rejected: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6m0-6-6 6"/></svg>`,
  disabled: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 20v-1.5a5.5 5.5 0 0 1 11 0V20M11 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="m17 9 4 4m0-4-4 4"/></svg>`,
};

function renderAuthFrame(content, modifier = "") {
  return `
    <main class="auth-page ${modifier}">
      <section class="auth-shell" aria-label="跟单管理系统账号访问">
        <header class="auth-brand">
          <img src="./assets/logos/logo-compact-ktk.jpg" alt="KOCOTREE" />
          <div>
            <strong>跟单管理系统</strong>
            <span>订单与发货协同管理</span>
          </div>
        </header>
        ${content}
      </section>
      <p class="auth-page__footer">浙江酷趣智能科技有限公司 · 内部系统</p>
    </main>`;
}

export function renderLoginPage() {
  return renderAuthFrame(`
    <div class="auth-card auth-card--login" data-auth-panel>
      <div class="auth-card__heading">
        <h1>登录跟单管理系统</h1>
        <p>使用公司飞书账号识别身份并进入系统</p>
      </div>
      <button class="auth-primary-button auth-primary-button--feishu" type="button" data-feishu-login>
        <span data-login-label>通过飞书登录</span>
      </button>
      <p class="auth-feedback" aria-live="polite" data-login-feedback></p>
    </div>
  `, "auth-page--login");
}

export function bindLoginPage() {
  const button = document.querySelector("[data-feishu-login]");
  const label = document.querySelector("[data-login-label]");
  const panel = document.querySelector("[data-auth-panel]");
  const feedback = document.querySelector("[data-login-feedback]");
  if (!button || !label || !panel || !feedback) return;

  button.addEventListener("click", () => {
    button.disabled = true;
    panel.setAttribute("aria-busy", "true");
    label.textContent = "正在识别飞书身份…";
    feedback.textContent = "正在读取当前飞书用户信息";
    window.setTimeout(() => {
      window.location.hash = "/admin-apply";
    }, 750);
  });
}

export function renderAdminApplyPage() {
  return renderAuthFrame(`
    <form class="auth-card auth-card--apply" data-admin-apply-form novalidate>
      <div class="auth-card__heading auth-card__heading--compact">
        <h1>管理员申请</h1>
      </div>

      <div class="auth-identity">
        <span class="auth-avatar" aria-hidden="true">煎</span>
        <div>
          <span>飞书用户</span>
          <strong>煎饼</strong>
        </div>
        <span class="auth-identity__state">身份已识别</span>
      </div>

      <div class="auth-field">
        <label for="apply-phone">手机号</label>
        <input id="apply-phone" name="phone" type="tel" inputmode="numeric" maxlength="11" autocomplete="tel" placeholder="请输入本人手机号" />
      </div>

      <div class="auth-field">
        <label for="apply-code">验证码</label>
        <div class="auth-code-row">
          <input id="apply-code" name="code" type="text" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="请输入 6 位验证码" />
          <button class="auth-secondary-button" type="button" data-send-code>获取验证码</button>
        </div>
      </div>

      <p class="auth-form-message" aria-live="polite" data-form-message></p>
      <button class="auth-primary-button" type="submit">提交申请</button>
    </form>
  `, "auth-page--apply");
}

function isValidPhone(phone) {
  return /^1\d{10}$/.test(phone);
}

export function bindAdminApplyPage() {
  const form = document.querySelector("[data-admin-apply-form]");
  const phoneInput = document.querySelector("#apply-phone");
  const codeInput = document.querySelector("#apply-code");
  const sendButton = document.querySelector("[data-send-code]");
  const message = document.querySelector("[data-form-message]");
  if (!form || !phoneInput || !codeInput || !sendButton || !message) return;

  const setMessage = (text, tone = "") => {
    message.textContent = text;
    message.dataset.tone = tone;
  };

  [phoneInput, codeInput].forEach((input) => {
    input.addEventListener("input", () => {
      input.value = input.value.replace(/\D/g, "");
      setMessage("");
    });
  });

  sendButton.addEventListener("click", () => {
    if (!isValidPhone(phoneInput.value)) {
      setMessage("请输入正确的 11 位手机号", "danger");
      phoneInput.focus();
      return;
    }

    let seconds = 60;
    sendButton.disabled = true;
    sendButton.textContent = `${seconds}s 后重新获取`;
    setMessage(`验证码已发送至 ${phoneInput.value.slice(0, 3)}****${phoneInput.value.slice(-4)}，原型中输入任意 6 位数字即可`, "success");
    const countdown = window.setInterval(() => {
      seconds -= 1;
      sendButton.textContent = seconds > 0 ? `${seconds}s 后重新获取` : "重新获取";
      if (seconds <= 0) {
        window.clearInterval(countdown);
        sendButton.disabled = false;
      }
    }, 1000);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!isValidPhone(phoneInput.value)) {
      setMessage("请输入正确的 11 位手机号", "danger");
      phoneInput.focus();
      return;
    }
    if (!/^\d{6}$/.test(codeInput.value)) {
      setMessage("请输入 6 位验证码", "danger");
      codeInput.focus();
      return;
    }
    window.location.hash = "/access-status/pending";
  });
}

const statusContent = {
  pending: {
    eyebrow: "申请已提交",
    title: "等待审核",
    description: "",
    detailLabel: "当前状态",
    detailValue: "待审核",
    action: "刷新审核状态",
  },
  rejected: {
    eyebrow: "申请未通过",
    title: "管理员申请已被拒绝",
    description: "拒绝原因：申请信息未核实，请确认手机号后重新提交。",
    detailLabel: "审核结果",
    detailValue: "已拒绝",
    action: "重新申请",
  },
  disabled: {
    eyebrow: "无法进入系统",
    title: "当前账号已停用",
    description: "该飞书账号暂无访问权限，请联系最高管理员处理。",
    detailLabel: "账号状态",
    detailValue: "已停用",
    action: "",
  },
};

export function renderAccessStatusPage(status) {
  const content = statusContent[status] ?? statusContent.pending;
  return renderAuthFrame(`
    <div class="auth-card auth-card--status is-${status}" data-status-panel>
      <span class="auth-status-icon">${statusIcons[status] ?? statusIcons.pending}</span>
      <div class="auth-card__heading auth-card__heading--status">
        <p class="auth-eyebrow">${content.eyebrow}</p>
        <h1>${content.title}</h1>
        ${content.description ? `<p>${content.description}</p>` : ""}
      </div>
      <dl class="auth-status-detail">
        <div><dt>飞书用户</dt><dd>煎饼</dd></div>
        <div><dt>${content.detailLabel}</dt><dd>${content.detailValue}</dd></div>
      </dl>
      ${content.action ? `<button class="auth-primary-button" type="button" data-status-action>${content.action}</button>` : ""}
      <p class="auth-feedback" aria-live="polite" data-status-feedback></p>
    </div>
  `, `auth-page--status auth-page--${status}`);
}

export function bindAccessStatusPage(status) {
  const action = document.querySelector("[data-status-action]");
  const feedback = document.querySelector("[data-status-feedback]");
  if (!action) return;

  action.addEventListener("click", () => {
    if (status === "rejected") {
      window.location.hash = "/admin-apply";
      return;
    }
    action.disabled = true;
    action.textContent = "正在刷新…";
    window.setTimeout(() => {
      action.disabled = false;
      action.textContent = "刷新审核状态";
      if (feedback) feedback.textContent = "当前仍为待审核状态";
    }, 650);
  });
}
