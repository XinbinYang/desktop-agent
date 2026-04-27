const { app, BrowserWindow, ipcMain, dialog, Menu, Tray, globalShortcut, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const Store = require('electron-store');

const store = new Store();
let mainWindow;
let tray = null;
let backendProcess = null;

const isDev = process.argv.includes('--dev');
const isPackaged = app.isPackaged;

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

  console.log('[Electron] Starting backend:', backendExe, backendArgs);

  return new Promise((resolve, reject) => {
    backendProcess = spawn(backendExe, backendArgs, {
      cwd: backendCwd,
      windowsHide: true,
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
  const { x, y, width, height } = store.get('windowBounds', { width: 1400, height: 900 });

  mainWindow = new BrowserWindow({
    width,
    height,
    x: x !== undefined ? x : undefined,
    y: y !== undefined ? y : undefined,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    show: false,
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

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (store.get('windowMaximized')) {
      mainWindow.maximize();
    }
  });

  // 保存窗口状态
  const saveBounds = () => {
    if (mainWindow.isMaximized()) {
      store.set('windowMaximized', true);
    } else {
      store.set('windowMaximized', false);
      store.set('windowBounds', mainWindow.getBounds());
    }
  };

  mainWindow.on('resize', saveBounds);
  mainWindow.on('move', saveBounds);
  mainWindow.on('maximize', saveBounds);
  mainWindow.on('unmaximize', saveBounds);

  mainWindow.on('close', (event) => {
    if (process.platform === 'darwin') return;
    event.preventDefault();
    mainWindow.hide();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  if (tray) return;
  const fs = require('fs');
  const trayIcon = path.join(__dirname, '../public/favicon.ico');
  if (!fs.existsSync(trayIcon)) {
    console.log('[Tray] No icon found, skipping tray creation');
    return;
  }
  tray = new Tray(trayIcon);
  tray.setToolTip('Desktop Agent');
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        } else {
          createWindow();
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        stopBackend();
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    } else {
      createWindow();
    }
  });
}

function createMenu() {
  const template = [
    {
      label: '文件',
      submenu: [
        {
          label: '新建会话',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            mainWindow?.webContents.send('menu-new-session');
          },
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: process.platform === 'darwin' ? 'Cmd+Q' : 'Alt+F4',
          click: () => {
            stopBackend();
            app.quit();
          },
        },
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
        {
          label: '刷新',
          accelerator: 'CmdOrCtrl+R',
          click: () => mainWindow?.webContents.reload(),
        },
        {
          label: '切换开发者工具',
          accelerator: 'F12',
          click: () => mainWindow?.webContents.toggleDevTools(),
        },
        { type: 'separator' },
        {
          label: '全屏',
          accelerator: 'F11',
          click: () => {
            const isFullScreen = mainWindow?.isFullScreen();
            mainWindow?.setFullScreen(!isFullScreen);
          },
        },
        { type: 'separator' },
        { role: 'resetzoom', label: '重置缩放' },
        { role: 'zoomin', label: '放大' },
        { role: 'zoomout', label: '缩小' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'close', label: '关闭' },
        { type: 'separator' },
        { role: 'front', label: '前置全部窗口' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 Desktop Agent',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: '关于',
              message: 'Desktop Agent',
              detail: `版本: ${app.getVersion()}\n基于 Electron + React + FastAPI 构建`,
            });
          },
        },
        {
          label: 'GitHub 仓库',
          click: () => shell.openExternal('https://github.com/XinbinYang/desktop-agent'),
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

app.whenReady().then(async () => {
  try {
    await startBackend();
    createWindow();
    createMenu();
    createTray();

    // 全局快捷键
    globalShortcut.register('F5', () => {
      mainWindow?.webContents.reload();
    });
  } catch (e) {
    dialog.showErrorBox('启动失败', '后端服务启动失败: ' + e.message);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    // Windows/Linux: 保持托盘运行
  }
});

app.on('before-quit', () => {
  stopBackend();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  } else {
    mainWindow?.show();
  }
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
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
