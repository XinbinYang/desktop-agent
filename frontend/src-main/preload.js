const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: () => ipcRenderer.invoke('select-file'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
});