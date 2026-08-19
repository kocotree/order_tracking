(function registerAuthPage() {
  const statusContent = {
    identifying: {
      mark: "…",
      tone: "identifying",
      title: "正在识别身份",
      description: "正在通过微信身份确认管理员账号，请稍候。",
      note: "身份识别完成后将自动进入下一步",
    },
    pending: {
      mark: "审",
      tone: "pending",
      title: "管理员申请审核中",
      description: "已匹配到网页端提交的管理员申请，审核通过后即可使用小程序。",
      note: "请等待最高管理员审核",
    },
    rejected: {
      mark: "驳",
      tone: "rejected",
      title: "管理员申请未通过",
      description: "已匹配到未通过的管理员申请，小程序内不能重新提交申请。",
      note: "请前往管理员网页端重新申请",
    },
    unmatched: {
      mark: "!",
      tone: "unmatched",
      title: "未找到管理员申请",
      description: "当前手机号没有匹配到网页端已验证的管理员申请。",
      note: "请先前往管理员网页端提交申请",
    },
    ambiguous: {
      mark: "!",
      tone: "ambiguous",
      title: "无法绑定管理员账号",
      description: "当前手机号无法唯一匹配管理员账号，系统不会自动合并身份。",
      note: "请联系最高管理员处理",
    },
    disabled: {
      mark: "停",
      tone: "disabled",
      title: "账号已停用",
      description: "已匹配的管理员账号当前处于停用状态，暂时无法查看业务数据。",
      note: "如需恢复使用，请联系最高管理员",
    },
    "logged-out": {
      mark: "退",
      tone: "logged-out",
      title: "已退出登录",
      description: "当前登录会话已结束，微信与管理员账号的绑定仍然保留。",
      note: "重新登录不会再次授权手机号",
    },
  };

  function renderBrand() {
    return `
      <div class="auth-brand" aria-label="KOCOTREE 订单管理系统">
        <div class="auth-brand__wordmark">KOCOTREE</div>
        <p>订单管理系统</p>
      </div>
    `;
  }

  function renderBinding() {
    return `
      <section class="auth-card auth-card--binding">
        <div class="auth-card__symbol" aria-hidden="true">绑</div>
        <div class="auth-card__heading">
          <p>管理员入口</p>
          <h1>绑定管理员账号</h1>
          <span>请授权网页端申请时使用的手机号，用于匹配并绑定同一管理员账号。</span>
        </div>
        <div class="auth-binding-points" aria-label="绑定说明">
          <p><i>1</i><span>管理员申请仅在网页端提交</span></p>
          <p><i>2</i><span>网页申请与微信手机号必须一致</span></p>
        </div>
        <button type="button" class="auth-primary-button" data-bind-phone>授权手机号并绑定</button>
        <p class="auth-card__note">点击后将调用微信手机号授权</p>
      </section>
    `;
  }

  function renderStatus(status) {
    const content = statusContent[status];
    const action = status === "pending"
      ? `<button type="button" class="auth-primary-button" data-auth-refresh>刷新状态</button>`
      : status === "logged-out"
        ? `<button type="button" class="auth-primary-button" data-auth-login>重新登录</button>`
      : "";

    return `
      <section class="auth-card auth-card--status">
        <div class="auth-status-mark auth-status-mark--${content.tone}" aria-hidden="true">${content.mark}</div>
        <div class="auth-card__heading">
          <p>管理员入口</p>
          <h1>${content.title}</h1>
          <span>${content.description}</span>
        </div>
        <div class="auth-status-note auth-status-note--${content.tone}">${content.note}</div>
        ${action}
      </section>
    `;
  }

  function bindEvents(context) {
    const { navigate } = context;
    document.querySelector("[data-bind-phone]")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-auth-refresh]")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-auth-login]")?.addEventListener("click", () => navigate("orders"));
  }

  function mount(context) {
    const { app, state } = context;
    const knownStatus = ["bind", ...Object.keys(statusContent)].includes(state.authStatus) ? state.authStatus : "bind";
    app.innerHTML = `
      <div class="auth-page">
        <div class="auth-orbit auth-orbit--one" aria-hidden="true"></div>
        <div class="auth-orbit auth-orbit--two" aria-hidden="true"></div>
        ${renderBrand()}
        <main class="auth-content">
          ${knownStatus === "bind" ? renderBinding() : renderStatus(knownStatus)}
        </main>
      </div>
    `;
    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.auth = { mount };
})();
