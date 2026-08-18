(function startPrototype() {
  const app = document.querySelector("#app");
  const data = window.AdminPrototypeData;
  const icons = window.AdminPrototypeIcons;
  const pages = window.AdminPrototypePages;

  if (!app || !data || !icons || !pages) {
    throw new Error("管理员小程序原型资源加载失败");
  }

  const state = {
    page: "orders",
    selectedOrderId: null,
    selectedShipmentNo: null,
    shipmentBackPage: "order-detail",
    keyword: "",
    status: "all",
    factories: [],
    tracker: "all",
    dueStart: "",
    dueEnd: "",
    overdueOnly: false,
    sort: "urgent",
    filterOpen: false,
    shipmentKeyword: "",
    shipmentFactories: [],
    shipmentDateStart: "",
    shipmentDateEnd: "",
    shipmentFilterOpen: false,
    repairKeyword: "",
    repairFactories: [],
    repairDateStart: "",
    repairDateEnd: "",
    repairFilterOpen: false,
    selectedRepairNo: null,
    repairDetailTab: "quality",
    expandedRepairProducts: [],
    expandedRepairBatches: [],
    repairDetailInitializedFor: null,
    notifyNewOrder: true,
    notifyDue: true,
    notifyShipment: true,
    notifyRepair: false,
    notificationPermissionDenied: ["notifyRepair"],
  };

  function formatNumber(value) {
    return new Intl.NumberFormat("zh-CN").format(value);
  }

  function selectOptions(options, current) {
    return options
      .map(([value, label]) => `<option value="${value}" ${value === current ? "selected" : ""}>${label}</option>`)
      .join("");
  }

  function showToast(message) {
    const toast = document.querySelector(".prototype-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("is-visible");
    window.setTimeout(() => toast.classList.remove("is-visible"), 1800);
  }

  function navigate(page, values = {}) {
    Object.assign(state, values, { page });
    window.scrollTo({ top: 0, behavior: "auto" });
    render();
  }

  const context = {
    app,
    data,
    icons,
    state,
    helpers: { formatNumber, selectOptions, showToast },
    navigate,
    render,
  };

  function render() {
    const page = pages[state.page];
    if (!page) throw new Error(`未注册页面：${state.page}`);
    page.mount(context);
  }

  render();
})();
