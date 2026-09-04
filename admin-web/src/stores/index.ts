import { defineStore } from "pinia";

import {
  ApiError,
  identityApi,
  type User,
} from "@/api/client";

export const useIdentityStore = defineStore("identity", {
  state: () => ({
    currentUser: null as User | null,
    userLoaded: false,
  }),
  actions: {
    async loadCurrentUser(force = false): Promise<User | null> {
      if (this.userLoaded && !force) return this.currentUser;
      try {
        this.currentUser = await identityApi.getMe();
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        this.currentUser = null;
      }
      this.userLoaded = true;
      return this.currentUser;
    },
    async logout(): Promise<void> {
      await identityApi.logout();
      this.$reset();
    },
  },
});

export { createPinia } from "pinia";
