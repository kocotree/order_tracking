(function registerAuthPage() {
  let agreementAccepted = false;

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

  function renderCapsule() {
    return '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>';
  }

  function renderBinding() {
    return `
      <header class="admin-auth-capsule-row">${renderCapsule()}</header>
      <main class="admin-auth-login-main">
        <div class="admin-auth-logo"><img src="../factory-miniprogram-lowfi/assets/logo-compact-ktk-transparent.png" alt="KOCOTREE KTK" /></div>
        <div class="admin-auth-copy"><h1>订单管理系统</h1><p>查看订单、发货记录与返修进度</p></div>
        <button type="button" class="auth-primary-button admin-auth-login-button" data-bind-phone>微信授权登录</button>
        <label class="admin-auth-agreement"><input type="checkbox" data-auth-agreement ${agreementAccepted ? "checked" : ""} /><i></i><span>我已阅读并同意<a href="#" data-policy="用户协议">用户协议</a>和<a href="#" data-policy="隐私政策">隐私政策</a></span></label>
      </main>
      <footer class="admin-auth-safe-note">仅用于已授权管理员访问业务数据</footer>
      <div class="prototype-toast" role="status"></div>
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
    const { navigate, helpers } = context;
    document.querySelector("[data-auth-agreement]")?.addEventListener("change", (event) => {
      agreementAccepted = event.target.checked;
    });
    document.querySelectorAll("[data-policy]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        helpers.showToast(`${link.dataset.policy}页面暂不展开`);
      });
    });
    document.querySelector("[data-bind-phone]")?.addEventListener("click", () => {
      if (!agreementAccepted) {
        helpers.showToast("请先阅读并同意用户协议和隐私政策");
        return;
      }
      navigate("orders");
    });
    document.querySelector("[data-auth-refresh]")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-auth-login]")?.addEventListener("click", () => navigate("orders"));
  }

  function mount(context) {
    const { app, state } = context;
    const knownStatus = ["bind", ...Object.keys(statusContent)].includes(state.authStatus) ? state.authStatus : "bind";
    app.innerHTML = knownStatus === "bind"
      ? `<div class="auth-page auth-page--login">${renderBinding()}</div>`
      : `
      <div class="auth-page auth-page--status">
        <div class="auth-orbit auth-orbit--one" aria-hidden="true"></div>
        <div class="auth-orbit auth-orbit--two" aria-hidden="true"></div>
        ${renderBrand()}
        <main class="auth-content">
          ${renderStatus(knownStatus)}
        </main>
      </div>
    `;
    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.auth = { mount };
})();
