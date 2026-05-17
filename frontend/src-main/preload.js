const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: () => ipcRenderer.invoke('select-file'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getAuthToken: () => ipcRenderer.invoke('get-auth-token'),
  setTheme: (theme) => ipcRenderer.invoke('set-theme', theme),
  captureRegion: (rect) => ipcRenderer.invoke('capture-region', rect),
  onNewSession: (cb) => {
    ipcRenderer.on('menu-new-session', cb);
    // 返回 unsubscribe 函数
    return () => {
      ipcRenderer.off('menu-new-session', cb);
    };
  },
});
