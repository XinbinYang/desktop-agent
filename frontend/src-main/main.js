const { app, BrowserWindow, ipcMain, dialog, Menu } = require('electron');
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

  // macOS: 第一个菜单项应该是应用名
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

app.whenReady().then(async () => {
  try {
    await startBackend();
    createWindow();
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
