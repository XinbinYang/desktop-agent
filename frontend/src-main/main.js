const { app, BrowserWindow, ipcMain, dialog, Menu, Tray, nativeImage, nativeTheme, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
const { spawn, exec } = require('child_process');

// Pin the userData directory so dev (electron .) and prod (packaged) share state
// AND match what start-all.ps1 passes to the backend via DESKTOP_AGENT_USER_DATA_DIR.
// Without this, dev mode picks %APPDATA%/desktop-agent-gui (from package.json "name")
// while the backend reads %APPDATA%/Desktop Agent — local auth tokens won't match.
//
// We resolve the platform appData path from env vars so this runs before
// Electron's app singleton is fully initialized (calling app.getPath() this
// early throws on some Electron versions).
function resolveAppDataDir() {
  if (process.platform === 'win32') return process.env.APPDATA || path.join(process.env.USERPROFILE || '', 'AppData', 'Roaming');
  if (process.platform === 'darwin') return path.join(process.env.HOME || '', 'Library', 'Application Support');
  return process.env.XDG_CONFIG_HOME || path.join(process.env.HOME || '', '.config');
}
const STABLE_USER_DATA_DIR = path.join(resolveAppDataDir(), 'Desktop Agent');
app.setPath('userData', STABLE_USER_DATA_DIR);

function getStorePath() {
  return path.join(app.getPath('userData'), 'window-state.json');
}
let mainWindow;
let tray = null;
let backendProcess = null;

const isDev = process.argv.includes('--dev');
const isPackaged = app.isPackaged;
const shouldOpenDevTools = process.env.DESKTOP_AGENT_OPEN_DEVTOOLS === '1';
let authToken = null;
let lastRendererCrashReloadAt = 0;

const WINDOW_THEMES = {
  dark: {
    background: '#0d1117',
    titleBar: '#161b22',
    symbol: '#e6edf3',
  },
  light: {
    background: '#ffffff',
    titleBar: '#f3f3f3',
    symbol: '#1e1e1e',
  },
};

function normalizeTheme(theme) {
  return theme === 'light' ? 'light' : 'dark';
}

function getTitleBarOverlay(theme) {
  const colors = WINDOW_THEMES[normalizeTheme(theme)];
  return {
    color: colors.titleBar,
    symbolColor: colors.symbol,
    height: 40,
  };
}

function applyWindowTheme(theme) {
  const resolvedTheme = normalizeTheme(theme);
  const colors = WINDOW_THEMES[resolvedTheme];

  nativeTheme.themeSource = resolvedTheme;

  if (!mainWindow) return;
  mainWindow.setBackgroundColor(colors.background);
  if (process.platform !== 'darwin' && typeof mainWindow.setTitleBarOverlay === 'function') {
    mainWindow.setTitleBarOverlay(getTitleBarOverlay(resolvedTheme));
  }
}

function getAuthStorePath() {
  return path.join(app.getPath('userData'), 'local-auth.json');
}

function getAuthToken() {
  if (process.env.DESKTOP_AGENT_AUTH_TOKEN) {
    return process.env.DESKTOP_AGENT_AUTH_TOKEN;
  }
  if (authToken !== null) {
    return authToken;
  }

  const storePath = getAuthStorePath();
  try {
    const data = JSON.parse(fs.readFileSync(storePath, 'utf-8'));
    if (typeof data.token === 'string' && data.token.length >= 32) {
      authToken = data.token;
      return authToken;
    }
  } catch {
    // Generate a new token below.
  }

  authToken = crypto.randomBytes(32).toString('hex');
  try {
    fs.mkdirSync(path.dirname(storePath), { recursive: true });
    fs.writeFileSync(storePath, JSON.stringify({ token: authToken }, null, 2));
  } catch (error) {
    console.error('[Auth] Failed to persist local auth token:', error);
  }
  return authToken;
}

// ========== 单实例锁 ==========
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  console.log('[Electron] Another instance is already running. Quitting.');
  app.quit();
  process.exit(0);
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

// ========== 后端进程管理 ==========
function waitForBackendHealth(timeoutMs = isPackaged ? 90000 : 15000) {
  const started = Date.now();
  const token = getAuthToken();

  return new Promise((resolve, reject) => {
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error('Backend health check timed out at http://127.0.0.1:8765/api/health'));
        return;
      }
      setTimeout(check, 500);
    };

    const check = () => {
      const options = token ? { headers: { 'X-Desktop-Agent-Token': token } } : undefined;
      const req = http.get('http://127.0.0.1:8765/api/health', options, (res) => {
        if (res.statusCode === 200) {
          res.resume();
          resolve(true);
          return;
        }
        res.resume();
        retry();
      });

      req.on('error', retry);
      req.setTimeout(2000, () => {
        req.destroy();
        retry();
      });
    };

    check();
  });
}

function startBackend() {
  if (isDev) {
    return Promise.resolve();
  }

  const backendExe = isPackaged
    ? path.join(process.resourcesPath, 'backend', 'desktop-agent-backend.exe')
    : path.join(__dirname, '..', '..', 'backend', 'venv', 'Scripts', 'python.exe');

  const backendArgs = isPackaged
    ? []
    : [path.join(__dirname, '..', '..', 'backend', 'start.py')];

  const backendCwd = isPackaged
    ? path.dirname(backendExe)
    : path.join(__dirname, '..', '..', 'backend');
  const token = getAuthToken();
  const backendEnv = {
    ...process.env,
    DESKTOP_AGENT_USER_DATA_DIR: app.getPath('userData'),
  };
  if (token) {
    backendEnv.DESKTOP_AGENT_AUTH_TOKEN = token;
  }

  console.log('[Electron] Starting backend:', backendExe, backendArgs);

  return new Promise((resolve, reject) => {
    if (!fs.existsSync(backendExe)) {
      reject(new Error(`Backend executable not found: ${backendExe}. Run "npm run build:backend" before packaging.`));
      return;
    }

    backendProcess = spawn(backendExe, backendArgs, {
      cwd: backendCwd,
      windowsHide: true,
      detached: false,
      env: backendEnv,
    });

    backendProcess.stdout.on('data', (data) => {
      const str = data.toString();
      console.log('[Backend]', str);
      if (str.includes('Uvicorn running')) {
        waitForBackendHealth().then(resolve).catch(reject);
      }
    });

    backendProcess.stderr.on('data', (data) => {
      console.error('[Backend Error]', data.toString());
    });

    backendProcess.on('error', (err) => {
      console.error('[Backend Failed]', err);
      reject(err);
    });

    setTimeout(() => {
      waitForBackendHealth().then(resolve).catch(reject);
    }, 1000);
  });
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) return;

  if (process.platform === 'win32') {
    // Windows: taskkill 更可靠
    exec(`taskkill /PID ${backendProcess.pid} /T /F`, (err) => {
      if (err) {
        console.error('[Electron] taskkill failed:', err);
        backendProcess.kill('SIGKILL');
      }
    });
  } else {
    backendProcess.kill('SIGTERM');
    setTimeout(() => {
      if (!backendProcess.killed) backendProcess.kill('SIGKILL');
    }, 2000);
  }
}

// ========== 窗口状态持久化（原生 fs，避免 ESM 兼容问题）==========
function getWindowState() {
  const defaultState = { width: 1400, height: 900, x: undefined, y: undefined, maximized: false };
  try {
    const data = fs.readFileSync(getStorePath(), 'utf-8');
    return { ...defaultState, ...JSON.parse(data) };
  } catch {
    return defaultState;
  }
}

function saveWindowState() {
  if (!mainWindow) return;
  const bounds = mainWindow.getNormalBounds();
  try {
    fs.writeFileSync(getStorePath(), JSON.stringify({
      width: bounds.width,
      height: bounds.height,
      x: bounds.x,
      y: bounds.y,
      maximized: mainWindow.isMaximized(),
    }, null, 2));
  } catch (e) {
    console.error('[WindowState] save failed:', e);
  }
}

// ========== 托盘 ==========
function createTray() {
  // 使用一个极简的 16x16 内联图标（1px 透明占位，可被替换）
  const iconData = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAABpJREFUeNpi/P//PwMlgImBQjBqwKgBwAADAA7XA/5l9V8AAAAASUVORK5CYII=',
    'base64'
  );
  const icon = nativeImage.createFromBuffer(iconData);
  tray = new Tray(icon);
  tray.setToolTip('Desktop Agent');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: '隐藏主窗口',
      click: () => {
        if (mainWindow) mainWindow.hide();
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// ========== 窗口创建 ==========
function createWindow() {
  const state = getWindowState();

  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    ...(process.platform === 'darwin' ? {} : { titleBarOverlay: getTitleBarOverlay('dark') }),
    backgroundColor: WINDOW_THEMES.dark.background,
    autoHideMenuBar: true,
    show: false, // 先隐藏，等加载完成再显示，避免闪烁
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
  });
  applyWindowTheme('dark');

  if (state.maximized) {
    mainWindow.maximize();
  }

  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[Electron] Renderer process gone:', details);
    const now = Date.now();
    if (now - lastRendererCrashReloadAt > 10000 && mainWindow && !mainWindow.isDestroyed()) {
      lastRendererCrashReloadAt = now;
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          console.error('[Electron] Reloading renderer after crash');
          mainWindow.reload();
        }
      }, 500);
    }
  });

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error('[Electron] Renderer failed to load:', { errorCode, errorDescription, validatedURL });
  });

  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.error(`[Renderer:${level}] ${message} (${sourceId}:${line})`);
    }
  });

  mainWindow.on('unresponsive', () => {
    console.error('[Electron] Window became unresponsive');
  });

  mainWindow.on('responsive', () => {
    console.error('[Electron] Window became responsive again');
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    if (shouldOpenDevTools) {
      mainWindow.webContents.openDevTools();
    }
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (state.maximized) mainWindow.maximize();
  });

  // 保存窗口状态
  mainWindow.on('resize', saveWindowState);
  mainWindow.on('move', saveWindowState);
  mainWindow.on('maximize', saveWindowState);
  mainWindow.on('unmaximize', saveWindowState);

  // 点击关闭时最小化到托盘（Windows/Linux）
  mainWindow.on('close', (event) => {
    if (process.platform !== 'darwin' && !app.isQuiting) {
      event.preventDefault();
      mainWindow.hide();
    } else {
      saveWindowState();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function buildMenu() {
  const template = [
    {
      label: '文件',
      submenu: [
        { label: '新建会话', accelerator: 'CmdOrCtrl+N', click: () => mainWindow?.webContents.send('menu-new-session') },
        { type: 'separator' },
        { role: 'quit', label: '退出' },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectall', label: '全选' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload', label: '刷新' },
        { role: 'forcereload', label: '强制刷新' },
        { role: 'toggledevtools', label: '开发者工具' },
        { type: 'separator' },
        { role: 'resetzoom', label: '实际大小' },
        { role: 'zoomin', label: '放大' },
        { role: 'zoomout', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'close', label: '关闭' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        { label: '关于 Desktop Agent', click: () => dialog.showMessageBox(mainWindow, { type: 'info', title: '关于', message: `Desktop Agent v${app.getVersion()}` }) },
      ],
    },
  ];

  if (process.platform === 'darwin') {
    template.unshift({
      label: app.getName(),
      submenu: [
        { role: 'about', label: '关于' },
        { type: 'separator' },
        { role: 'hide', label: '隐藏' },
        { role: 'hideothers', label: '隐藏其他' },
        { role: 'unhide', label: '显示全部' },
        { type: 'separator' },
        { role: 'quit', label: '退出' },
      ],
    });
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ========== App 生命周期 ==========
app.whenReady().then(async () => {
  try {
    await startBackend();
    createWindow();
    createTray();
    buildMenu();
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
  app.isQuiting = true;
  stopBackend();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else if (mainWindow) {
    mainWindow.show();
  }
});

// ========== IPC ==========
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

function resolveUserPath(value) {
  if (typeof value !== 'string' || value.trim().length === 0) return null;
  return path.resolve(value);
}

function openExplorerFallback(resolved, isDirectory) {
  if (process.platform !== 'win32') return null;
  const args = isDirectory ? [resolved] : ['/select,', resolved];
  const child = spawn('explorer.exe', args, {
    detached: true,
    stdio: 'ignore',
  });
  child.unref();
  return null;
}

ipcMain.handle('reveal-path', async (_event, targetPath) => {
  const resolved = resolveUserPath(targetPath);
  if (!resolved) return 'Invalid path';
  try {
    if (!fs.existsSync(resolved)) return 'Path does not exist';
    const stat = fs.statSync(resolved);
    if (stat.isDirectory()) {
      const error = await shell.openPath(resolved);
      if (!error) return null;
      return openExplorerFallback(resolved, true) || error;
    }
    if (process.platform === 'win32') {
      return openExplorerFallback(resolved, false);
    }
    shell.showItemInFolder(resolved);
    return null;
  } catch (err) {
    return String(err);
  }
});

ipcMain.handle('open-path', async (_event, targetPath) => {
  const resolved = resolveUserPath(targetPath);
  if (!resolved) return 'Invalid path';
  try {
    const error = await shell.openPath(resolved);
    return error || null;
  } catch (err) {
    return String(err);
  }
});

ipcMain.handle('open-terminal', (_event, targetPath) => {
  const resolved = resolveUserPath(targetPath);
  if (!resolved) return 'Invalid path';
  try {
    if (!fs.existsSync(resolved)) return 'Path does not exist';
    const stat = fs.statSync(resolved);
    const cwd = stat.isDirectory() ? resolved : path.dirname(resolved);
    const command = process.platform === 'win32'
      ? 'powershell.exe'
      : (process.env.SHELL || '/bin/sh');
    const args = process.platform === 'win32' ? ['-NoExit'] : [];
    const child = spawn(command, args, {
      cwd,
      detached: true,
      stdio: 'ignore',
    });
    child.unref();
    return null;
  } catch (err) {
    return String(err);
  }
});

ipcMain.handle('get-app-version', () => app.getVersion());

ipcMain.handle('get-auth-token', () => getAuthToken());

ipcMain.handle('set-theme', (_event, theme) => {
  const resolvedTheme = normalizeTheme(theme);
  applyWindowTheme(resolvedTheme);
  return resolvedTheme;
});

ipcMain.handle('capture-region', async (_event, rect) => {
  try {
    const img = await mainWindow.webContents.capturePage(rect);
    return img.toDataURL();
  } catch (err) {
    console.error('[capture-region] failed:', err);
    return null;
  }
});
