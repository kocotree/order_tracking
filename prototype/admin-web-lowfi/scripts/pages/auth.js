const statusIcons = {
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
      window.location.hash = "/dashboard";
    }, 750);
  });
}

const statusContent = {
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
  const content = statusContent[status] ?? statusContent.disabled;
  return renderAuthFrame(`
    <div class="auth-card auth-card--status is-${status}" data-status-panel>
      <span class="auth-status-icon">${statusIcons[status] ?? statusIcons.disabled}</span>
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

export function bindAccessStatusPage() {
  // 无权限页只做提示，没有可执行操作。
}
