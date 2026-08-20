import { readFile } from "node:fs/promises";

const requiredFiles = [
  "app.ts",
  "app.json",
  "app.wxss",
  "pages/auth/auth.ts",
  "pages/auth/auth.json",
  "pages/auth/auth.wxml",
  "pages/auth/auth.wxss",
  "pages/status/status.ts",
  "pages/status/status.json",
  "pages/status/status.wxml",
  "pages/status/status.wxss",
  "pages/profile/profile.ts",
  "pages/profile/profile.json",
  "pages/profile/profile.wxml",
  "pages/profile/profile.wxss",
  "project.config.json.example",
];

await Promise.all(requiredFiles.map((file) => readFile(file)));
JSON.parse(await readFile("app.json", "utf8"));
for (const page of ["auth", "status", "profile"]) {
  JSON.parse(await readFile(`pages/${page}/${page}.json`, "utf8"));
}
const projectConfig = JSON.parse(await readFile("project.config.json.example", "utf8"));
if (projectConfig.appid !== "touristappid") {
  throw new Error("project.config.json.example must not contain a real AppID");
}
console.log("Mini Program project structure is valid.");
