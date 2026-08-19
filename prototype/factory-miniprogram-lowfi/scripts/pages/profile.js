(function registerProfilePage() {
  var profileState = {
    avatarUrl: "",
    logoutOpen: false,
    notifications: {
      newOrder: true,
      due: true,
      repair: true,
      result: false,
    },
    permissionDenied: ["result"],
  };

  var notifications = [
    { key: "newOrder", title: "新订单任务", description: "本厂收到新的订单任务时提醒" },
    { key: "due", title: "临期与逾期提醒", description: "合同出货时间临近或逾期时提醒" },
    { key: "repair", title: "新返修任务", description: "本厂收到新的质检返修任务时提醒" },
    { key: "result", title: "业务处理结果", description: "撤回审核或退回补发结果提醒" },
  ];

  function renderNotification(item) {
    var enabled = profileState.notifications[item.key];
    var denied = profileState.permissionDenied.includes(item.key);
    return '<div class="factory-notification-row' + (denied ? ' has-warning' : '') + '">' +
      '<span><strong>' + item.title + '</strong><small>' + item.description + '</small>' +
      (denied ? '<em>微信通知未开启</em>' : '') + '</span>' +
      '<div class="factory-notification-action">' +
        (denied ? '<button type="button" class="permission-link" data-enable-permission="' + item.key + '">去开启</button>' : '') +
        '<button type="button" class="factory-switch' + (enabled ? ' is-on' : '') + '" role="switch" aria-checked="' + enabled + '" aria-label="' + item.title + '" data-notification="' + item.key + '"><i></i></button>' +
      '</div></div>';
  }

  function mount(app) {
    var icons = window.FactoryIcons;

    function render() {
      app.innerHTML = '<div class="page-shell factory-profile-page">' +
        '<header class="page-header profile-header"><div class="mini-titlebar"><span class="titlebar-spacer" aria-hidden="true"></span><h1>我的</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></div></header>' +
        '<main class="factory-profile-content">' +
          '<section class="factory-profile-hero">' +
            '<button type="button" class="factory-avatar" id="change-avatar" aria-label="更换头像">' +
              (profileState.avatarUrl ? '<img src="' + profileState.avatarUrl + '" alt="张师傅的头像" />' : '<span>张</span>') +
              '<i>' + icons.camera + '</i>' +
            '</button>' +
            '<input id="avatar-input" class="avatar-input" type="file" accept="image/*" aria-hidden="true" tabindex="-1" />' +
            '<div class="factory-profile-identity"><h2>张师傅</h2><p>昱斌 · 工厂员工</p></div>' +
          '</section>' +
          '<section class="factory-profile-card"><header><h2>账号信息</h2></header><dl class="factory-account-list">' +
            '<div><dt>姓名</dt><dd>张师傅</dd></div>' +
            '<div><dt>联系电话</dt><dd>138****5628</dd></div>' +
            '<div><dt>职位</dt><dd>工厂员工</dd></div>' +
            '<div><dt>所属工厂</dt><dd>昱斌</dd></div>' +
          '</dl></section>' +
          '<section class="factory-profile-card"><header><h2>通知设置</h2></header><div class="factory-notification-list">' + notifications.map(renderNotification).join("") + '</div></section>' +
          '<button type="button" class="logout-button" id="logout-button">退出登录</button>' +
        '</main>' +
        '<nav class="tabbar" aria-label="工厂小程序一级导航"><button type="button" class="tabbar__item" id="profile-to-tasks">' + icons.tasks + '<span>任务</span></button><button type="button" class="tabbar__item" id="profile-to-records">' + icons.truck + '<span>发货记录</span></button><button type="button" class="tabbar__item is-active">' + icons.profile + '<span>我的</span></button></nav>' +
      '</div>' + renderLogoutSheet() + '<div class="prototype-toast" role="status"></div>';
      bindEvents();
    }

    function renderLogoutSheet() {
      if (!profileState.logoutOpen) return "";
      return '<div class="profile-dialog-layer" id="logout-layer"><section class="profile-dialog" role="dialog" aria-modal="true" aria-labelledby="logout-title"><h2 id="logout-title">退出登录？</h2><p>退出后，下次进入仍会根据当前微信身份重新登录。</p><div><button type="button" class="dialog-cancel" id="cancel-logout">取消</button><button type="button" class="dialog-confirm" id="confirm-logout">退出登录</button></div></section></div>';
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

    function openAvatarPicker() {
      document.querySelector("#avatar-input")?.click();
    }

    function bindEvents() {
      document.querySelector("#profile-to-tasks")?.addEventListener("click", function () { window.FactoryPages["task-list"].mount(app); });
      document.querySelector("#profile-to-records")?.addEventListener("click", function () { window.FactoryPages["shipment-records"].mount(app); });
      document.querySelector("#change-avatar")?.addEventListener("click", openAvatarPicker);
      document.querySelector("#avatar-input")?.addEventListener("change", function (event) {
        var file = event.target.files && event.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.addEventListener("load", function () { profileState.avatarUrl = reader.result; render(); showToast("头像已更换"); });
        reader.readAsDataURL(file);
      });
      document.querySelectorAll("[data-notification]").forEach(function (button) {
        button.addEventListener("click", function () {
          var key = button.dataset.notification;
          if (!profileState.notifications[key] && profileState.permissionDenied.includes(key)) {
            showToast("请先开启微信通知");
            return;
          }
          profileState.notifications[key] = !profileState.notifications[key];
          render();
        });
      });
      document.querySelectorAll("[data-enable-permission]").forEach(function (button) {
        button.addEventListener("click", function () {
          var key = button.dataset.enablePermission;
          profileState.permissionDenied = profileState.permissionDenied.filter(function (item) { return item !== key; });
          profileState.notifications[key] = true;
          render();
          showToast("微信通知已开启");
        });
      });
      document.querySelector("#logout-button")?.addEventListener("click", function () { profileState.logoutOpen = true; render(); });
      document.querySelector("#cancel-logout")?.addEventListener("click", function () { profileState.logoutOpen = false; render(); });
      document.querySelector("#logout-layer")?.addEventListener("click", function (event) {
        if (event.target !== event.currentTarget) return;
        profileState.logoutOpen = false;
        render();
      });
      document.querySelector("#confirm-logout")?.addEventListener("click", function () {
        profileState.logoutOpen = false;
        window.FactoryPages.auth.mount(app, "login", true);
      });
    }

    render();
  }

  window.FactoryPages ??= {};
  window.FactoryPages.profile = { mount: mount };
})();
