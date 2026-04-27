const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: () => ipcRenderer.invoke('select-file'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  onNewSession: (cb) => ipcRenderer.on('menu-new-session', cb),
  removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel),
});
