import { currentApiBaseUrl } from "./api/config";

interface AppState {
  globalData: {
    apiBaseUrl: string;
  };
}

App<AppState>({
  globalData: {
    apiBaseUrl: "",
  },
  onLaunch() {
    this.globalData.apiBaseUrl = currentApiBaseUrl();
  },
});
