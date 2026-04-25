"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const path_1 = require("path");
const fs_1 = require("fs");
const promises_1 = require("fs/promises");
const child_process_1 = require("child_process");
const python_manager_1 = require("./python-manager");
let mainWindow = null;
let pythonManager = null;
// ====== 日志系统：输出到用户数据目录的 app.log ======
function initLogger() {
    const logDir = electron_1.app.getPath('userData');
    const logFile = (0, path_1.join)(logDir, 'app.log');
    // 追加模式，保留历史日志
    const stream = (0, fs_1.createWriteStream)(logFile, { flags: 'a', encoding: 'utf-8' });
    const timestamp = () => new Date().toLocaleString('zh-CN');
    // 拦截 console，同时写入文件
    const origConsole = { ...console };
    const writeLog = (prefix, ...args) => {
        const msg = args.map(a => {
            if (typeof a === 'object')
                try {
                    return JSON.stringify(a);
                }
                catch {
                    return String(a);
                }
            return String(a);
        }).join(' ');
        const line = `[${timestamp()}] [${prefix}] ${msg}\n`;
        stream.write(line);
        origConsole.log(`[${prefix}]`, ...args);
    };
    console.log = (...args) => writeLog('INFO', ...args);
    console.error = (...args) => writeLog('ERROR', ...args);
    console.warn = (...args) => writeLog('WARN', ...args);
    // 启动时写入分隔线（区分每次启动）
    stream.write('\n' + '='.repeat(60) + '\n');
    stream.write(`[App started at ${timestamp()}] isPackaged=${electron_1.app.isPackaged}\n`);
    stream.write(`Log file: ${logFile}\n`);
    stream.write('='.repeat(60) + '\n\n');
    // 捕获未处理异常
    process.on('uncaughtException', (err) => {
        writeLog('FATAL', `UncaughtException: ${err.message}\n${err.stack}`);
    });
    process.on('unhandledRejection', (reason) => {
        writeLog('FATAL', `UnhandledRejection: ${reason}`);
    });
}
// 初始化日志（在 app ready 之前就可用）
initLogger();
/**
 * 查找可用的 Python 可执行文件
 * 优先级：内嵌 Python（打包后） > 系统 Python
 */
function findPython() {
    // 1. 打包后：优先使用内嵌 Python 运行时
    if (electron_1.app.isPackaged) {
        const embeddedPython = (0, path_1.join)(process.resourcesPath, 'python-runtime', 'python.exe');
        if ((0, fs_1.existsSync)(embeddedPython)) {
            try {
                const version = (0, child_process_1.execFileSync)(embeddedPython, ['--version'], {
                    encoding: 'utf-8',
                    timeout: 5000,
                    windowsHide: true
                }).trim();
                console.log(`[findPython] Using embedded Python: ${embeddedPython} (${version})`);
                return embeddedPython;
            }
            catch (e) {
                console.error('[findPython] Embedded Python exists but failed to run:', e);
            }
        }
        else {
            console.log('[findPython] No embedded Python found at:', embeddedPython);
        }
    }
    // 2. 回退到系统 Python
    const candidates = process.platform === 'win32'
        ? ['python', 'python3', 'py']
        : ['python3', 'python'];
    for (const cmd of candidates) {
        try {
            const checkCmd = process.platform === 'win32' ? 'where' : 'which';
            const result = (0, child_process_1.execFileSync)(checkCmd, [cmd.split(' ')[0]], {
                encoding: 'utf-8',
                timeout: 3000,
                windowsHide: true
            }).trim();
            if (result) {
                const actualPath = result.split('\n')[0].trim();
                try {
                    const version = (0, child_process_1.execFileSync)(actualPath, ['--version'], {
                        encoding: 'utf-8',
                        timeout: 5000,
                        windowsHide: true
                    }).trim();
                    console.log(`[findPython] Using system Python: ${actualPath} (${version})`);
                    return actualPath;
                }
                catch { /* skip */ }
            }
        }
        catch { /* not found */ }
    }
    console.error(`[findPython] WARNING: No Python available!`);
    return candidates[0];
}
function createWindow() {
    const { width: workWidth, height: workHeight } = electron_1.screen.getPrimaryDisplay().workAreaSize;
    const windowWidth = Math.min(Math.max(Math.round(workWidth * 0.9), 1180), 1560);
    const windowHeight = Math.min(Math.max(Math.round(workHeight * 0.88), 760), 980);
    mainWindow = new electron_1.BrowserWindow({
        width: windowWidth,
        height: windowHeight,
        minWidth: 1024,
        minHeight: 680,
        center: true,
        title: 'Finance Tools - 数据采集工具',
        frame: false,
        titleBarStyle: 'hiddenInset',
        backgroundColor: '#020617',
        webPreferences: {
            preload: (0, path_1.join)(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: false
        },
        show: false
    });
    // 开发环境加载 Vite dev server
    if (!electron_1.app.isPackaged) {
        mainWindow.loadURL('http://localhost:5173');
    }
    else {
        // 打包后：前端在 src/dist/ 目录，用 getAppPath 获取项目根目录
        const indexPath = (0, path_1.join)(electron_1.app.getAppPath(), 'src', 'dist', 'index.html');
        console.log('[Main] Loading production page:', indexPath);
        console.log('[Main] app.getAppPath():', electron_1.app.getAppPath());
        mainWindow.loadFile(indexPath);
        // 页面加载错误诊断
        mainWindow.webContents.on('did-fail-load', (_event, _errorCode, _errorDesc, validatedURL) => {
            console.error('[Main] Page load FAILED:', validatedURL);
        });
        mainWindow.webContents.on('did-finish-load', () => {
            console.log('[Main] Page loaded OK, URL:', mainWindow?.webContents.getURL());
        });
    }
    mainWindow.once('ready-to-show', () => {
        mainWindow?.show();
        // 始终打开 DevTools（方便调试打包后的问题）
        mainWindow?.webContents.openDevTools({ mode: 'detach' });
    });
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}
function sendToRenderer(channel, data) {
    if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(channel, data);
    }
}
// 初始化 IPC 通道
function registerIpcHandlers() {
    // Python 引擎状态
    electron_1.ipcMain.handle('python:start', async () => {
        if (!pythonManager)
            return { success: false, message: 'Python manager not initialized' };
        if (pythonManager.status === 'running')
            return { success: true, status: 'running' };
        const started = pythonManager.start();
        const status = pythonManager.status;
        sendToRenderer('python:status-changed', status);
        return { success: started, status };
    });
    electron_1.ipcMain.handle('python:status', async () => {
        return pythonManager?.status || 'stopped';
    });
    // 商家相关 IPC
    electron_1.ipcMain.handle('merchant:list', async () => {
        return pythonManager?.sendRequest('merchant.list', {}) || [];
    });
    electron_1.ipcMain.handle('merchant:create', async (_event, data) => {
        return pythonManager?.sendRequest('merchant.create', data);
    });
    electron_1.ipcMain.handle('merchant:update', async (_event, data) => {
        return pythonManager?.sendRequest('merchant.update', data);
    });
    electron_1.ipcMain.handle('merchant:delete', async (_event, id) => {
        return pythonManager?.sendRequest('merchant.delete', { id });
    });
    electron_1.ipcMain.handle('merchant:test-login', async (_event, id) => {
        return pythonManager?.sendRequest('merchant.testLogin', { id });
    });
    // 任务相关 IPC
    electron_1.ipcMain.handle('task:start', async (_event, merchantId) => {
        return pythonManager?.sendRequest('task.start', { merchantId: merchantId || null });
    });
    electron_1.ipcMain.handle('task:stop', async (_event, merchantId) => {
        return pythonManager?.sendRequest('task.stop', { merchantId: merchantId || null });
    });
    electron_1.ipcMain.handle('task:start-all', async () => {
        return pythonManager?.sendRequest('task.startAll', {});
    });
    electron_1.ipcMain.handle('task:stop-all', async () => {
        return pythonManager?.sendRequest('task.stopAll', {});
    });
    // 任务配置 IPC
    electron_1.ipcMain.handle('taskConfig:list', async () => {
        return pythonManager?.sendRequest('taskConfig.list', {}) || [];
    });
    electron_1.ipcMain.handle('taskConfig:listByMerchant', async (_event, merchantId) => {
        return pythonManager?.sendRequest('taskConfig.listByMerchant', { merchantId }) || [];
    });
    electron_1.ipcMain.handle('taskConfig:create', async (_event, data) => {
        return pythonManager?.sendRequest('taskConfig.create', data);
    });
    electron_1.ipcMain.handle('taskConfig:update', async (_event, data) => {
        return pythonManager?.sendRequest('taskConfig.update', data);
    });
    electron_1.ipcMain.handle('taskConfig:delete', async (_event, id) => {
        return pythonManager?.sendRequest('taskConfig.delete', { id });
    });
    electron_1.ipcMain.handle('taskConfig:execute', async (_event, taskId) => {
        return pythonManager?.sendRequest('taskConfig.execute', { taskId });
    });
    electron_1.ipcMain.handle('taskConfig:parseCurl', async (_event, curl) => {
        return pythonManager?.sendRequest('taskConfig.parseCurl', { curl });
    });
    // 数据相关 IPC
    electron_1.ipcMain.handle('data:list', async (_event, params) => {
        return pythonManager?.sendRequest('data.list', params || {});
    });
    electron_1.ipcMain.handle('data:export', async (_event, params) => {
        return pythonManager?.sendRequest('data.export', params || {});
    });
    electron_1.ipcMain.handle('data:delete', async (_event, id) => {
        return pythonManager?.sendRequest('data.delete', { id });
    });
    // 仪表盘 IPC
    electron_1.ipcMain.handle('dashboard:summary', async () => {
        return pythonManager?.sendRequest('dashboard.summary', {}) || {};
    });
    // 窗口控制
    electron_1.ipcMain.handle('window:minimize', async () => {
        mainWindow?.minimize();
    });
    // 文件对话框
    electron_1.ipcMain.handle('dialog:save', async (_event, options) => {
        const result = await electron_1.dialog.showSaveDialog(mainWindow, {
            title: options?.title || '保存文件',
            defaultPath: options?.defaultPath || '',
            filters: options?.filters || [{ name: 'Excel', extensions: ['xlsx'] }],
        });
        return result;
    });
    // 文件复制（导出时将临时文件复制到用户选择的位置）
    electron_1.ipcMain.handle('file:copy', async (_event, srcPath, destPath) => {
        await (0, promises_1.cp)(srcPath, destPath);
        return destPath;
    });
    electron_1.ipcMain.handle('window:maximize', async () => {
        if (mainWindow?.isMaximized()) {
            mainWindow.unmaximize();
        }
        else {
            mainWindow?.maximize();
        }
    });
    electron_1.ipcMain.handle('window:close', async () => {
        mainWindow?.close();
    });
}
electron_1.app.whenReady().then(() => {
    createWindow();
    // 查找可用的 Python 可执行文件
    const pythonExe = findPython();
    console.log('[Main] Using python executable:', pythonExe);
    // 打包后：python/ 在 app.asar.unpacked/resources/python/
    let pythonScript;
    if (electron_1.app.isPackaged) {
        pythonScript = (0, path_1.join)(process.resourcesPath, 'python', 'main.py');
        console.log('[Main] Packaged mode, resourcesPath:', process.resourcesPath);
        console.log('[Main] Python script path:', pythonScript);
    }
    else {
        pythonScript = (0, path_1.join)(__dirname, '..', 'python', 'main.py');
        console.log('[Main] Dev mode, Python script path:', pythonScript);
    }
    // 检查 Python 脚本是否存在
    if (!(0, fs_1.existsSync)(pythonScript)) {
        console.error(`[Main] FATAL: Python script not found: ${pythonScript}`);
    }
    else {
        console.log('[Main] Python script exists OK');
    }
    // 设置环境变量（内嵌 Python 需要 PYTHONPATH 找到项目模块）
    const pythonDir = electron_1.app.isPackaged
        ? (0, path_1.join)(process.resourcesPath, 'python')
        : (0, path_1.join)(__dirname, '..', 'python');
    process.env.PYTHONPATH = pythonDir;
    // 强制 UTF-8 编码，解决 Windows 打包后 GBK 编码导致 emoji/中文报错
    process.env.PYTHONIOENCODING = 'utf-8';
    // 打包后：数据库存放在用户数据目录，重装应用不丢失数据
    if (electron_1.app.isPackaged) {
        const userDataDbDir = (0, path_1.join)(electron_1.app.getPath('userData'), 'db');
        process.env.FINANCE_TOOLS_DB = (0, path_1.join)(userDataDbDir, 'finance_tools.db');
        console.log('[Main] Database path (userData):', process.env.FINANCE_TOOLS_DB);
    }
    else {
        console.log('[Main] Dev mode: database in shared/db/');
    }
    // 打包后：指定 Playwright 浏览器路径（随 extraResources 一起打包）
    if (electron_1.app.isPackaged) {
        const pwBrowserPath = (0, path_1.join)(process.resourcesPath, 'ms-playwright');
        if ((0, fs_1.existsSync)(pwBrowserPath)) {
            process.env.PLAYWRIGHT_BROWSERS_PATH = pwBrowserPath;
            console.log('[Main] PLAYWRIGHT_BROWSERS_PATH:', pwBrowserPath);
        }
    }
    console.log('[Main] PYTHONPATH:', process.env.PYTHONPATH);
    // Python 解释器配置：
    //   - 环境变量 PYTHON_EXE 优先级最高
    //   - dev 模式默认使用 conda 环境（finance_tools）
    //   - 打包后使用系统检测的 pythonExe
    const DEV_PYTHON_EXE = '/opt/anaconda3/envs/finance_tools/bin/python';
    const resolvedPythonExe = process.env.PYTHON_EXE || (!electron_1.app.isPackaged ? DEV_PYTHON_EXE : pythonExe);
    // const isDebug = process.env.PYTHON_DEBUG === '1'
    // const isDebug = true
    const isDebug = false;
    if (isDebug || resolvedPythonExe !== pythonExe) {
        console.log(`[Main] Debug: ${isDebug}, Python exe: ${resolvedPythonExe}`);
    }
    pythonManager = new python_manager_1.PythonProcessManager({
        pythonExe: resolvedPythonExe,
        args: [pythonScript],
        debug: isDebug,
    });
    // 监听 Python 进程状态变化
    pythonManager.onStatusChange = (status) => {
        sendToRenderer('python:status-changed', status);
    };
    registerIpcHandlers();
    // 随 Electron 一起启动 Python 引擎
    pythonManager.start();
    console.log('[Main] Python engine auto-started');
    electron_1.app.on('activate', () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0)
            createWindow();
    });
});
electron_1.app.on('window-all-closed', () => {
    pythonManager?.stop();
    electron_1.app.quit();
});
//# sourceMappingURL=main.js.map