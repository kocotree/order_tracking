export function getCurrentRoute() {
  const hash = window.location.hash.replace(/^#/, "") || "/dashboard";
  return hash.split("?")[0];
}

export function getCurrentLocation() {
  return window.location.hash.replace(/^#/, "") || "/dashboard";
}

export function buildRouteWithReturn(route, returnRoute) {
  return `${route}?return=${encodeURIComponent(returnRoute)}`;
}

export function getReturnRoute(defaultRoute) {
  const query = getCurrentLocation().split("?")[1] ?? "";
  const returnRoute = new URLSearchParams(query).get("return");
  return returnRoute?.startsWith("/") ? returnRoute : defaultRoute;
}

export function ensureInitialRoute() {
  if (!window.location.hash) {
    window.location.replace("#/dashboard");
  }
}

export function startRouter(renderRoute) {
  const handleRoute = () => renderRoute(getCurrentRoute());
  window.addEventListener("hashchange", handleRoute);
  handleRoute();
  return () => window.removeEventListener("hashchange", handleRoute);
}
