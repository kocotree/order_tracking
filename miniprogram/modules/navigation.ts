export type NavigationItem = {
  key: string;
  label: string;
  path: string;
  icon: string;
  activeIcon: string;
};

export function adminNavigationItems(): NavigationItem[] {
  return [
    {
      key: "primary",
      label: "订单",
      path: "/pages/admin-orders/admin-orders",
      icon: "/assets/icons/admin-orders.svg",
      activeIcon: "/assets/icons/admin-orders-active.svg",
    },
    {
      key: "shipments",
      label: "发货",
      path: "/pages/admin-shipments/admin-shipments",
      icon: "/assets/icons/factory-shipments.svg",
      activeIcon: "/assets/icons/factory-shipments-active.svg",
    },
    {
      key: "profile",
      label: "我的",
      path: "/pages/profile/profile",
      icon: "/assets/icons/admin-profile.svg",
      activeIcon: "/assets/icons/admin-profile-active.svg",
    },
  ];
}
