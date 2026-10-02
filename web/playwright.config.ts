import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:8765', headless: true, viewport: { width: 1440, height: 1100 } },
  webServer: {
    command: 'uv run --project .. uvicorn tests.browser_app:app --app-dir .. --host 127.0.0.1 --port 8765',
    url: 'http://127.0.0.1:8765/api/config',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
