"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
electron_1.contextBridge.exposeInMainWorld('electronAPI', {
    // Python 引擎状态
    pythonStart: () => electron_1.ipcRenderer.invoke('python:start'),
    pythonStatus: () => electron_1.ipcRenderer.invoke('python:status'),
    onPythonStatusChanged: (callback) => {
        electron_1.ipcRenderer.on('python:status-changed', (_event, status) => callback(status));
    },
    // 商家管理
    merchantList: () => electron_1.ipcRenderer.invoke('merchant:list'),
    merchantCreate: (data) => electron_1.ipcRenderer.invoke('merchant:create', data),
    merchantUpdate: (data) => electron_1.ipcRenderer.invoke('merchant:update', data),
    merchantDelete: (id) => electron_1.ipcRenderer.invoke('merchant:delete', id),
    merchantTestLogin: (id) => electron_1.ipcRenderer.invoke('merchant:test-login', id),
    // 任务管理
    taskStart: (merchantId) => electron_1.ipcRenderer.invoke('task:start', merchantId),
    taskStop: (merchantId) => electron_1.ipcRenderer.invoke('task:stop', merchantId),
    taskStartAll: () => electron_1.ipcRenderer.invoke('task:start-all'),
    taskStopAll: () => electron_1.ipcRenderer.invoke('task:stop-all'),
    // 任务配置
    taskConfigList: () => electron_1.ipcRenderer.invoke('taskConfig:list'),
    taskConfigListByMerchant: (merchantId) => electron_1.ipcRenderer.invoke('taskConfig:listByMerchant', merchantId),
    taskConfigCreate: (data) => electron_1.ipcRenderer.invoke('taskConfig:create', data),
    taskConfigUpdate: (data) => electron_1.ipcRenderer.invoke('taskConfig:update', data),
    taskConfigDelete: (id) => electron_1.ipcRenderer.invoke('taskConfig:delete', id),
    taskConfigExecute: (taskId) => electron_1.ipcRenderer.invoke('taskConfig:execute', taskId),
    taskConfigParseCurl: (curl) => electron_1.ipcRenderer.invoke('taskConfig:parseCurl', curl),
    // 数据管理
    dataList: (params) => electron_1.ipcRenderer.invoke('data:list', params),
    dataExport: (merchantId, ids) => electron_1.ipcRenderer.invoke('data:export', { merchantId, ids }),
    dataDelete: (id) => electron_1.ipcRenderer.invoke('data:delete', id),
    showSaveDialog: (options) => electron_1.ipcRenderer.invoke('dialog:save', options),
    copyFile: (srcPath, destPath) => electron_1.ipcRenderer.invoke('file:copy', srcPath, destPath),
    // 仪表盘
    dashboardSummary: () => electron_1.ipcRenderer.invoke('dashboard:summary'),
    // 事件监听
    onPythonEvent: (callback) => {
        electron_1.ipcRenderer.on('python-event', (_event, data) => callback(data.event, data.data));
    },
    // 窗口控制
    minimizeWindow: () => electron_1.ipcRenderer.invoke('window:minimize'),
    maximizeWindow: () => electron_1.ipcRenderer.invoke('window:maximize'),
    closeWindow: () => electron_1.ipcRenderer.invoke('window:close'),
});
//# sourceMappingURL=preload.js.map