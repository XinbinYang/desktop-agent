import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:15174',
    headless: true,
  },
  webServer: [
    {
      command: 'cd ../backend && python -X utf8 -c "import uvicorn,asyncio;config=uvicorn.Config(\'app.main:app\',host=\'127.0.0.1\',port=18768,log_level=\'error\');server=uvicorn.Server(config);asyncio.run(server.serve())"',
      port: 18768,
      reuseExistingServer: false,
      timeout: 45000,
    },
    {
      command: 'npx vite --host 127.0.0.1 --port 15174 --strictPort',
      port: 15174,
      reuseExistingServer: false,
      timeout: 45000,
    },
  ],
});
