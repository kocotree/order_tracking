(function bootstrap() {
  var app = document.getElementById("app");

  function init() {
    var authMatch = window.location.hash.match(/^#auth=(login|apply|pending|rejected|disabled)$/);
    var initialView = authMatch ? authMatch[1] : "login";
    var isApprovedDemoAccount = initialView === "login";
    var page = window.FactoryPages.auth;
    if (page && page.mount) {
      page.mount(app, initialView, isApprovedDemoAccount);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
