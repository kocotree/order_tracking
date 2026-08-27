(function registerProfilePage() {
  var profileState = {
    avatarUrl: "",
    avatarSheetOpen: false,
    avatarPreviewOpen: false,
    logoutOpen: false,
    wechatNotificationAuthorized: false,
  };

  function mount(app) {
    var icons = window.FactoryIcons;
    var data = window.FactoryPrototypeData;

    function render() {
      var unreadCount = data.notifications.filter(function (item) { return !item.read; }).length;
      app.innerHTML = '<div class="page-shell factory-profile-page">' +
        '<header class="page-header profile-header"><div class="mini-titlebar"><span class="titlebar-spacer" aria-hidden="true"></span><h1>我的</h1><div class="wechat-capsule" aria-hidden="true"><b>•••</b><i></i><span></span></div></div></header>' +
        '<main class="factory-profile-content">' +
          '<section class="factory-profile-hero">' +
            '<button type="button" class="factory-avatar" id="change-avatar" aria-label="查看或更换头像">' +
              (profileState.avatarUrl ? '<img src="' + profileState.avatarUrl + '" alt="张师傅的头像" />' : '<span>张</span>') +
            '</button>' +
            '<input id="avatar-input" class="avatar-input" type="file" accept="image/*" aria-hidden="true" tabindex="-1" />' +
            '<div class="factory-profile-identity"><h2>张师傅</h2><p>工厂员工</p></div>' +
          '</section>' +
          '<section class="factory-profile-card" aria-label="账号与通知"><dl class="factory-account-list">' +
            '<div><dt>姓名</dt><dd>张师傅</dd></div>' +
            '<div><dt>联系电话</dt><dd>138****5628</dd></div>' +
            '<div><dt>职位</dt><dd>工厂员工</dd></div>' +
            '<div><dt>所属工厂</dt><dd>昱斌</dd></div>' +
          '</dl>' +
            '<button type="button" class="factory-profile-action-row factory-wechat-authorization" id="authorize-wechat-notifications"><strong>微信提醒授权</strong><span class="factory-wechat-authorization__state">' + (profileState.wechatNotificationAuthorized ? '本次已授权' : '去授权') + '</span><span class="factory-profile-action-row__chevron">' + icons.chevron + '</span></button>' +
            '<button type="button" class="factory-profile-action-row factory-notification-center" id="open-notifications"><strong>通知中心</strong>' + (unreadCount > 0 ? '<b aria-label="' + unreadCount + '条未读">' + unreadCount + '</b>' : '') + '<span class="factory-profile-action-row__chevron">' + icons.chevron + '</span></button>' +
          '</section>' +
          '<button type="button" class="logout-button" id="logout-button">退出登录</button>' +
        '</main>' +
        '<nav class="tabbar" aria-label="工厂小程序一级导航"><button type="button" class="tabbar__item" id="profile-to-tasks">' + icons.tasks + '<span>任务</span></button><button type="button" class="tabbar__item" id="profile-to-records">' + icons.truck + '<span>发货记录</span></button><button type="button" class="tabbar__item is-active">' + icons.profile + '<span>我的</span></button></nav>' +
      '</div>' + renderAvatarSheet() + renderAvatarPreview() + renderLogoutSheet() + '<div class="prototype-toast" role="status"></div>';
      bindEvents();
    }

    function renderAvatarSheet() {
      if (!profileState.avatarSheetOpen) return "";
      return '<div class="factory-avatar-action-layer" id="avatar-action-layer">' +
        '<section class="factory-avatar-action-sheet" role="dialog" aria-modal="true" aria-label="头像操作">' +
          '<div><button type="button" id="view-avatar">查看头像</button><button type="button" id="select-avatar">更换头像</button></div>' +
          '<button type="button" id="close-avatar-actions">取消</button>' +
        '</section>' +
      '</div>';
    }

    function renderAvatarPreview() {
      if (!profileState.avatarPreviewOpen) return "";
      return '<div class="factory-avatar-preview" role="dialog" aria-modal="true" aria-label="头像预览">' +
        '<button type="button" id="close-avatar-preview" aria-label="关闭头像预览">×</button>' +
        (profileState.avatarUrl ? '<img src="' + profileState.avatarUrl + '" alt="张师傅的头像大图" />' : '<span>张</span>') +
      '</div>';
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

    function bindEvents() {
      document.querySelector("#profile-to-tasks")?.addEventListener("click", function () { window.FactoryPages["task-list"].mount(app); });
      document.querySelector("#profile-to-records")?.addEventListener("click", function () { window.FactoryPages["shipment-records"].mount(app); });
      document.querySelector("#change-avatar")?.addEventListener("click", function () {
        profileState.avatarSheetOpen = true;
        render();
      });
      document.querySelector("#avatar-action-layer")?.addEventListener("click", function (event) {
        if (event.target !== event.currentTarget) return;
        profileState.avatarSheetOpen = false;
        render();
      });
      document.querySelector("#close-avatar-actions")?.addEventListener("click", function () {
        profileState.avatarSheetOpen = false;
        render();
      });
      document.querySelector("#view-avatar")?.addEventListener("click", function () {
        profileState.avatarSheetOpen = false;
        profileState.avatarPreviewOpen = true;
        render();
      });
      document.querySelector("#select-avatar")?.addEventListener("click", function () {
        profileState.avatarSheetOpen = false;
        render();
        document.querySelector("#avatar-input")?.click();
      });
      document.querySelector("#close-avatar-preview")?.addEventListener("click", function () {
        profileState.avatarPreviewOpen = false;
        render();
      });
      document.querySelector("#avatar-input")?.addEventListener("change", function (event) {
        var file = event.target.files && event.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.addEventListener("load", function () { profileState.avatarUrl = reader.result; render(); showToast("头像已更换"); });
        reader.readAsDataURL(file);
      });
      document.querySelector("#authorize-wechat-notifications")?.addEventListener("click", function () {
        profileState.wechatNotificationAuthorized = true;
        render();
      });
      document.querySelector("#open-notifications")?.addEventListener("click", function () { window.FactoryPages.notifications.mount(app, true); });
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
