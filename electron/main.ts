import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import { join, dirname } from 'path'
import { createWriteStream, existsSync } from 'fs'
import { cp } from 'fs/promises'
import { execFileSync } from 'child_process'
import { PythonProcessManager } from './python-manager'

let mainWindow: BrowserWindow | null = null
let pythonManager: PythonProcessManager | null = null

// ====== 日志系统：输出到用户数据目录的 app.log ======
function initLogger(): void {
  const logDir = app.getPath('userData')
  const logFile = join(logDir, 'app.log')
  // 追加模式，保留历史日志
  const stream = createWriteStream(logFile, { flags: 'a', encoding: 'utf-8' })

  const timestamp = () => new Date().toLocaleString('zh-CN')
  
  // 拦截 console，同时写入文件
  const origConsole = { ...console }
  const writeLog = (prefix: string, ...args: any[]) => {
    const msg = args.map(a => {
      if (typeof a === 'object') try { return JSON.stringify(a) } catch { return String(a) }
      return String(a)
    }).join(' ')
    const line = `[${timestamp()}] [${prefix}] ${msg}\n`
    stream.write(line)
    origConsole.log(`[${prefix}]`, ...args)
  }

  console.log = (...args) => writeLog('INFO', ...args)
  console.error = (...args) => writeLog('ERROR', ...args)
  console.warn = (...args) => writeLog('WARN', ...args)

  // 启动时写入分隔线（区分每次启动）
  stream.write('\n' + '='.repeat(60) + '\n')
  stream.write(`[App started at ${timestamp()}] isPackaged=${app.isPackaged}\n`)
  stream.write(`Log file: ${logFile}\n`)
  stream.write('='.repeat(60) + '\n\n')

  // 捕获未处理异常
  process.on('uncaughtException', (err) => {
    writeLog('FATAL', `UncaughtException: ${err.message}\n${err.stack}`)
  })
  process.on('unhandledRejection', (reason) => {
    writeLog('FATAL', `UnhandledRejection: ${reason}`)
  })
}

// 初始化日志（在 app ready 之前就可用）
initLogger()

/**
 * 查找可用的 Python 可执行文件
 * 优先级：内嵌 Python（打包后） > 系统 Python
 */
function findPython(): string {
  // 1. 打包后：优先使用内嵌 Python 运行时
  if (app.isPackaged) {
    const embeddedPython = join(process.resourcesPath, 'python-runtime', 'python.exe')
    if (existsSync(embeddedPython)) {
      try {
        const version = execFileSync(embeddedPython, ['--version'], {
          encoding: 'utf-8',
          timeout: 5000,
          windowsHide: true
        }).trim()
        console.log(`[findPython] Using embedded Python: ${embeddedPython} (${version})`)
        return embeddedPython
      } catch (e) {
        console.error('[findPython] Embedded Python exists but failed to run:', e)
      }
    } else {
      console.log('[findPython] No embedded Python found at:', embeddedPython)
    }
  }

  // 2. 回退到系统 Python
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python']
  
  for (const cmd of candidates) {
    try {
      const checkCmd = process.platform === 'win32' ? 'where' : 'which'
      const result = execFileSync(checkCmd, [cmd.split(' ')[0]], {
        encoding: 'utf-8',
        timeout: 3000,
        windowsHide: true
      }).trim()
      
      if (result) {
        const actualPath = result.split('\n')[0].trim()
        try {
          const version = execFileSync(actualPath, ['--version'], {
            encoding: 'utf-8',
            timeout: 5000,
            windowsHide: true
          }).trim()
          console.log(`[findPython] Using system Python: ${actualPath} (${version})`)
          return actualPath
        } catch { /* skip */ }
      }
    } catch { /* not found */ }
  }
  
  console.error(`[findPython] WARNING: No Python available!`)
  return candidates[0]
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 680,
    title: 'Finance Tools - 数据采集工具',
    frame: false,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#020617',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    },
    show: false
  })

  // 开发环境加载 Vite dev server
  if (!app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    // 打包后：前端在 src/dist/ 目录，用 getAppPath 获取项目根目录
    const indexPath = join(app.getAppPath(), 'src', 'dist', 'index.html')
    console.log('[Main] Loading production page:', indexPath)
    console.log('[Main] app.getAppPath():', app.getAppPath())
    mainWindow.loadFile(indexPath)
    
    // 页面加载错误诊断
    mainWindow.webContents.on('did-fail-load', (_event, _errorCode, _errorDesc, validatedURL) => {
      console.error('[Main] Page load FAILED:', validatedURL)
    })
    mainWindow.webContents.on('did-finish-load', () => {
      console.log('[Main] Page loaded OK, URL:', mainWindow?.webContents.getURL())
    })
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
    // 始终打开 DevTools（方便调试打包后的问题）
    mainWindow?.webContents.openDevTools({ mode: 'detach' })
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function sendToRenderer(channel: string, data?: any): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data)
  }
}

// 初始化 IPC 通道
function registerIpcHandlers(): void {
  // Python 引擎状态
  ipcMain.handle('python:start', async () => {
    if (!pythonManager) return { success: false, message: 'Python manager not initialized' }
    if (pythonManager.status === 'running') return { success: true, status: 'running' }
    
    const started = pythonManager.start()
    const status = pythonManager.status
    sendToRenderer('python:status-changed', status)
    return { success: started, status }
  })

  ipcMain.handle('python:status', async () => {
    return pythonManager?.status || 'stopped'
  })

  // 商家相关 IPC
  ipcMain.handle('merchant:list', async () => {
    return pythonManager?.sendRequest('merchant.list', {}) || []
  })

  ipcMain.handle('merchant:create', async (_event, data) => {
    return pythonManager?.sendRequest('merchant.create', data)
  })

  ipcMain.handle('merchant:update', async (_event, data) => {
    return pythonManager?.sendRequest('merchant.update', data)
  })

  ipcMain.handle('merchant:delete', async (_event, id) => {
    return pythonManager?.sendRequest('merchant.delete', { id })
  })

  ipcMain.handle('merchant:test-login', async (_event, id) => {
    return pythonManager?.sendRequest('merchant.testLogin', { id })
  })

  // 任务相关 IPC
  ipcMain.handle('task:start', async (_event, merchantId?: string) => {
    return pythonManager?.sendRequest('task.start', { merchantId: merchantId || null })
  })

  ipcMain.handle('task:stop', async (_event, merchantId?: string) => {
    return pythonManager?.sendRequest('task.stop', { merchantId: merchantId || null })
  })

  ipcMain.handle('task:start-all', async () => {
    return pythonManager?.sendRequest('task.startAll', {})
  })

  ipcMain.handle('task:stop-all', async () => {
    return pythonManager?.sendRequest('task.stopAll', {})
  })

  // 任务配置 IPC
  ipcMain.handle('taskConfig:list', async () => {
    return pythonManager?.sendRequest('taskConfig.list', {}) || []
  })

  ipcMain.handle('taskConfig:listByMerchant', async (_event, merchantId: string) => {
    return pythonManager?.sendRequest('taskConfig.listByMerchant', { merchantId }) || []
  })

  ipcMain.handle('taskConfig:create', async (_event, data) => {
    return pythonManager?.sendRequest('taskConfig.create', data)
  })

  ipcMain.handle('taskConfig:update', async (_event, data) => {
    return pythonManager?.sendRequest('taskConfig.update', data)
  })

  ipcMain.handle('taskConfig:delete', async (_event, id) => {
    return pythonManager?.sendRequest('taskConfig.delete', { id })
  })

  ipcMain.handle('taskConfig:execute', async (_event, taskId: string) => {
    return pythonManager?.sendRequest('taskConfig.execute', { taskId })
  })

  ipcMain.handle('taskConfig:parseCurl', async (_event, curl: string) => {
    return pythonManager?.sendRequest('taskConfig.parseCurl', { curl })
  })

  // 数据相关 IPC
  ipcMain.handle('data:list', async (_event, params?: any) => {
    return pythonManager?.sendRequest('data.list', params || {})
  })

  ipcMain.handle('data:export', async (_event, merchantId?: string) => {
    return pythonManager?.sendRequest('data.export', { merchantId: merchantId || null })
  })

  ipcMain.handle('data:delete', async (_event, id) => {
    return pythonManager?.sendRequest('data.delete', { id })
  })

  // 窗口控制
  ipcMain.handle('window:minimize', async () => {
    mainWindow?.minimize()
  })

  // 文件对话框
  ipcMain.handle('dialog:save', async (_event, options?: any) => {
    const result = await dialog.showSaveDialog(mainWindow!, {
      title: options?.title || '保存文件',
      defaultPath: options?.defaultPath || '',
      filters: options?.filters || [{ name: 'Excel', extensions: ['xlsx'] }],
    })
    return result
  })

  // 文件复制（导出时将临时文件复制到用户选择的位置）
  ipcMain.handle('file:copy', async (_event, srcPath: string, destPath: string) => {
    await cp(srcPath, destPath)
    return destPath
  })

  ipcMain.handle('window:maximize', async () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow?.maximize()
    }
  })

  ipcMain.handle('window:close', async () => {
    mainWindow?.close()
  })
}

app.whenReady().then(() => {
  createWindow()
  
  // 查找可用的 Python 可执行文件
  const pythonExe = findPython()
  console.log('[Main] Using python executable:', pythonExe)
  
  // 打包后：python/ 在 app.asar.unpacked/resources/python/
  let pythonScript: string
  if (app.isPackaged) {
    pythonScript = join(process.resourcesPath, 'python', 'main.py')
    console.log('[Main] Packaged mode, resourcesPath:', process.resourcesPath)
    console.log('[Main] Python script path:', pythonScript)
  } else {
    pythonScript = join(__dirname, '..', 'python', 'main.py')
    console.log('[Main] Dev mode, Python script path:', pythonScript)
  }
  
  // 检查 Python 脚本是否存在
  if (!existsSync(pythonScript)) {
    console.error(`[Main] FATAL: Python script not found: ${pythonScript}`)
  } else {
    console.log('[Main] Python script exists OK')
  }

  // 设置环境变量（内嵌 Python 需要 PYTHONPATH 找到项目模块）
  const pythonDir = app.isPackaged
    ? join(process.resourcesPath, 'python')
    : join(__dirname, '..', 'python')
  process.env.PYTHONPATH = pythonDir
  // 强制 UTF-8 编码，解决 Windows 打包后 GBK 编码导致 emoji/中文报错
  process.env.PYTHONIOENCODING = 'utf-8'
  // 打包后：指定 Playwright 浏览器路径（随 extraResources 一起打包）
  if (app.isPackaged) {
    const pwBrowserPath = join(process.resourcesPath, 'ms-playwright')
    if (existsSync(pwBrowserPath)) {
      process.env.PLAYWRIGHT_BROWSERS_PATH = pwBrowserPath
      console.log('[Main] PLAYWRIGHT_BROWSERS_PATH:', pwBrowserPath)
    }
  }
  console.log('[Main] PYTHONPATH:', process.env.PYTHONPATH)

  pythonManager = new PythonProcessManager(pythonExe, [pythonScript])

  // 监听 Python 进程状态变化
  pythonManager.onStatusChange = (status: string) => {
    sendToRenderer('python:status-changed', status)
  }

  registerIpcHandlers()

  // 随 Electron 一起启动 Python 引擎
  pythonManager.start()
  console.log('[Main] Python engine auto-started')

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  pythonManager?.stop()
  app.quit()
})
