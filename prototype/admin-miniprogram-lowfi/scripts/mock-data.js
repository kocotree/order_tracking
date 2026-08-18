(function registerMockData() {
  const orders = [
    {
      id: "order-078",
      orderNo: "078#",
      productName: "乐园游会吊带包屁衣",
      specs: "蓝色/90、蓝色/100、杏色/90",
      tracker: "松子",
      factories: ["昱斌", "宇情"],
      contractShipDate: "2026-08-10",
      contractShipDateLabel: "08月10日",
      overdueDays: 8,
      shipped: 1380,
      total: 3000,
      progress: 46,
      status: "shipping",
      statusLabel: "发货中",
      orderDate: "2026-07-26",
      updatedAt: "2026-08-18T08:40:00",
    },
    {
      id: "order-369",
      orderNo: "369#",
      productName: "小热皮绒绒裤",
      specs: "棕色/100、棕色/110",
      tracker: "烧麦",
      factories: ["宇情"],
      contractShipDate: "2026-08-18",
      contractShipDateLabel: "今天",
      overdueDays: 0,
      shipped: 1440,
      total: 2000,
      progress: 72,
      detailProducts: [
        { productName: "小热皮绒绒裤", colorCode: "棕色/100", shipped: 720, ordered: 1000 },
        { productName: "小热皮绒绒裤", colorCode: "棕色/110", shipped: 720, ordered: 1000 },
      ],
      status: "shipping",
      statusLabel: "发货中",
      orderDate: "2026-07-29",
      updatedAt: "2026-08-18T08:10:00",
    },
    {
      id: "order-088",
      orderNo: "088#",
      productName: "云朵软壳冲锋衣",
      specs: "松石绿/110、松石绿/120、米白/110",
      tracker: "大葱",
      factories: ["昱斌"],
      contractShipDate: "2026-08-21",
      contractShipDateLabel: "08月21日",
      overdueDays: 0,
      shipped: 0,
      total: 1600,
      progress: 0,
      detailProducts: [
        { productName: "云朵软壳冲锋衣", colorCode: "松石绿/110", shipped: 0, ordered: 600 },
        { productName: "云朵软壳冲锋衣", colorCode: "松石绿/120", shipped: 0, ordered: 500 },
        { productName: "云朵软壳冲锋衣", colorCode: "米白/110", shipped: 0, ordered: 500 },
      ],
      status: "pending",
      statusLabel: "待发货",
      orderDate: "2026-08-03",
      updatedAt: "2026-08-17T16:30:00",
    },
    {
      id: "order-246",
      orderNo: "246#",
      productName: "秋日摇粒绒外套",
      specs: "雾蓝/120、雾蓝/130",
      tracker: "橄榄",
      factories: ["盛泰"],
      contractShipDate: "2026-08-12",
      contractShipDateLabel: "08月12日",
      overdueDays: 0,
      shipped: 1800,
      total: 1800,
      progress: 100,
      detailProducts: [
        { productName: "秋日摇粒绒外套", colorCode: "雾蓝/120", shipped: 900, ordered: 900 },
        { productName: "秋日摇粒绒外套", colorCode: "雾蓝/130", shipped: 900, ordered: 900 },
      ],
      status: "completed",
      statusLabel: "已完成",
      orderDate: "2026-07-20",
      updatedAt: "2026-08-16T14:20:00",
    },
    {
      id: "order-092",
      orderNo: "092#",
      productName: "轻量防风马甲等2款",
      specs: "橙色/110、藏青/120 等7个规格",
      tracker: "青椒",
      factories: ["禹帆"],
      contractShipDate: "2026-08-24",
      contractShipDateLabel: "08月24日",
      overdueDays: 0,
      shipped: 0,
      total: 2800,
      progress: 0,
      detailProducts: [
        { productName: "轻量防风马甲", colorCode: "橙色/110", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "橙色/120", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "藏青/110", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "藏青/120", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "米白/110", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "米白/120", shipped: 0, ordered: 400 },
        { productName: "轻量防风马甲", colorCode: "米白/130", shipped: 0, ordered: 400 },
      ],
      status: "draft",
      statusLabel: "草稿",
      orderDate: "2026-08-06",
      updatedAt: "2026-08-15T10:15:00",
    },
  ];

  const statusOptions = [
    ["all", "全部状态"],
    ["pending", "待发货"],
    ["shipping", "发货中"],
    ["completed", "已完成"],
    ["draft", "草稿"],
  ];

  const sortOptions = [
    ["urgent", "默认紧急程度"],
    ["due-asc", "合同出货时间升序"],
    ["due-desc", "合同出货时间降序"],
    ["order-newest", "订单日期最新"],
    ["updated-newest", "更新时间最新"],
  ];

  const detailOverrides = {
    "order-078": {
      pendingCancellationCount: 0,
      factoryProgress: [
        {
          name: "昱斌",
          allocated: 1800,
          shipped: 900,
          products: [
            { productName: "乐园游会吊带包屁衣", colorCode: "蓝色/90", shipped: 450, ordered: 450 },
            { productName: "乐园游会吊带包屁衣", colorCode: "蓝色/100", shipped: 450, ordered: 450 },
            { productName: "乐园游会吊带包屁衣", colorCode: "杏色/90", shipped: 0, ordered: 900 },
          ],
        },
        {
          name: "宇情",
          allocated: 1200,
          shipped: 480,
          products: [
            { productName: "乐园游会吊带包屁衣", colorCode: "蓝色/100", shipped: 480, ordered: 480 },
            { productName: "乐园游会吊带包屁衣", colorCode: "杏色/90", shipped: 0, ordered: 720 },
          ],
        },
      ],
      shipments: [
        { no: "FH20260812-004", factory: "宇情", quantity: 480, status: "shipped", statusLabel: "已发货" },
        { no: "FH20260810-002", factory: "昱斌", quantity: 900, status: "shipped", statusLabel: "已发货" },
      ],
    },
  };

  const shipmentDetails = {
    "FH20260812-004": {
      no: "FH20260812-004",
      status: "shipped",
      statusLabel: "已发货",
      factory: "宇情",
      shipDate: "2026-08-12",
      totalQuantity: 480,
      orderNos: ["078#"],
      lines: [
        { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 480 },
      ],
      boxes: [
        {
          boxNo: "01",
          items: [
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 240 },
          ],
        },
        {
          boxNo: "02",
          items: [
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 240 },
          ],
        },
      ],
      proofs: ["发货凭证 1", "发货凭证 2"],
      note: "共2箱，请按箱号核对。",
      logs: [
        { action: "提交发货单", date: "2026-08-12", operator: "宇情工厂", source: "工厂小程序" },
      ],
    },
    "FH20260810-002": {
      no: "FH20260810-002",
      status: "shipped",
      statusLabel: "已发货",
      factory: "昱斌",
      shipDate: "2026-08-10",
      totalQuantity: 900,
      orderNos: ["078#"],
      lines: [
        { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/90", quantity: 450 },
        { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 450 },
      ],
      boxes: [
        {
          boxNo: "01",
          items: [
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/90", quantity: 225 },
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 225 },
          ],
        },
        {
          boxNo: "02",
          items: [
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/90", quantity: 225 },
            { orderNo: "078#", productName: "乐园游会吊带包屁衣", colorSpec: "蓝色/100", quantity: 225 },
          ],
        },
      ],
      proofs: ["发货凭证 1"],
      note: "无",
      logs: [
        { action: "提交发货单", date: "2026-08-10", operator: "昱斌工厂", source: "工厂小程序" },
      ],
    },
  };

  const repairRecords = [
    {
      repairNo: "FX20260817-001",
      factory: "旭之梦",
      returnDate: "2026-08-17",
      warehouseReturnQuantity: 36,
      repairedQuantity: 18,
      scrappedQuantity: 2,
    },
    {
      repairNo: "FX20260816-002",
      factory: "龙腾",
      returnDate: "2026-08-16",
      warehouseReturnQuantity: 48,
      repairedQuantity: 0,
      scrappedQuantity: 0,
    },
    {
      repairNo: "FX20260814-003",
      factory: "红燕",
      returnDate: "2026-08-14",
      warehouseReturnQuantity: 28,
      repairedQuantity: 24,
      scrappedQuantity: 4,
    },
    {
      repairNo: "FX20260813-004",
      factory: "众乐鑫",
      returnDate: "2026-08-13",
      warehouseReturnQuantity: 42,
      repairedQuantity: 20,
      scrappedQuantity: 3,
    },
  ];

  const repairDetails = {
    "FX20260817-001": {
      qualityLines: [
        { productName: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", warehouseReturnQuantity: 8, boxNo: "1", reason: "帽檐车线不顺" },
        { productName: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", warehouseReturnQuantity: 10, boxNo: "1", reason: "面料污渍" },
        { productName: "探索家渔夫帽", colorSpec: "沙岩米 / 54cm", warehouseReturnQuantity: 12, boxNo: "2", reason: "帽围尺寸偏小" },
        { productName: "探索家渔夫帽", colorSpec: "沙岩米 / 56cm", warehouseReturnQuantity: 6, boxNo: "3", reason: "扣具松动" },
      ],
      returnBatches: [
        {
          id: "return-20260817-1",
          returnDate: "2026-08-17",
          lines: [
            { productName: "探索家渔夫帽", colorSpec: "森林绿 / 52cm", repairedQuantity: 8, scrappedQuantity: 0, warehouseReturnQuantity: 8 },
            { productName: "探索家渔夫帽", colorSpec: "森林绿 / 54cm", repairedQuantity: 6, scrappedQuantity: 1, warehouseReturnQuantity: 10 },
            { productName: "探索家渔夫帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 4, scrappedQuantity: 1, warehouseReturnQuantity: 12 },
          ],
        },
      ],
    },
    "FX20260816-002": {
      qualityLines: [
        { productName: "轻量防风马甲", colorSpec: "雾蓝 / 120", warehouseReturnQuantity: 16, boxNo: "1", reason: "拉链不顺" },
        { productName: "轻量防风马甲", colorSpec: "雾蓝 / 130", warehouseReturnQuantity: 20, boxNo: "2", reason: "前片色差" },
        { productName: "山野轻量长裤", colorSpec: "岩灰 / 130", warehouseReturnQuantity: 12, boxNo: "3-4", reason: "裤脚跳线" },
      ],
      returnBatches: [],
    },
    "FX20260814-003": {
      qualityLines: [
        { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 52cm", warehouseReturnQuantity: 10, boxNo: "1", reason: "帽檐变形" },
        { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", warehouseReturnQuantity: 8, boxNo: "1", reason: "车缝线头" },
        { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 56cm", warehouseReturnQuantity: 10, boxNo: "2", reason: "帽围尺寸偏差" },
      ],
      returnBatches: [
        {
          id: "return-20260816-1",
          returnDate: "2026-08-16",
          lines: [
            { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 5, scrappedQuantity: 1, warehouseReturnQuantity: 8 },
            { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 56cm", repairedQuantity: 5, scrappedQuantity: 1, warehouseReturnQuantity: 10 },
          ],
        },
        {
          id: "return-20260815-1",
          returnDate: "2026-08-15",
          lines: [
            { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 52cm", repairedQuantity: 8, scrappedQuantity: 1, warehouseReturnQuantity: 10 },
            { productName: "海岛轻量防晒帽", colorSpec: "沙岩米 / 54cm", repairedQuantity: 6, scrappedQuantity: 1, warehouseReturnQuantity: 8 },
          ],
        },
      ],
    },
    "FX20260813-004": {
      qualityLines: [
        { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 80", warehouseReturnQuantity: 14, boxNo: "1", reason: "领口尺寸偏小" },
        { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 90", warehouseReturnQuantity: 16, boxNo: "2", reason: "印花偏位" },
        { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 100", warehouseReturnQuantity: 12, boxNo: "3", reason: "面料污渍" },
      ],
      returnBatches: [
        {
          id: "return-20260817-2",
          returnDate: "2026-08-17",
          lines: [
            { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 80", repairedQuantity: 8, scrappedQuantity: 1, warehouseReturnQuantity: 14 },
            { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 90", repairedQuantity: 7, scrappedQuantity: 1, warehouseReturnQuantity: 16 },
            { productName: "乐园游会吊带包屁衣", colorSpec: "雾松灰 / 100", repairedQuantity: 5, scrappedQuantity: 1, warehouseReturnQuantity: 12 },
          ],
        },
      ],
    },
  };

  window.AdminPrototypeData = { orders, statusOptions, sortOptions, detailOverrides, shipmentDetails, repairRecords, repairDetails };
})();
