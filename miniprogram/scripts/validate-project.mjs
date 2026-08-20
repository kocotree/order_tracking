import { readFile } from "node:fs/promises";

const requiredFiles = [
  "app.ts",
  "app.json",
  "app.wxss",
  "pages/index/index.ts",
  "pages/index/index.json",
  "pages/index/index.wxml",
  "pages/index/index.wxss",
  "project.config.json.example",
];

await Promise.all(requiredFiles.map((file) => readFile(file)));
JSON.parse(await readFile("app.json", "utf8"));
JSON.parse(await readFile("pages/index/index.json", "utf8"));
const projectConfig = JSON.parse(await readFile("project.config.json.example", "utf8"));
if (projectConfig.appid !== "touristappid") {
  throw new Error("project.config.json.example must not contain a real AppID");
}
console.log("Mini Program project structure is valid.");
