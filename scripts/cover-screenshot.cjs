const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const root = path.resolve(__dirname, '..');
const [inputArg, outputArg, widthArg, heightArg] = process.argv.slice(2);
if (!inputArg || !outputArg) {
  console.error('Usage: 封面截图.cmd input.html output.png [width=1080] [height=1920]');
  process.exit(2);
}
const input = path.resolve(inputArg);
const output = path.resolve(outputArg);
const width = Number(widthArg || 1080);
const height = Number(heightArg || 1920);
if (!fs.existsSync(input) || path.extname(input).toLowerCase() !== '.html') {
  console.error('Input must be an existing local HTML file.');
  process.exit(2);
}
if (!Number.isInteger(width) || !Number.isInteger(height) || width < 320 || height < 320) {
  console.error('Width and height must be integers >= 320.');
  process.exit(2);
}
const configPath = path.join(root, 'runtime.local.json');
let config = {};
if (fs.existsSync(configPath)) config = JSON.parse(fs.readFileSync(configPath, 'utf8').replace(/^\uFEFF/, ''));
const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || config.browser;
if (!executablePath || !fs.existsSync(executablePath)) {
  console.error('Browser missing. Run 一键安装并检查.cmd first.');
  process.exit(2);
}
const puppeteer = require(path.join(root, 'animation-local', 'node_modules', 'puppeteer'));
(async () => {
  const browser = await puppeteer.launch({executablePath, headless: true});
  try {
    const page = await browser.newPage();
    await page.setViewport({width, height, deviceScaleFactor: 1});
    await page.goto(pathToFileURL(input).href, {waitUntil: 'networkidle0'});
    fs.mkdirSync(path.dirname(output), {recursive: true});
    await page.screenshot({path: output, type: 'png', fullPage: false});
    console.log(output);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
