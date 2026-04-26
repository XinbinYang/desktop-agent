const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let backendProcess = null;

const isDev = process.argv.includes('--dev');
const isPackaged = app.isPackaged;

function startBackend() {
  if (isDev) {
    // 开发模式：假设后端已手动启动
    return Promise.resolve();
  }

  // 生产模式：启动打包好的后端exe
  const backendExe = isPackaged
    ? path.join(process.resourcesPath, 'backend', 'desktop-agent-backend.exe')
    : path.join(__dirname, '..', '..', 'backend', 'venv', 'Scripts', 'python.exe');

  const backendArgs = isPackaged
    ? []
    : [path.join(__dirname, '..', '..', 'backend', 'start.py')];

  const backendCwd = isPackaged
    ? path.dirname(backendExe)
    : path.join(__dirname, '..', '..', 'backend');

  console.log('[Electron] Starting backend:', backendExe, backendArgs);

  return new Promise((resolve, reject) => {
    backendProcess = spawn(backendExe, backendArgs, {
      cwd: backendCwd,
      windowsHide: true, // 隐藏黑窗口
      detached: false,
    });

    backendProcess.stdout.on('data', (data) => {
      const str = data.toString();
      console.log('[Backend]', str);
      if (str.includes('Uvicorn running')) {
        resolve(true);
      }
    });

    backendProcess.stderr.on('data', (data) => {
      console.error('[Backend Error]', data.toString());
    });

    backendProcess.on('error', (err) => {
      console.error('[Backend Failed]', err);
      reject(err);
    });

    // 5秒超时兜底
    setTimeout(() => resolve(true), 5000);
  });
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill('SIGTERM');
    setTimeout(() => {
      if (!backendProcess.killed) backendProcess.kill('SIGKILL');
    }, 2000);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  try {
    await startBackend();
    createWindow();
  } catch (e) {
    dialog.showErrorBox('启动失败', '后端服务启动失败: ' + e.message);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// IPC
ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory'] });
  return result.filePaths[0] || null;
});

ipcMain.handle('select-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg'] }, { name: 'All', extensions: ['*'] }],
  });
  return result.filePaths[0] || null;
});

ipcMain.handle('get-app-version', () => app.getVersion());