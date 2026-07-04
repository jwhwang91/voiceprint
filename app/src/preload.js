// 유일한 renderer <-> main 통로. renderer 에는 node 권한을 주지 않는다.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('api', {
  pty: {
    input: (data) => ipcRenderer.send('pty:input', data),
    resize: (cols, rows) => ipcRenderer.send('pty:resize', { cols, rows }),
    onData: (cb) => ipcRenderer.on('pty:data', (_e, d) => cb(d)),
    onExit: (cb) => ipcRenderer.on('pty:exit', () => cb()),
  },
  session: {
    restart: () => ipcRenderer.invoke('session:restart'),
    claude: () => ipcRenderer.invoke('session:claude'),
  },
  python: {
    run: (args, env) => ipcRenderer.invoke('python:run', { args, env }),
  },
  naver: {
    show: (v) => ipcRenderer.invoke('naver:show', v),
    login: () => ipcRenderer.invoke('naver:login'),
    home: () => ipcRenderer.invoke('naver:home'),
    onVisibility: (cb) => ipcRenderer.on('naver:visibility', (_e, v) => cb(v)),
  },
  files: {
    pathForFile: (file) => webUtils.getPathForFile(file),
    ingest: (job, paths) => ipcRenderer.invoke('files:ingest', { job, paths }),
    list: (job) => ipcRenderer.invoke('files:list', job),
  },
  memo: {
    get: (job) => ipcRenderer.invoke('memo:get', job),
    save: (job, text) => ipcRenderer.invoke('memo:save', { job, text }),
  },
  onboarding: {
    status: () => ipcRenderer.invoke('onboarding:status'),
  },
  settings: {
    keys: () => ipcRenderer.invoke('settings:keys'),
    save: (values) => ipcRenderer.invoke('settings:save', values),
  },
  workspace: {
    get: () => ipcRenderer.invoke('workspace:get'),
    choose: () => ipcRenderer.invoke('workspace:choose'),
    open: () => ipcRenderer.invoke('workspace:open'),
  },
  logs: {
    open: () => ipcRenderer.invoke('logs:open'),
  },
  env: {
    check: () => ipcRenderer.invoke('env:check'),
  },
  newJob: (job) => ipcRenderer.invoke('job:new', job),
  listJobs: () => ipcRenderer.invoke('jobs:list'),
});
