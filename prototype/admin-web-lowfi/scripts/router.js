export function getCurrentRoute() {
  const hash = window.location.hash.replace(/^#/, "") || "/dashboard";
  return hash.split("?")[0];
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
