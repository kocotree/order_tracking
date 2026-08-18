(function bootstrap() {
  var app = document.getElementById("app");

  function init() {
    var page = window.FactoryPages["task-list"];
    if (page && page.mount) {
      page.mount(app);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();