(function registerProfilePage() {
  const notifications = [
    { key: "notifyNewOrder", title: "新订单通知", description: "新订单导入并分配后提醒" },
    { key: "notifyDue", title: "临期与逾期提醒", description: "合同出货时间临近或逾期时提醒" },
    { key: "notifyShipment", title: "正常发货通知", description: "工厂提交正式发货单后提醒" },
    { key: "notifyRepair", title: "质检单返修通知", description: "工厂提交返修发回记录后提醒" },
  ];

  function renderNotificationRow(item, state) {
    const enabled = state[item.key];
    const permissionDenied = state.notificationPermissionDenied.includes(item.key);
    return `
      <div class="profile-notification-row ${permissionDenied ? "has-permission-warning" : ""}">
        <span>
          <strong>${item.title}</strong>
          <small>${item.description}</small>
          ${permissionDenied ? `<em>微信通知未开启</em>` : ""}
        </span>
        <div class="profile-notification-action">
          ${permissionDenied ? `<button type="button" class="profile-permission-button" data-enable-notification="${item.key}">去开启</button>` : ""}
          <button type="button" class="profile-switch ${enabled ? "is-on" : ""}" role="switch" aria-checked="${enabled}" data-notification-key="${item.key}" aria-label="${item.title}"><i></i></button>
        </div>
      </div>
    `;
  }

  function bindEvents(context) {
    const { state, render, navigate } = context;
    document.querySelectorAll("[data-notification-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.notificationKey;
        state[key] = !state[key];
        if (state[key]) state.notificationPermissionDenied = state.notificationPermissionDenied.filter((item) => item !== key);
        render();
      });
    });
    document.querySelectorAll("[data-enable-notification]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.enableNotification;
        state.notificationPermissionDenied = state.notificationPermissionDenied.filter((item) => item !== key);
        state[key] = true;
        render();
      });
    });
    document.querySelector("[data-page-target='orders']")?.addEventListener("click", () => navigate("orders"));
    document.querySelector("[data-page-target='shipments']")?.addEventListener("click", () => navigate("shipments"));
  }

  function mount(context) {
    const { app, icons, state } = context;
    app.innerHTML = `
      <div class="page-shell profile-page">
        <header class="page-header profile-page__header">
          <div class="mini-titlebar">
            <span class="titlebar-spacer" aria-hidden="true"></span>
            <h1>我的</h1>
            <div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div>
          </div>
        </header>

        <main class="profile-content">
          <section class="profile-hero">
            <div class="profile-avatar" aria-label="煎饼的头像">煎</div>
            <div class="profile-identity">
              <div><h2>煎饼</h2></div>
              <p>最高管理员</p>
            </div>
          </section>

          <section class="profile-card">
            <header><h2>账号信息</h2></header>
            <dl class="profile-account-list">
              <div><dt>姓名</dt><dd>煎饼</dd></div>
              <div><dt>管理员类型</dt><dd>最高管理员</dd></div>
              <div><dt>账号状态</dt><dd class="is-normal">正常</dd></div>
            </dl>
          </section>

          <section class="profile-card">
            <header><h2>通知设置</h2></header>
            <div class="profile-notification-list">
              ${notifications.map((item) => renderNotificationRow(item, state)).join("")}
            </div>
          </section>
        </main>

        <nav class="tabbar" aria-label="管理员小程序一级导航">
          <button type="button" class="tabbar__item" data-page-target="orders">${icons.orders}<span>订单</span></button>
          <button type="button" class="tabbar__item" data-page-target="shipments">${icons.truck}<span>发货</span></button>
          <button type="button" class="tabbar__item is-active">${icons.profile}<span>我的</span></button>
        </nav>
      </div>
    `;

    bindEvents(context);
  }

  window.AdminPrototypePages ??= {};
  window.AdminPrototypePages.profile = { mount };
})();
