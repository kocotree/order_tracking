import type { components } from "./generated";
import { authorizedRequest } from "./identity";

export type FactoryApplication = components["schemas"]["FactoryApplicationResponse"];
export type FactoryOption = components["schemas"]["FactoryOptionResponse"];

export const factoryApi = {
  listFactories: (keyword = "") =>
    authorizedRequest<components["schemas"]["FactoryOptionListResponse"]>({
      url: `/factories?keyword=${encodeURIComponent(keyword)}`,
      method: "GET",
    }),
  submitApplication: (realName: string, position: "owner" | "employee", factoryId: string) =>
    authorizedRequest<FactoryApplication>({
      url: "/factory-applications",
      method: "POST",
      data: { realName, position, factoryId },
    }),
  getMyApplication: () =>
    authorizedRequest<FactoryApplication>({
      url: "/factory-applications/me",
      method: "GET",
    }).then((application) => application as FactoryApplication | null),
};
