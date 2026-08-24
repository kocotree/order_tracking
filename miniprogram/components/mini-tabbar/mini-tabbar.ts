type TabbarItem = {
  key: string;
  label: string;
  path: string;
  icon: string;
  activeIcon?: string;
};

Component({
  properties: {
    items: { type: Array, value: [] as TabbarItem[] },
    activeKey: { type: String, value: "" },
  },
  methods: {
    openItem(event: WechatMiniprogram.TouchEvent) {
      const { key, path } = event.currentTarget.dataset as { key?: string; path?: string };
      if (!path || key === this.data.activeKey) return;
      wx.reLaunch({ url: path });
    },
  },
});
