export const notificationData = [
  {
    id: "notification-1",
    category: "正常发货",
    title: "宇情工厂已提交发货",
    description: "发货单 FH20260812-004，涉及订单 369#",
    time: "2026-08-12 15:30",
    tone: "info",
    route: "/shipments/FH20260812-004",
    read: false,
  },
  {
    id: "notification-2",
    category: "合同出货提醒",
    title: "订单 078# 今日到期",
    description: "昱斌工厂仍有 520 件待发，请及时跟进",
    time: "2026-08-12 09:00",
    tone: "warning",
    route: "/orders/078%23",
    read: false,
  },
  {
    id: "notification-3",
    category: "正常发货",
    title: "启宏工厂已提交发货",
    description: "发货单 FH20260811-005，涉及订单 090#",
    time: "2026-08-11 17:42",
    tone: "success",
    route: "/shipments/FH20260811-005",
    read: false,
  },
  {
    id: "notification-4",
    category: "质检返修",
    title: "旭之梦工厂已提交返修结果",
    description: "返修单 FX20260817-001，本次返修 18 件、报废 2 件",
    time: "2026-08-17 14:10",
    tone: "info",
    route: "/repairs/FX20260817-001",
    read: false,
  },
  {
    id: "notification-5",
    category: "合同出货提醒",
    title: "订单 085# 距合同出货还有 3 天",
    description: "盛泰工厂仍有 1,920 件待发，请及时跟进",
    time: "2026-08-12 09:00",
    tone: "warning",
    route: "/orders/085%23",
    read: true,
  },
  {
    id: "notification-6",
    category: "正常发货",
    title: "盛泰工厂已提交发货",
    description: "发货单 FH20260810-004，涉及订单 085#",
    time: "2026-08-10 16:28",
    tone: "success",
    route: "/shipments/FH20260810-004",
    read: true,
  },
  {
    id: "notification-7",
    category: "合同出货提醒",
    title: "订单 088# 距合同出货还有 5 天",
    description: "昱斌工厂仍有 1,600 件待发，请及时跟进",
    time: "2026-08-13 09:00",
    tone: "warning",
    route: "/orders/088%23",
    read: true,
  },
  {
    id: "notification-8",
    category: "正常发货",
    title: "昱斌工厂已提交发货",
    description: "发货单 FH20260808-003，涉及订单 078#",
    time: "2026-08-08 11:16",
    tone: "info",
    route: "/shipments/FH20260808-003",
    read: true,
  },
  {
    id: "notification-9",
    category: "质检返修",
    title: "红燕工厂返修单已完成",
    description: "返修单 FX20260814-003，返修 24 件、报废 4 件",
    time: "2026-08-15 15:06",
    tone: "success",
    route: "/repairs/FX20260814-003",
    read: true,
  },
  {
    id: "notification-10",
    category: "合同出货提醒",
    title: "订单 090# 距合同出货还有 10 天",
    description: "启宏工厂仍有 1,000 件待发，请及时跟进",
    time: "2026-08-10 09:00",
    tone: "warning",
    route: "/orders/090%23",
    read: true,
  },
  {
    id: "notification-11",
    category: "正常发货",
    title: "宇情工厂已提交发货",
    description: "发货单 FH20260806-002，涉及订单 078#",
    time: "2026-08-06 14:35",
    tone: "info",
    route: "/shipments/FH20260806-002",
    read: true,
  },
  {
    id: "notification-12",
    category: "质检返修",
    title: "龙腾工厂已接收返修通知",
    description: "返修单 FX20260816-002，待处理 48 件",
    time: "2026-08-16 15:02",
    tone: "info",
    route: "/repairs/FX20260816-002",
    read: true,
  },
];

export const dashboardData = {
  updatedAt: "2026-08-12 15:40",
  stats: [
    {
      id: "pending-imports",
      label: "待导入订单",
      value: 6,
      unit: "单",
      detail: "其中 2 单资料待补",
      tone: "info",
      destination: "待导入订单",
    },
    {
      id: "recent-shipments",
      label: "今日发货记录",
      value: 4,
      unit: "张",
      detail: "今日新增 2 张",
      tone: "info",
      destination: "发货单列表",
    },
    {
      id: "overdue-orders",
      label: "逾期订单",
      value: 3,
      unit: "单",
      detail: "最久已逾期 4 天",
      tone: "danger",
      destination: "订单列表 · 已逾期",
    },
  ],
  notifications: notificationData.slice(0, 3),
  orders: [
    {
      id: "order-078",
      orderNo: "078#",
      productName: "乐园游会吊带包屁衣",
      category: "服装",
      tracker: "松子",
      factory: "昱斌、宇情",
      nearestDue: "2026-08-10",
      progress: 46,
      progressText: "1,380 / 3,000",
      status: "已逾期",
      tone: "danger",
    },
    {
      id: "order-369",
      orderNo: "369#",
      productName: "小热皮绒绒裤",
      category: "服装",
      tracker: "烧麦",
      factory: "宇情",
      nearestDue: "2026-08-13",
      progress: 72,
      progressText: "1,440 / 2,000",
      status: "未完成",
      tone: "info",
    },
    {
      id: "order-085",
      orderNo: "085#",
      productName: "海岛轻量防晒帽",
      category: "帽子",
      tracker: "青椒",
      factory: "盛泰",
      nearestDue: "2026-08-15",
      progress: 20,
      progressText: "480 / 2,400",
      status: "未完成",
      tone: "info",
    },
    {
      id: "order-088",
      orderNo: "088#",
      productName: "云朵软壳冲锋衣",
      category: "服装",
      tracker: "大葱",
      factory: "昱斌",
      nearestDue: "2026-08-18",
      progress: 0,
      progressText: "0 / 1,600",
      status: "未完成",
      tone: "warning",
    },
    {
      id: "order-090",
      orderNo: "090#",
      productName: "晴雨两用机能风衣",
      category: "服装",
      tracker: "橄榄",
      factory: "启宏",
      nearestDue: "2026-08-20",
      progress: 86,
      progressText: "860 / 1,000",
      status: "未完成",
      tone: "info",
    },
  ],
};

export const orderListData = {
  orders: [
    {
      id: "order-078",
      orderNo: "078#",
      productName: "乐园游会吊带包屁衣",
      category: "服装",
      specSummary: "3 个颜色 / 规格",
      tracker: "松子",
      factory: "昱斌、宇情",
      nearestDue: "2026-08-10",
      shippedPercent: 46,
      shippedText: "1,380 / 3,000",
      statusKey: "shipping",
      statusLabel: "未完成",
      tone: "danger",
      overdueDays: 3,
      orderDate: "2026-07-26",
      updatedAt: "2026-08-13T09:00:00",
    },
    {
      id: "order-369",
      orderNo: "369#",
      productName: "小热皮绒绒裤",
      category: "服装",
      specSummary: "2 个颜色 / 规格",
      tracker: "烧麦",
      factory: "宇情",
      nearestDue: "2026-08-13",
      shippedPercent: 72,
      shippedText: "1,440 / 2,000",
      statusKey: "shipping",
      statusLabel: "未完成",
      tone: "info",
      overdueDays: 0,
      orderDate: "2026-07-29",
      updatedAt: "2026-08-13T08:50:00",
    },
    {
      id: "order-085",
      orderNo: "085#",
      productName: "海岛轻量防晒帽",
      category: "帽子",
      specSummary: "4 个颜色 / 规格",
      tracker: "青椒",
      factory: "盛泰",
      nearestDue: "2026-08-15",
      shippedPercent: 20,
      shippedText: "480 / 2,400",
      statusKey: "shipping",
      statusLabel: "未完成",
      tone: "info",
      overdueDays: 0,
      orderDate: "2026-08-01",
      updatedAt: "2026-08-12T17:20:00",
    },
    {
      id: "order-088",
      orderNo: "088#",
      productName: "云朵软壳冲锋衣",
      category: "服装",
      specSummary: "5 个颜色 / 规格",
      tracker: "大葱",
      factory: "昱斌",
      nearestDue: "2026-08-18",
      shippedPercent: 0,
      shippedText: "0 / 1,600",
      statusKey: "pending",
      statusLabel: "未完成",
      tone: "warning",
      overdueDays: 0,
      orderDate: "2026-08-03",
      updatedAt: "2026-08-12T14:30:00",
    },
    {
      id: "order-090",
      orderNo: "090#",
      productName: "晴雨两用机能风衣",
      category: "服装",
      specSummary: "2 个颜色 / 规格",
      tracker: "橄榄",
      factory: "启宏",
      nearestDue: "2026-08-20",
      shippedPercent: 86,
      shippedText: "860 / 1,000",
      statusKey: "shipping",
      statusLabel: "未完成",
      tone: "info",
      overdueDays: 0,
      orderDate: "2026-08-04",
      updatedAt: "2026-08-12T11:10:00",
    },
    {
      id: "order-092",
      orderNo: "092#",
      productName: "轻量防风马甲等 2 款",
      category: "服装",
      specSummary: "7 个颜色 / 规格",
      tracker: "青椒",
      factory: "盛泰",
      nearestDue: "2026-08-22",
      shippedPercent: 0,
      shippedText: "0 / 2,800",
      statusKey: "draft",
      statusLabel: "草稿",
      tone: "draft",
      overdueDays: 0,
      orderDate: "2026-08-06",
      updatedAt: "2026-08-12T10:15:00",
    },
    {
      id: "order-096",
      orderNo: "096#",
      productName: "森林漫步速干短裤",
      category: "服装",
      specSummary: "3 个颜色 / 规格",
      tracker: "松子",
      factory: "宇情",
      nearestDue: "2026-08-08",
      shippedPercent: 100,
      shippedText: "1,200 / 1,200",
      statusKey: "completed",
      statusLabel: "已完成",
      tone: "success",
      overdueDays: 0,
      orderDate: "2026-07-18",
      updatedAt: "2026-08-10T16:40:00",
    },
  ],
};

export const pendingImportData = {
  lastSuccessfulFetchAt: "2026-08-20 09:30",
  fetchLogs: [],
  orders: [
    { orderNo: "E81", productName: "小护甲机能裤", category: "服装", tracker: "松子", factory: "宇情", validationKey: "ready", validationLabel: "可导入", tone: "success", statusKey: "pending" },
    { orderNo: "E82", productName: "云感防晒衣", category: "服装", tracker: "烧麦", factory: "昱斌", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E83", productName: "海岛轻量防晒帽", category: "帽子", tracker: "青椒", factory: "盛泰", validationKey: "ready", validationLabel: "可导入", tone: "success", statusKey: "pending" },
    { orderNo: "E84", productName: "晴雨两用机能风衣", category: "服装", tracker: "橄榄", factory: "启宏", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E85", productName: "森林漫步速干短裤", category: "服装", tracker: "大葱", factory: "宇情", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E86", productName: "山野轻暖摇粒绒", category: "服装", tracker: "松子", factory: "昱斌", validationKey: "ready", validationLabel: "可导入", tone: "success", statusKey: "pending" },
    { orderNo: "E87", productName: "轻量防风马甲", category: "服装", tracker: "烧麦", factory: "盛泰", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E88", productName: "探索家渔夫帽", category: "帽子", tracker: "青椒", factory: "启宏", validationKey: "ready", validationLabel: "可导入", tone: "success", statusKey: "pending" },
    { orderNo: "E89", productName: "云朵软壳冲锋衣", category: "服装", tracker: "大葱", factory: "昱斌", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E90", productName: "小热皮绒绒裤", category: "服装", tracker: "橄榄", factory: "宇情", validationKey: "ready", validationLabel: "可导入", tone: "success", statusKey: "pending" },
    { orderNo: "E91", productName: "乐园游会吊带包屁衣", category: "服装", tracker: "松子", factory: "昱斌、宇情", validationKey: "needs-data", validationLabel: "资料待处理", tone: "warning", statusKey: "pending" },
    { orderNo: "E72", productName: "轻量防风长裤", category: "服装", tracker: "烧麦", factory: "盛泰", validationKey: "ready", validationLabel: "导入时校验通过", tone: "success", statusKey: "imported" },
    { orderNo: "E73", productName: "向阳遮阳帽", category: "帽子", tracker: "青椒", factory: "启宏", validationKey: "ready", validationLabel: "导入时校验通过", tone: "success", statusKey: "imported" },
  ],
};

const mockFeishuCandidate = {
  orderNo: "E92",
  productName: "山野轻量冲锋裤",
  category: "服装",
  tracker: "青椒",
  factory: "盛泰",
  validationKey: "needs-data",
  validationLabel: "资料待处理",
  tone: "warning",
  statusKey: "pending",
};

export function fetchNewFeishuOrders() {
  const fetchedAt = new Date();
  const fetchedAtText = fetchedAt.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).replaceAll("/", "-");
  const exists = pendingImportData.orders.some((order) => order.orderNo === mockFeishuCandidate.orderNo);

  if (!exists) pendingImportData.orders.unshift({ ...mockFeishuCandidate });
  const result = { added: exists ? 0 : 1, skipped: exists ? 3 : 2, failed: 1 };
  pendingImportData.lastSuccessfulFetchAt = fetchedAtText;
  pendingImportData.fetchLogs.unshift({
    operator: "煎饼",
    fetchedAt: fetchedAt.toISOString(),
    feishuRecordIds: ["rec_mock_e92_01", "rec_mock_existing_01", "rec_mock_existing_02", "rec_mock_failed_01"],
    errorReason: "rec_mock_failed_01：订单编号为空",
    ...result,
  });
  return result;
}

export const shipmentListData = {
  shipments: [
    { shipmentNo: "FH20260814-003", orderNos: ["092#"], factory: "盛泰", shipDate: "2026-08-14", shippedQuantity: 680, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260814-002", orderNos: ["088#", "090#"], factory: "启宏", shipDate: "2026-08-14", shippedQuantity: 520, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260813-008", orderNos: ["085#"], factory: "盛泰", shipDate: "2026-08-13", shippedQuantity: 480, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260813-006", orderNos: ["369#"], factory: "宇情", shipDate: "2026-08-13", shippedQuantity: 360, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260812-006", orderNos: ["078#", "369#"], factory: "宇情", shipDate: "2026-08-12", shippedQuantity: 100, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260812-004", orderNos: ["369#"], factory: "宇情", shipDate: "2026-08-12", shippedQuantity: 420, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260811-005", orderNos: ["090#"], factory: "启宏", shipDate: "2026-08-11", shippedQuantity: 500, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260810-004", orderNos: ["085#"], factory: "盛泰", shipDate: "2026-08-10", shippedQuantity: 480, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260809-004", orderNos: ["090#"], factory: "启宏", shipDate: "2026-08-09", shippedQuantity: 360, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260808-003", orderNos: ["078#"], factory: "昱斌", shipDate: "2026-08-08", shippedQuantity: 760, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260806-002", orderNos: ["078#"], factory: "昱斌", shipDate: "2026-08-06", shippedQuantity: 520, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
    { shipmentNo: "FH20260805-001", orderNos: ["078#"], factory: "昱斌", shipDate: "2026-08-05", shippedQuantity: 520, statusKey: "shipped", statusLabel: "已发货", tone: "info" },
  ],
};

export const shipmentDetailData = {
  "FH20260814-003": {
    totalBoxes: 4,
    lines: [
      { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 110", shippedQuantity: 180 },
      { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 120", shippedQuantity: 160 },
      { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 120", shippedQuantity: 180 },
      { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 130", shippedQuantity: 160 },
    ],
    boxes: [
      {
        boxNo: 1,
        items: [
          { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 110", quantity: 90 },
          { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 120", quantity: 80 },
        ],
      },
      {
        boxNo: 2,
        items: [
          { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 110", quantity: 90 },
          { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 120", quantity: 100 },
        ],
      },
      {
        boxNo: 3,
        items: [
          { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 120", quantity: 80 },
          { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 130", quantity: 80 },
        ],
      },
      {
        boxNo: 4,
        items: [
          { orderNo: "092#", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 120", quantity: 80 },
          { orderNo: "092#", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 130", quantity: 80 },
        ],
      },
    ],
    proofCount: 2,
    factoryRemark: "共 4 箱，马甲与长裤按套装比例混装，请按箱号核对。",
    logs: [
      { time: "2026-08-14 10:26", operator: "盛泰工厂", action: "提交发货单", source: "工厂小程序" },
      { time: "2026-08-14 10:18", operator: "盛泰工厂", action: "上传发货凭证 2 张", source: "工厂小程序" },
    ],
  },
  "FH20260811-005": {
    totalBoxes: 3,
    lines: [
      { orderNo: "090#", code: "KQ26588", name: "轻量防晒外套", colorSpec: "湖蓝 / 120", shippedQuantity: 260 },
      { orderNo: "090#", code: "KQ26589", name: "轻薄速干长裤", colorSpec: "深灰 / 120", shippedQuantity: 240 },
    ],
    boxes: [
      { boxNo: 1, items: [{ orderNo: "090#", code: "KQ26588", name: "轻量防晒外套", colorSpec: "湖蓝 / 120", quantity: 100 }, { orderNo: "090#", code: "KQ26589", name: "轻薄速干长裤", colorSpec: "深灰 / 120", quantity: 80 }] },
      { boxNo: 2, items: [{ orderNo: "090#", code: "KQ26588", name: "轻量防晒外套", colorSpec: "湖蓝 / 120", quantity: 80 }, { orderNo: "090#", code: "KQ26589", name: "轻薄速干长裤", colorSpec: "深灰 / 120", quantity: 80 }] },
      { boxNo: 3, items: [{ orderNo: "090#", code: "KQ26588", name: "轻量防晒外套", colorSpec: "湖蓝 / 120", quantity: 80 }, { orderNo: "090#", code: "KQ26589", name: "轻薄速干长裤", colorSpec: "深灰 / 120", quantity: 80 }] },
    ],
    proofCount: 1,
    factoryRemark: "套装混装，共 3 箱。",
    logs: [
      { time: "2026-08-12 09:38", operator: "煎饼", action: "确认全部收到，共 500 件", source: "管理员网页端" },
      { time: "2026-08-11 16:20", operator: "启宏工厂", action: "提交发货单", source: "工厂小程序" },
    ],
  },
};

export const productListData = {
  products: [
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416764", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝100" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416771", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝110" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416788", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝120" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416795", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝130" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416801", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝140" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416818", productName: "小舒云弹弹棉T", colorSpec: "晴空蓝150" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416900", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉100" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416917", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉110" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416924", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉120" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416931", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉130" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416948", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉140" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416955", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉150" },
    { itemNo: "KQ26191", hasImage: true, productCode: "6942649416962", productName: "小舒云弹弹棉T", colorSpec: "冰莓粉160" },
  ],
};

export const factoryListData = {
  sourceTotal: 80,
  factories: [
    { id: "factory-1", supplierNumber: "A10", factoryName: "禹帆", factoryCode: "YF", legalName: "温岭市新河禹帆制帽厂", address: "", legalRepresentative: "徐陈杰", authorizedAgent: "", contacts: [{ name: "王超", phone: "13858645122" }], bank: "", bankAccount: "", sourceAliases: ["禹帆"], connectedUsers: 2 },
    { id: "factory-2", supplierNumber: "A15", factoryName: "玥鑫", factoryCode: "YX", legalName: "通州区平潮镇庆煦服饰厂", address: "浙江省嘉兴市桐乡市桐乡经济开发区发展大道288号4幢270室", legalRepresentative: "王庆庆", authorizedAgent: "", contacts: [{ name: "王亮", phone: "15562049203" }], bank: "", bankAccount: "", sourceAliases: ["玥鑫"], connectedUsers: 1 },
    { id: "factory-3", supplierNumber: "A24", factoryName: "众乐鑫", factoryCode: "ZLX", legalName: "砀山县众乐鑫服饰加工厂", address: "宿州市砀山县李庄镇李园村王牌坊自然村077", legalRepresentative: "汪闪闪", authorizedAgent: "", contacts: [{ name: "汪闪闪", phone: "15385797179" }], bank: "", bankAccount: "", sourceAliases: ["众乐鑫"], connectedUsers: 1 },
    { id: "factory-4", supplierNumber: "E01", factoryName: "金甲", factoryCode: "JJ", legalName: "淮安顶戴花翎帽业有限公司", address: "淮安市涟水县涟城街道安东路70-5号", legalRepresentative: "陆荣翠", authorizedAgent: "", contacts: [{ name: "胡永周", phone: "17715625999" }], bank: "", bankAccount: "", sourceAliases: ["金甲"], connectedUsers: 2 },
    { id: "factory-5", supplierNumber: "E03", factoryName: "康君（淮安李师傅）", factoryCode: "KJ", legalName: "淮安市康君服饰加工有限公司", address: "淮安市淮阴区丁集镇丁集村七组丁香花园西街24号", legalRepresentative: "李民", authorizedAgent: "", contacts: [{ name: "李民", phone: "18936553337" }], bank: "", bankAccount: "", sourceAliases: ["康君", "淮安李师傅"], connectedUsers: 1 },
    { id: "factory-6", supplierNumber: "E11", factoryName: "沙娟", factoryCode: "SJ", legalName: "泗洪县归仁镇沙娟鞋帽加工厂", address: "泗洪县归仁镇富仁花园内", legalRepresentative: "沙娟", authorizedAgent: "", contacts: [{ name: "沙娟", phone: "15851190525" }], bank: "", bankAccount: "", sourceAliases: ["沙娟"], connectedUsers: 1 },
    { id: "factory-7", supplierNumber: "E13", factoryName: "泗洪红亮", factoryCode: "SHHL", legalName: "泗洪县红亮服帽加工厂", address: "宿迁市泗洪县界集镇曹庙街88号", legalRepresentative: "李训亮", authorizedAgent: "", contacts: [{ name: "包玲玲", phone: "15950605396" }], bank: "", bankAccount: "", sourceAliases: ["泗洪红亮"], connectedUsers: 1 },
    { id: "factory-8", supplierNumber: "E15", factoryName: "红燕", factoryCode: "HY", legalName: "涟水县昌鸿服装厂", address: "涟水县涟水城街道金城路23号107室", legalRepresentative: "李林华", authorizedAgent: "", contacts: [{ name: "刘红艳", phone: "18352368621" }], bank: "", bankAccount: "", sourceAliases: ["红燕"], connectedUsers: 2 },
    { id: "factory-9", supplierNumber: "E18", factoryName: "旭之梦", factoryCode: "XZM", legalName: "淮安茂鸿服饰有限公司", address: "江苏省淮安淮阴区淮高镇大兴庄村（袁庄村）五组58号", legalRepresentative: "朱兆俊", authorizedAgent: "", contacts: [{ name: "王素兰", phone: "15250871495" }], bank: "", bankAccount: "", sourceAliases: ["旭之梦"], connectedUsers: 1 },
    { id: "factory-10", supplierNumber: "E20", factoryName: "龙腾", factoryCode: "LT", legalName: "宿迁市龙杰帽业有限公司", address: "江苏省宿迁市宿迁豫区大兴镇水木新城32-33号商铺", legalRepresentative: "张春梅", authorizedAgent: "", contacts: [{ name: "张香梅", phone: "13228704488" }], bank: "", bankAccount: "", sourceAliases: ["龙腾"], connectedUsers: 1 },
    { id: "factory-11", supplierNumber: "E22", factoryName: "宇婷", factoryCode: "YT", legalName: "淮安市宇婷帽业有限公司", address: "淮安市淮安区仇桥镇北涧村东赵组27号", legalRepresentative: "赵凤兵", authorizedAgent: "", contacts: [{ name: "赵国飞", phone: "18036504888" }], bank: "", bankAccount: "", sourceAliases: ["宇婷"], connectedUsers: 0 },
    { id: "factory-12", supplierNumber: "E25", factoryName: "源洋", factoryCode: "YY", legalName: "涟水县鑫鹏制帽有限公司", address: "江苏省淮安市涟水县涟城街道军民中心村二区九排1号楼8、9号门面", legalRepresentative: "沈彩霞", authorizedAgent: "", contacts: [{ name: "小沈", phone: "13912063943" }], bank: "", bankAccount: "", sourceAliases: ["源洋"], connectedUsers: 1 },
    { id: "factory-13", supplierNumber: "E37", factoryName: "东阳凡杰-子听", factoryCode: "ZT", legalName: "东阳市子听服装厂", address: "浙江省金华市东阳市江北街道临江社区北鹿西街216号7号楼4楼402", legalRepresentative: "杨才洪", authorizedAgent: "", contacts: [{ name: "杨先生", phone: "18185875517" }, { name: "黄贤俊", phone: "13067685222" }], bank: "", bankAccount: "", sourceAliases: ["东阳凡杰", "子听"], connectedUsers: 2 },
    { id: "factory-14", supplierNumber: "E42", factoryName: "悦圆", factoryCode: "", legalName: "", address: "", legalRepresentative: "", authorizedAgent: "", contacts: [{ name: "代廷翠", phone: "18751787547" }], bank: "", bankAccount: "", sourceAliases: ["悦圆"], connectedUsers: 0 },
    { id: "factory-15", supplierNumber: "E46", factoryName: "盛泽岚", factoryCode: "SZL", legalName: "宿州盛泽岚服饰有限公司", address: "安徽省宿州市砀山县经济开发区淘美居产业园7栋", legalRepresentative: "王武朵", authorizedAgent: "", contacts: [], bank: "", bankAccount: "", sourceAliases: ["盛泽岚"], connectedUsers: 0 },
    { id: "factory-16", supplierNumber: "E84", factoryName: "希舟", factoryCode: "XZ", legalName: "铅山县青溪飞跃服饰厂", address: "上饶市铅山县青溪服务中心石溪村", legalRepresentative: "苏舟", authorizedAgent: "", contacts: [], bank: "", bankAccount: "", sourceAliases: ["希舟"], connectedUsers: 1 },
  ],
};

export const peopleManagementData = {
  currentUser: {
    id: "user-super-1",
    name: "煎饼",
    role: "admin",
    isSuperAdmin: true,
  },
  factoryApplications: [
    { id: "factory-application-1", name: "李兰", phone: "18036504889", phoneVerified: true, position: "工厂员工", requestedFactoryId: "factory-11", requestedFactoryName: "宇婷", appliedAt: "2026-08-17 08:46", status: "pending", reviewedBy: "", reviewedAt: "", rejectReason: "" },
    { id: "factory-application-2", name: "陈波", phone: "18751787548", phoneVerified: true, position: "工厂员工", requestedFactoryId: "factory-14", requestedFactoryName: "悦圆", appliedAt: "2026-08-16 15:20", status: "pending", reviewedBy: "", reviewedAt: "", rejectReason: "" },
    { id: "factory-application-3", name: "刘红艳", phone: "18352368621", phoneVerified: true, position: "老板", requestedFactoryId: "factory-8", requestedFactoryName: "红燕", appliedAt: "2026-08-15 11:06", status: "approved", reviewedBy: "煎饼", reviewedAt: "2026-08-15 11:20", rejectReason: "" },
    { id: "factory-application-4", name: "周敏", phone: "18800004126", phoneVerified: true, position: "工厂员工", requestedFactoryId: "factory-3", requestedFactoryName: "众乐鑫", appliedAt: "2026-08-14 13:18", status: "rejected", reviewedBy: "煎饼", reviewedAt: "2026-08-14 13:35", rejectReason: "无法确认与该工厂的人员关系" },
  ],
  users: [
    { id: "user-super-1", name: "煎饼", role: "admin", position: "生产部", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: true },
    { id: "user-admin-1", name: "烧麦", role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false },
    { id: "user-admin-2", name: "松子", role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false },
    { id: "user-admin-3", name: "橄榄", role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false },
    { id: "user-admin-4", name: "大葱", role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false },
    { id: "user-admin-5", name: "青椒", role: "admin", position: "跟单人员", factoryId: "", factoryName: "—", enabled: true, isSuperAdmin: false },
    { id: "user-factory-1", name: "王超", role: "factory", position: "老板", factoryId: "factory-1", factoryName: "禹帆", enabled: true, isSuperAdmin: false },
    { id: "user-factory-2", name: "王亮", role: "factory", position: "工厂员工", factoryId: "factory-2", factoryName: "玥鑫", enabled: true, isSuperAdmin: false },
    { id: "user-factory-3", name: "汪闪闪", role: "factory", position: "老板", factoryId: "factory-3", factoryName: "众乐鑫", enabled: true, isSuperAdmin: false },
    { id: "user-factory-4", name: "刘红艳", role: "factory", position: "老板", factoryId: "factory-8", factoryName: "红燕", enabled: true, isSuperAdmin: false },
    { id: "user-factory-5", name: "赵国飞", role: "factory", position: "工厂员工", factoryId: "factory-11", factoryName: "宇婷", enabled: false, isSuperAdmin: false },
  ],
};

export const pendingImportDetailData = {
  E81: {
    nearestDue: "2026-08-20",
    totalQuantity: 1800,
    shippedQuantity: 0,
    pendingQuantity: 1800,
    products: [
      { code: "KQ26143", name: "小护甲机能裤", colorSpec: "雾松灰 / 120", factory: "宇情", quantity: 600, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26143", name: "小护甲机能裤", colorSpec: "雾松灰 / 130", factory: "宇情", quantity: 600, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26143", name: "小护甲机能裤", colorSpec: "雾松灰 / 140", factory: "宇情", quantity: 600, validationKey: "ready", validationLabel: "通过" },
    ],
  },
  E82: {
    nearestDue: "2026-08-22",
    totalQuantity: 1500,
    shippedQuantity: 0,
    pendingQuantity: 1500,
    products: [
      { code: "KQ26418", name: "云感防晒衣", colorSpec: "云杉绿 / 110", factory: "昱斌", quantity: 500, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26418", name: "云感防晒衣", colorSpec: "云杉绿 / 120", factory: "昱斌", quantity: 500, validationKey: "needs-data", validationLabel: "资料待处理" },
      { code: "KQ26418", name: "云感防晒衣", colorSpec: "云杉绿 / 130", factory: "昱斌", quantity: 500, validationKey: "ready", validationLabel: "通过" },
    ],
  },
  E83: {
    nearestDue: "2026-08-24",
    totalQuantity: 1200,
    shippedQuantity: 0,
    pendingQuantity: 1200,
    products: [
      { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 52cm", factory: "盛泰", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", factory: "盛泰", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 56cm", factory: "盛泰", quantity: 400, validationKey: "ready", validationLabel: "通过" },
    ],
  },
  E86: {
    nearestDue: "2026-08-25",
    totalQuantity: 1200,
    shippedQuantity: 0,
    pendingQuantity: 1200,
    products: [
      { code: "KQ26516", name: "山野轻暖摇粒绒", colorSpec: "苔原绿 / 110", factory: "昱斌", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26516", name: "山野轻暖摇粒绒", colorSpec: "苔原绿 / 120", factory: "昱斌", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26516", name: "山野轻暖摇粒绒", colorSpec: "苔原绿 / 130", factory: "昱斌", quantity: 400, validationKey: "ready", validationLabel: "通过" },
    ],
  },
  E88: {
    nearestDue: "2026-08-25",
    totalQuantity: 1200,
    shippedQuantity: 0,
    pendingQuantity: 1200,
    products: [
      { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", factory: "启宏", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", factory: "启宏", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 56cm", factory: "启宏", quantity: 400, validationKey: "ready", validationLabel: "通过" },
    ],
  },
  E90: {
    nearestDue: "2026-08-25",
    totalQuantity: 1200,
    shippedQuantity: 0,
    pendingQuantity: 1200,
    products: [
      { code: "KQ26290", name: "小热皮绒绒裤", colorSpec: "岩灰 / 110", factory: "宇情", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26290", name: "小热皮绒绒裤", colorSpec: "岩灰 / 120", factory: "宇情", quantity: 400, validationKey: "ready", validationLabel: "通过" },
      { code: "KQ26290", name: "小热皮绒绒裤", colorSpec: "岩灰 / 130", factory: "宇情", quantity: 400, validationKey: "ready", validationLabel: "通过" },
    ],
  },
};

export const orderDetailData = {
  "078#": {
    orderNo: "078#",
    productName: "乐园游会吊带包屁衣",
    category: "服装",
    tracker: "松子",
    orderDate: "2026-07-26",
    source: "飞书多维表格导入",
    statusLabel: "已逾期",
    tone: "danger",
    totalQuantity: 3000,
    shippedQuantity: 1380,
    pendingQuantity: 1620,
    nearestDue: "2026-08-10",
    remark: "首批优先安排雾松灰 80、90 规格。",
    products: [
      { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 80", quantity: 1000, shippedQuantity: 620, pendingQuantity: 380 },
      { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 90", quantity: 1000, shippedQuantity: 480, pendingQuantity: 520 },
      { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 100", quantity: 1000, shippedQuantity: 280, pendingQuantity: 720 },
    ],
    factories: [
      {
        name: "昱斌",
        contractNo: "20260726-KK-YB",
        allocated: 1800,
        shipped: 1280,
        statusLabel: "已逾期",
        tone: "danger",
        contractReady: true,
        lines: [
          { colorSpec: "雾松灰 / 80", dueDate: "2026-08-10", quantity: 600, price: "23.94", shipped: 520 },
          { colorSpec: "雾松灰 / 90", dueDate: "2026-08-10", quantity: 600, price: "23.94", shipped: 480 },
          { colorSpec: "雾松灰 / 100", dueDate: "2026-08-10", quantity: 600, price: "23.94", shipped: 280 },
        ],
      },
      {
        name: "宇情",
        contractNo: "20260726-KK-YQ",
        allocated: 1200,
        shipped: 100,
        statusLabel: "未完成",
        tone: "info",
        contractReady: true,
        lines: [
          { colorSpec: "雾松灰 / 80", dueDate: "2026-08-10", quantity: 400, price: "", shipped: 100 },
          { colorSpec: "雾松灰 / 90", dueDate: "2026-08-10", quantity: 400, price: "", shipped: 0 },
          { colorSpec: "雾松灰 / 100", dueDate: "2026-08-10", quantity: 400, price: "", shipped: 0 },
        ],
      },
    ],
    shipments: [
      { no: "FH20260812-006", factory: "宇情", shipDate: "2026-08-12", declared: 100, statusLabel: "已发货", tone: "info" },
      { no: "FH20260808-003", factory: "昱斌", shipDate: "2026-08-08", declared: 760, statusLabel: "已发货", tone: "info" },
      { no: "FH20260805-001", factory: "昱斌", shipDate: "2026-08-05", declared: 520, statusLabel: "已发货", tone: "info" },
    ],
    logs: [
      { time: "2026-08-12 10:18", operator: "宇情工厂", action: "提交发货单 FH20260812-006", source: "工厂小程序" },
      { time: "2026-08-08 17:42", operator: "昱斌工厂", action: "提交发货单 FH20260808-003，发货记录立即生效", source: "工厂小程序" },
      { time: "2026-07-26 15:20", operator: "松子", action: "确认导入并发布订单", source: "管理员网页端" },
    ],
  },
  "092#": {
    orderNo: "092#",
    productName: "轻量防风马甲等 2 款",
    category: "服装",
    tracker: "青椒",
    orderDate: "2026-08-06",
    source: "飞书多维表格导入",
    statusKey: "draft",
    statusLabel: "草稿",
    tone: "draft",
    totalQuantity: 2800,
    shippedQuantity: 0,
    pendingQuantity: 2800,
    nearestDue: "2026-08-22",
    remark: "—",
    products: [
      { code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 110", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 120", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 130", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 140", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 120", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 130", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
      { code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 140", quantity: 400, shippedQuantity: 0, pendingQuantity: 400 },
    ],
    factories: [{
      name: "盛泰",
      contractNo: "—",
      allocated: 2800,
      shipped: 0,
      statusLabel: "草稿",
      tone: "draft",
      contractReady: false,
      lines: [
        { code: "KQ26721", colorSpec: "雾蓝 / 110", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26721", colorSpec: "雾蓝 / 120", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26721", colorSpec: "雾蓝 / 130", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26721", colorSpec: "雾蓝 / 140", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26722", colorSpec: "岩灰 / 120", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26722", colorSpec: "岩灰 / 130", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
        { code: "KQ26722", colorSpec: "岩灰 / 140", dueDate: "2026-08-22", quantity: 400, price: "", shipped: 0 },
      ],
    }],
    shipments: [],
    logs: [{ time: "2026-08-12 10:15", operator: "青椒", action: "确认导入为草稿", source: "管理员网页端" }],
  },
};

export function importPendingOrdersAsDrafts(orderNos) {
  const importedAt = new Date().toISOString();
  const orderDate = importedAt.slice(0, 10);
  const requestedOrderNos = new Set(orderNos);
  const importedOrders = pendingImportData.orders.filter((order) => (
    requestedOrderNos.has(order.orderNo)
    && order.statusKey === "pending"
    && order.validationKey === "ready"
    && pendingImportDetailData[order.orderNo]
  ));

  importedOrders.forEach((order) => {
    const detail = pendingImportDetailData[order.orderNo];
    const products = detail.products.map((product) => ({
      code: product.code,
      name: product.name,
      colorSpec: product.colorSpec,
      quantity: product.quantity,
      shippedQuantity: 0,
      pendingQuantity: product.quantity,
    }));
    const factoryNames = [...new Set(detail.products.flatMap((product) => product.factory.split(/[、,，]/).map((value) => value.trim())))];
    const totalQuantity = Number(detail.totalQuantity) || detail.products.reduce((sum, product) => sum + Number(product.quantity || 0), 0);

    order.statusKey = "imported";

    if (!orderListData.orders.some((item) => item.orderNo === order.orderNo)) {
      orderListData.orders.unshift({
        id: `order-${order.orderNo.toLocaleLowerCase("zh-CN")}`,
        orderNo: order.orderNo,
        productName: order.productName,
        category: order.category,
        specSummary: `${detail.products.length} 个颜色 / 规格`,
        tracker: order.tracker,
        factory: order.factory,
        nearestDue: detail.nearestDue,
        shippedPercent: 0,
        shippedText: `0 / ${totalQuantity.toLocaleString("zh-CN")}`,
        statusKey: "draft",
        statusLabel: "草稿",
        tone: "draft",
        overdueDays: 0,
        orderDate,
        updatedAt: importedAt,
      });
    }

    orderDetailData[order.orderNo] = {
      orderNo: order.orderNo,
      productName: order.productName,
      category: order.category,
      tracker: order.tracker,
      orderDate,
      source: "飞书多维表格导入",
      statusKey: "draft",
      statusLabel: "草稿",
      tone: "draft",
      totalQuantity,
      shippedQuantity: 0,
      pendingQuantity: totalQuantity,
      nearestDue: detail.nearestDue,
      remark: "—",
      products,
      factories: factoryNames.map((factory) => {
        const lines = detail.products
          .filter((product) => product.factory.split(/[、,，]/).map((value) => value.trim()).includes(factory))
          .map((product) => ({
            code: product.code,
            colorSpec: product.colorSpec,
            dueDate: detail.nearestDue,
            quantity: product.quantity,
            price: "",
            shipped: 0,
          }));
        return {
          name: factory,
          contractNo: "—",
          allocated: lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0),
          shipped: 0,
          statusLabel: "草稿",
          tone: "draft",
          contractReady: false,
          lines,
        };
      }),
      shipments: [],
      logs: [{ time: importedAt.replace("T", " ").slice(0, 16), operator: order.tracker, action: "确认导入为草稿", source: "管理员网页端" }],
    };
  });

  return importedOrders;
}

export function deletePendingImportOrder(orderNo) {
  const order = pendingImportData.orders.find((item) => item.orderNo === orderNo);
  if (!order || order.statusKey !== "pending") return false;
  order.statusKey = "deleted";
  return true;
}

export const repairListData = {
  repairs: [
    {
      repairNo: "FX20260817-001",
      factory: "旭之梦",
      returnedAt: "2026-08-17 15:20",
      sourceFile: "E18质检(1).xlsx",
      warehouseReturnQuantity: 36,
      repairedQuantity: 18,
      scrappedQuantity: 2,
      statusKey: "processing",
      statusLabel: "未完成",
      tone: "info",
      summary: { boxCount: 3, lineCount: 4 },
      lines: [
        { boxNo: "1", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", quantity: 8, reason: "帽檐车线不顺", photoCount: 1 },
        { boxNo: "1", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", quantity: 10, reason: "面料污渍", photoCount: 1 },
        { boxNo: "2", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "沙岩米 / 54cm", quantity: 12, reason: "帽围尺寸偏小", photoCount: 0 },
        { boxNo: "3", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "沙岩米 / 56cm", quantity: 6, reason: "扣具松动", photoCount: 1 },
      ],
      returns: [
        {
          batchNo: 1,
          shippedAt: "2026-08-17 14:10",
          repairedQuantity: 18,
          scrappedQuantity: 2,
          lines: [
            { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", repairedQuantity: 8, scrappedQuantity: 0 },
            { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", repairedQuantity: 6, scrappedQuantity: 1 },
            { code: "KQ26368", name: "探索家渔夫帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 4, scrappedQuantity: 1 },
          ],
        },
      ],
    },
    {
      repairNo: "FX20260816-002",
      factory: "龙腾",
      returnedAt: "2026-08-16 14:35",
      sourceFile: "E22质检.xlsx",
      warehouseReturnQuantity: 48,
      repairedQuantity: 0,
      scrappedQuantity: 0,
      statusKey: "pending",
      statusLabel: "未完成",
      tone: "warning",
      summary: { boxCount: 4, lineCount: 3 },
      lines: [
        { boxNo: "1", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 120", quantity: 16, reason: "拉链不顺", photoCount: 1 },
        { boxNo: "2", code: "KQ26721", name: "轻量防风马甲", colorSpec: "雾蓝 / 130", quantity: 20, reason: "前片色差", photoCount: 2 },
        { boxNo: "3-4", code: "KQ26722", name: "山野轻量长裤", colorSpec: "岩灰 / 130", quantity: 12, reason: "裤脚跳线", photoCount: 0 },
      ],
      returns: [],
    },
    {
      repairNo: "FX20260814-003",
      factory: "红燕",
      returnedAt: "2026-08-14 10:18",
      sourceFile: "E61质检.xlsx",
      warehouseReturnQuantity: 28,
      repairedQuantity: 24,
      scrappedQuantity: 4,
      statusKey: "completed",
      statusLabel: "已完成",
      tone: "success",
      summary: { boxCount: 2, lineCount: 3 },
      lines: [
        { boxNo: "1", code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 52cm", quantity: 10, reason: "帽檐变形", photoCount: 1 },
        { boxNo: "1", code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", quantity: 8, reason: "车缝线头", photoCount: 0 },
        { boxNo: "2", code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 56cm", quantity: 10, reason: "帽围尺寸偏差", photoCount: 1 },
      ],
      returns: [
        {
          batchNo: 1,
          shippedAt: "2026-08-15 09:20",
          repairedQuantity: 14,
          scrappedQuantity: 2,
          lines: [
            { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 52cm", repairedQuantity: 8, scrappedQuantity: 1 },
            { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 6, scrappedQuantity: 1 },
          ],
        },
        {
          batchNo: 2,
          shippedAt: "2026-08-16 13:35",
          repairedQuantity: 10,
          scrappedQuantity: 2,
          lines: [
            { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 5, scrappedQuantity: 1 },
            { code: "KQ26352", name: "海岛轻量防晒帽", colorSpec: "沙岩米 / 56cm", repairedQuantity: 5, scrappedQuantity: 1 },
          ],
        },
      ],
    },
    {
      repairNo: "FX20260813-004",
      factory: "众乐鑫",
      returnedAt: "2026-08-13 16:42",
      sourceFile: "质检退回_众乐鑫.xlsx",
      warehouseReturnQuantity: 42,
      repairedQuantity: 20,
      scrappedQuantity: 3,
      statusKey: "processing",
      statusLabel: "未完成",
      tone: "info",
      summary: { boxCount: 3, lineCount: 3 },
      lines: [
        { boxNo: "1", code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 80", quantity: 14, reason: "领口尺寸偏小", photoCount: 1 },
        { boxNo: "2", code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 90", quantity: 16, reason: "印花偏位", photoCount: 1 },
        { boxNo: "3", code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 100", quantity: 12, reason: "面料污渍", photoCount: 0 },
      ],
      returns: [
        {
          batchNo: 1,
          shippedAt: "2026-08-17 10:26",
          repairedQuantity: 20,
          scrappedQuantity: 3,
          lines: [
            { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 80", repairedQuantity: 8, scrappedQuantity: 1 },
            { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 90", repairedQuantity: 7, scrappedQuantity: 1 },
            { code: "KQ26143", name: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 100", repairedQuantity: 5, scrappedQuantity: 1 },
          ],
        },
      ],
    },
  ],
};

export const repairImportPreview = {
  factory: "旭之梦",
  warehouseReturnQuantity: 36,
  boxCount: 3,
  lineCount: 4,
  lines: [
    { boxNo: "1", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", quantity: 8, reason: "帽檐车线不顺", photoCount: 1 },
    { boxNo: "1", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", quantity: 10, reason: "面料污渍", photoCount: 1 },
    { boxNo: "2", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "沙岩米 / 54cm", quantity: 12, reason: "帽围尺寸偏小", photoCount: 0 },
    { boxNo: "3", code: "KQ26368", name: "探索家渔夫帽", colorSpec: "沙岩米 / 56cm", quantity: 6, reason: "扣具松动", photoCount: 1 },
  ],
};
