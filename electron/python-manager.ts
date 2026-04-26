import { ChildProcess, spawn } from 'child_process'
import path from 'path'

interface JsonRpcRequest {
  jsonrpc: '2.0'
  id: number
  method: string
  params: Record<string, unknown>
}

interface JsonRpcResponse {
  jsonrpc: '2.0'
  id: number
  result?: unknown
  error?: {
    code: number
    message: string
    data?: unknown
  }
}

export interface PythonManagerOptions {
  /** Python 可执行文件路径，如 'python3' 或 '/usr/local/bin/python3' */
  pythonExe: string
  /** Python 脚本参数列表，第一个元素为脚本路径 */
  args: string[]
  /** 是否开启 PYTHON_DEBUG（默认 false），设为 true 时 Python 端会连接 PyCharm 远程调试 */
  debug?: boolean
  /** 额外注入的环境变量（可选） */
  extraEnv?: Record<string, string>
}

export class PythonProcessManager {
  private process: ChildProcess | null = null
  private requestId = 0
  private pendingCallbacks = new Map<number, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
  }>()
  private buffer = ''
  private _isRunning = false
  private pythonExe: string
  private args: string[]
  private options: PythonManagerOptions
  
  // 状态变化回调
  public onStatusChange?: (status: string) => void

  constructor(options: PythonManagerOptions) {
    this.pythonExe = options.pythonExe
    this.args = options.args
    this.options = { debug: false, ...options }
  }

  start(): boolean {
    if (this._isRunning) return true

    try {
      const scriptPath = this.args[0]
      console.log('[PythonManager] Starting process')
      console.log('[PythonManager] pythonExe:', this.pythonExe)
      console.log('[PythonManager] args:', this.args)
      console.log('[PythonManager] cwd:', path.dirname(scriptPath))
      console.log('[PythonManager] FINANCE_TOOLS_DB:', this.options.extraEnv?.FINANCE_TOOLS_DB || process.env.FINANCE_TOOLS_DB || '')
      
      this.process = spawn(this.pythonExe, this.args, {
        cwd: path.dirname(scriptPath),
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          // 灵活控制 debug 模式，本地开发时可开启连接 PyCharm 调试
          ...(this.options.debug ? { PYTHON_DEBUG: '1' } : {}),
          ...this.options.extraEnv,
        },
        stdio: ['pipe', 'pipe', 'pipe']
      })

      // 处理标准输出（JSON-RPC 消息）
      this.process.stdout?.on('data', (chunk) => {
        this.buffer += chunk.toString()
        
        // 尝试解析完整的 JSON 行
        while (true) {
          const newlineIdx = this.buffer.indexOf('\n')
          if (newlineIdx === -1) break
          
          const line = this.buffer.substring(0, newlineIdx).trim()
          this.buffer = this.buffer.substring(newlineIdx + 1)
          
          if (!line) continue
          
          try {
            const message = JSON.parse(line)
            this.handleMessage(message)
          } catch (err) {
            console.error('[PythonManager] Failed to parse output:', err, line)
          }
        }
      })

      // 处理错误输出（日志）
      this.process.stderr?.on('data', (chunk) => {
        const lines = chunk.toString().split('\n')
        for (const line of lines) {
          if (line.trim()) {
            console.log(`[Python] ${line}`)
          }
        }
      })

      // 进程退出处理
      this.process.on('exit', (code) => {
        this._isRunning = false
        console.log(`[PythonManager] Process exited with code: ${code}`)
        this.onStatusChange?.('stopped')
        
        // 拒绝所有挂起的请求
        for (const [id, callback] of this.pendingCallbacks) {
          callback.reject(new Error(`Python process exited with code ${code}`))
          this.pendingCallbacks.delete(id)
        }
      })

      this.process.on('error', (err) => {
        this._isRunning = false
        console.error('[PythonManager] Process error:', err.message)
        this.onStatusChange?.('error')
      })

      this._isRunning = true
      this.onStatusChange?.('running')
      return true
      
    } catch (error) {
      console.error('[PythonManager] Failed to start process:', error)
      this.onStatusChange?.('error')
      return false
    }
  }

  stop(): void {
    if (!this.process || !this._isRunning) return
    
    try {
      // 发送退出信号
      this.sendRaw({ jsonrpc: '2.0', id: 0, method: 'system.exit', params: {} })
      
      // 强制终止
      setTimeout(() => {
        if (this.process && !this.process.killed) {
          this.process.kill('SIGTERM')
        }
      }, 3000)
    } catch (e) {
      console.error('[PythonManager] Stop error:', e)
    }
    
    this._isRunning = false
    this.onStatusChange?.('stopped')
  }

  sendRequest(method: string, params: Record<string, unknown>): Promise<unknown> {
    // 自动启动进程
    if (!this._isRunning) {
      this.onStatusChange?.('starting')
      const started = this.start()
      if (!started) {
        return Promise.reject(new Error('Failed to start Python process'))
      }
    }

    return new Promise((resolve, reject) => {
      this.requestId++
      const id = this.requestId

      const request: JsonRpcRequest = {
        jsonrpc: '2.0',
        id,
        method,
        params
      }

      // 设置超时（5分钟）
      const timeout = setTimeout(() => {
        this.pendingCallbacks.delete(id)
        reject(new Error(`RPC request timeout: ${method} (id=${id})`))
      }, 5 * 60 * 1000)

      this.pendingCallbacks.set(id, {
        resolve: (val) => {
          clearTimeout(timeout)
          resolve(val)
        },
        reject: (err) => {
          clearTimeout(timeout)
          reject(err)
        }
      })

      this.sendRaw(request)
    })
  }

  private sendRaw(request: JsonRpcRequest): void {
    if (!this.process?.stdin) {
      throw new Error('Python process stdin not available')
    }
    
    const data = JSON.stringify(request) + '\n'
    this.process.stdin.write(data)
  }

  private handleMessage(message: JsonRpcResponse & { event?: string; data?: unknown }): void {
    // 处理事件通知（无 id）
    if ('event' in message && message.event) {
      this.handleEvent(message.event, message.data)
      return
    }

    // 处理 RPC 响应
    if (message.id !== undefined && this.pendingCallbacks.has(message.id)) {
      const callback = this.pendingCallbacks.get(message.id)!
      this.pendingCallbacks.delete(message.id)

      if (message.error) {
        callback.reject(new Error(message.error.message))
      } else {
        callback.resolve(message.result)
      }
    }
  }

  private handleEvent(event: string, data?: unknown): void {
    console.log(`[PythonManager] Event received: ${event}`, data)
    
    // 转发给主窗口的渲染进程
    const { BrowserWindow } = require('electron')
    const windows = BrowserWindow.getAllWindows()
    windows.forEach((win: Electron.BrowserWindow) => {
      win.webContents.send('python-event', { event, data })
    })
  }

  get status(): 'stopped' | 'starting' | 'running' | 'error' {
    if (!this.process) return 'stopped'
    if (this._isRunning) return 'running'
    return 'stopped'
  }
}
