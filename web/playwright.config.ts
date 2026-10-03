import { defineConfig } from '@playwright/test';
const port = process.env.IDEA_TEST_PORT || '8765';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  use: { baseURL: `http://127.0.0.1:${port}`, headless: true, viewport: { width: 1440, height: 1100 } },
  webServer: {
    command: `uv run --project .. uvicorn tests.browser_app:app --app-dir .. --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/config`,
    reuseExistingServer: false,
    timeout: 30000,
  },
});
