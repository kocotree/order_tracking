// Local UI contract test. MySQL transactions are tested separately by pytest.
// Start admin-web Vite first. Requires the already installed playwright-cli and Edge.
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import setupReceiptFixture from "./shipment-receipt-fixture.mjs";

const root = resolve(import.meta.dirname, "../..");
const output = resolve(root, "output/playwright");
mkdirSync(output, { recursive: true });
const baseUrl = process.argv[2] || "http://127.0.0.1:5184";
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(baseUrl)) throw new Error("Use a local test server");
const session = "shipment-receipt-check";
function cli(...args) {
  const result = spawnSync("playwright-cli", [`-s=${session}`, ...args], { cwd: root, encoding: "utf8" });
  if (result.status !== 0 || /^### Error/m.test(result.stdout)) throw new Error(result.stdout + result.stderr);
  return result.stdout;
}
const setup = setupReceiptFixture.toString();
const scenario = `async page => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const quantity = page.getByRole('spinbutton', { name: '箱号 1 6942649419550 核对数量', exact: true });
  const save = page.getByRole('button', { name: '保存', exact: true });
  const confirm = page.getByRole('button', { name: '确认收货', exact: true });
  const total = page.locator('.shipment-summary-grid .detail-summary-number').first();
  await quantity.fill('0');
  assert(await total.textContent() === '550', 'Box change must update the total');
  await confirm.click();
  await page.getByRole('alert').filter({hasText:'请先保存'}).waitFor();
  assert(await quantity.isVisible(), 'Unsaved confirmation must remain editable');
  await page.route('**/api/v1/admin/shipments/issue44/receipt', route => route.fulfill({status:409,json:{message:'核对版本已变化，请重新读取后再保存'}}), {times:1});
  await save.click();
  await page.getByRole('alert').filter({hasText:'核对版本已变化'}).waitFor();
  assert(await quantity.inputValue() === '0', 'Failed save must preserve input');
  await save.click();
  await page.getByRole('status').filter({hasText:'核对草稿已保存'}).waitFor();
  await page.reload();
  await quantity.waitFor();
  assert(await quantity.inputValue() === '0', 'Saved draft must restore after reload');
  assert(await total.textContent() === '550', 'Restored total must match boxes');
  assert((await page.evaluate(() => navigator.userAgent)).includes('Edg/'), 'Must run Microsoft Edge');
  for (const width of [1440, 1280]) {
    await page.setViewportSize({width,height:1000});
    const style = await page.locator('.detail-sequence-column').evaluate(el => {
      const style = getComputedStyle(el);
      return [el.getBoundingClientRect().width,style.paddingLeft,style.paddingRight,style.textAlign,style.whiteSpace];
    });
    assert(JSON.stringify(style) === JSON.stringify([52,'8px','8px','center','nowrap']), 'Sequence column dimensions');
  }
  await confirm.click();
  await page.getByRole('status').filter({hasText:'收货已确认'}).waitFor();
  assert(await page.getByRole('spinbutton').count() === 0, 'Confirmed quantities must be locked');
  assert(await total.textContent() === '550', 'Confirmed total must match saved draft');
  await page.reload();
  await page.locator('.receipt-confirmation').waitFor();
  assert(await page.getByRole('spinbutton').count() === 0, 'Reload must keep confirmed receipt locked');
  await page.screenshot({path:${JSON.stringify(resolve(output, "receipt-edge-verified.png"))},fullPage:true});
  console.log('PASS: Edge save failure, draft restore, confirmation, totals, locking and table dimensions');
}`;
const setupPath = resolve(output, "receipt-setup.js");
const scenarioPath = resolve(output, "receipt-scenario.js");
writeFileSync(setupPath, setup);
writeFileSync(scenarioPath, scenario);
try {
  cli("open", "about:blank", "--browser", "msedge");
  cli("run-code", "--filename", setupPath);
  cli("goto", `${baseUrl}/shipments/issue44`);
  cli("snapshot");
  const evidence = cli("run-code", "--filename", scenarioPath);
  writeFileSync(resolve(output, "receipt-edge-result.txt"), evidence);
  console.log("PASS: Edge receipt UI functional checks (controlled API responses)");
} finally {
  cli("close");
}
