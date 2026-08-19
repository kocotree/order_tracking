(function registerAuthPages() {
  var authState = {
    view: "login",
    existingAccount: false,
    agreementAccepted: false,
    form: {
      realName: "",
      phone: "138****5628",
      position: "employee",
      factory: "昱斌",
    },
    submittedAt: "2026-08-19 14:30",
  };

  var factories = ["昱斌", "宇倩", "盛峰", "聚兴"];

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>'"]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
    });
  }

  function renderCapsule() {
    return '<div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>';
  }

  function mount(app, initialView, existingAccount) {
    authState.view = initialView || "login";
    authState.existingAccount = Boolean(existingAccount);
    if (["pending", "rejected"].includes(authState.view) && !authState.form.realName) authState.form.realName = "张师傅";

    function setView(view) {
      authState.view = view;
      if (window.location.hash.indexOf("#auth=") === 0) window.history.replaceState(null, "", "#auth=" + view);
      render();
    }

    function renderLogin() {
      return '<div class="auth-shell auth-login-page">' +
        '<header class="auth-login-header">' +
          '<div class="auth-status-bar" aria-hidden="true"><strong>9:41</strong><div class="auth-device-status"><span class="auth-cellular"><i></i><i></i><i></i><i></i></span><span class="auth-wifi"><i></i></span><span class="auth-battery"><i></i></span></div></div>' +
          '<div class="auth-capsule-row">' + renderCapsule() + '</div>' +
        '</header>' +
        '<main class="auth-login-main">' +
          '<div class="auth-brand-logo"><img src="./assets/logo-compact-ktk-transparent.png" alt="KOCOTREE KTK" /></div>' +
          '<div class="auth-login-copy"><h1>订单管理系统</h1><p>查看订单任务，完成装箱发货与返修处理</p></div>' +
          '<button type="button" class="auth-primary-button auth-wechat-button" id="wechat-login"><span class="auth-wechat-icon" aria-hidden="true"><i></i><b></b></span><span>微信授权登录</span></button>' +
          '<label class="auth-agreement"><input type="checkbox" id="auth-agreement"' + (authState.agreementAccepted ? ' checked' : '') + ' /><i></i><span>我已阅读并同意<a href="#" data-policy="用户协议">用户协议</a>和<a href="#" data-policy="隐私政策">隐私政策</a></span></label>' +
        '</main>' +
        '<footer class="auth-safe-note">仅用于已授权工厂用户访问本厂业务数据</footer>' +
      '</div>';
    }

    function renderLoading() {
      return '<div class="auth-shell auth-status-page"><header class="auth-capsule-row">' + renderCapsule() + '</header><main class="auth-status-main"><div class="auth-loader"><i></i><i></i><i></i></div><h1>正在识别身份</h1><p>正在绑定微信身份与授权手机号，请稍候</p></main></div>';
    }

    function renderApply() {
      return '<div class="auth-shell auth-form-page">' +
        '<header class="auth-page-header"><button type="button" id="auth-back" aria-label="返回">' + window.FactoryIcons.back + '</button><h1>申请加入工厂</h1>' + renderCapsule() + '</header>' +
        '<main class="auth-form-content">' +
          '<section class="auth-intro"><span>工厂身份申请</span><h2>填写真实工作信息</h2><p>提交后由管理员审核，审核通过后可查看所属工厂任务。</p></section>' +
          '<section class="auth-form-card">' +
            '<label class="auth-field"><span>真实姓名</span><input id="apply-name" type="text" maxlength="20" value="' + escapeHtml(authState.form.realName) + '" placeholder="请输入真实姓名" autocomplete="name" /></label>' +
            '<div class="auth-field auth-readonly-field"><span>联系电话</span><strong>' + authState.form.phone + '</strong><small>已通过微信授权绑定</small></div>' +
            '<fieldset class="auth-field auth-position-field"><legend>职位</legend><div><button type="button" data-position="owner" class="' + (authState.form.position === "owner" ? "is-selected" : "") + '">老板</button><button type="button" data-position="employee" class="' + (authState.form.position === "employee" ? "is-selected" : "") + '">工厂员工</button></div></fieldset>' +
            '<label class="auth-field"><span>申请工厂</span><input id="apply-factory" type="search" list="factory-options" value="' + escapeHtml(authState.form.factory) + '" placeholder="搜索并选择工厂" autocomplete="off" /><datalist id="factory-options">' + factories.map(function (factory) { return '<option value="' + factory + '"></option>'; }).join("") + '</datalist><small>搜索并单选系统已有工厂</small></label>' +
          '</section>' +
          '<button type="button" class="auth-primary-button" id="submit-application">提交申请</button>' +
        '</main>' +
      '</div>';
    }

    function statusFacts(includeReason) {
      return '<dl class="auth-status-facts"><div><dt>真实姓名</dt><dd>' + escapeHtml(authState.form.realName || "张师傅") + '</dd></div><div><dt>联系电话</dt><dd>' + authState.form.phone + '</dd></div><div><dt>职位</dt><dd>' + (authState.form.position === "owner" ? "老板" : "工厂员工") + '</dd></div><div><dt>申请工厂</dt><dd>' + authState.form.factory + '</dd></div><div><dt>提交时间</dt><dd>' + authState.submittedAt + '</dd></div>' + (includeReason ? '<div class="auth-reject-reason"><dt>拒绝原因</dt><dd>申请人信息与工厂登记联系人不一致，请核对后重新提交。</dd></div><div><dt>审核时间</dt><dd>2026-08-19 15:10</dd></div>' : '') + '</dl>';
    }

    function renderPending() {
      return '<div class="auth-shell auth-status-page"><header class="auth-capsule-row">' + renderCapsule() + '</header><main class="auth-status-content"><section class="auth-state-card"><div class="auth-state-icon auth-state-icon--pending"><i></i></div><span class="auth-state-kicker">工厂身份申请</span><h1>申请审核中</h1><p>管理员审核通过后，即可查看所属工厂的订单与返修任务。</p>' + statusFacts(false) + '</section><button type="button" class="auth-primary-button" id="refresh-review">刷新审核结果</button><button type="button" class="auth-text-button" id="auth-logout">退出登录</button></main></div>';
    }

    function renderRejected() {
      return '<div class="auth-shell auth-status-page"><header class="auth-capsule-row">' + renderCapsule() + '</header><main class="auth-status-content"><section class="auth-state-card"><div class="auth-state-icon auth-state-icon--rejected">!</div><span class="auth-state-kicker">审核结果</span><h1>申请未通过</h1><p>请根据拒绝原因修改资料后重新提交。</p>' + statusFacts(true) + '</section><button type="button" class="auth-primary-button" id="edit-application">修改并重新提交</button><button type="button" class="auth-text-button" id="auth-logout">退出登录</button></main></div>';
    }

    function renderDisabled() {
      return '<div class="auth-shell auth-status-page"><header class="auth-capsule-row">' + renderCapsule() + '</header><main class="auth-status-main auth-disabled-main"><div class="auth-state-icon auth-state-icon--disabled">×</div><span class="auth-state-kicker">账号权限</span><h1>当前账号暂不可使用</h1><p>账号已停用或没有访问权限，请联系管理员处理。</p><div class="auth-disabled-factory"><span>所属工厂</span><strong>昱斌</strong></div><button type="button" class="auth-text-button" id="auth-logout">退出登录</button></main></div>';
    }

    function render() {
      var views = { login: renderLogin, loading: renderLoading, apply: renderApply, pending: renderPending, rejected: renderRejected, disabled: renderDisabled };
      app.innerHTML = (views[authState.view] || renderLogin)() + '<div class="prototype-toast auth-toast" role="status"></div>';
      bindEvents();
    }

    function showToast(message) {
      var toast = document.querySelector(".prototype-toast");
      if (!toast) return;
      toast.textContent = message;
      toast.classList.remove("is-visible");
      void toast.offsetWidth;
      toast.classList.add("is-visible");
      setTimeout(function () { toast.classList.remove("is-visible"); }, 1800);
    }

    function bindEvents() {
      document.querySelector("#auth-agreement")?.addEventListener("change", function (event) { authState.agreementAccepted = event.target.checked; });
      document.querySelectorAll("[data-policy]").forEach(function (link) { link.addEventListener("click", function (event) { event.preventDefault(); showToast(link.dataset.policy + "页面暂不展开"); }); });
      document.querySelector("#wechat-login")?.addEventListener("click", function () {
        if (!authState.agreementAccepted) { showToast("请先阅读并同意用户协议和隐私政策"); return; }
        authState.view = "loading";
        render();
        setTimeout(function () {
          if (authState.existingAccount) window.FactoryPages["task-list"].mount(app);
          else setView("apply");
        }, 700);
      });
      document.querySelector("#auth-back")?.addEventListener("click", function () { setView("login"); });
      document.querySelectorAll("[data-position]").forEach(function (button) { button.addEventListener("click", function () { authState.form.position = button.dataset.position; render(); }); });
      document.querySelector("#submit-application")?.addEventListener("click", function () {
        var name = document.querySelector("#apply-name").value.trim();
        var factory = document.querySelector("#apply-factory").value.trim();
        if (!name) { showToast("请填写真实姓名"); return; }
        if (!factories.includes(factory)) { showToast("请选择系统已有工厂"); return; }
        authState.form.realName = name;
        authState.form.factory = factory;
        authState.submittedAt = "2026-08-19 16:20";
        setView("pending");
      });
      document.querySelector("#refresh-review")?.addEventListener("click", function () { showToast("审核仍在进行中"); });
      document.querySelector("#edit-application")?.addEventListener("click", function () { setView("apply"); });
      document.querySelector("#auth-logout")?.addEventListener("click", function () { authState.existingAccount = false; setView("login"); });
    }

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages.auth = { mount: mount };
})();
