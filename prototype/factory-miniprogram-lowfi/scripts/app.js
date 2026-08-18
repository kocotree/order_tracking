(function bootstrap() {
  var app = document.getElementById("app");

  function init() {
    var page = window.FactoryPages["task-list"];
    if (page && page.render) {
      page.render(app);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();