// Wait for Vite dev server to be ready before launching Electron
const http = require('http')

const VITE_URL = 'http://localhost:5173'
const MAX_RETRIES = 60
const RETRY_INTERVAL = 300

function checkVite() {
  return new Promise((resolve) => {
    const req = http.get(VITE_URL, (res) => {
      resolve(res.statusCode === 200 || res.statusCode === 304)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(2000, () => { req.destroy(); resolve(false) })
  })
}

async function waitForVite() {
  console.log('[wait-vite] Waiting for Vite dev server...')
  for (let i = 0; i < MAX_RETRIES; i++) {
    const ready = await checkVite()
    if (ready) {
      console.log('[wait-vite] Vite is ready!')
      process.exit(0)
    }
    await new Promise(r => setTimeout(r, RETRY_INTERVAL))
    process.stdout.write('.')
  }
  console.error('\n[wait-vite] Vite dev server not ready after timeout. Launching Electron anyway...')
  process.exit(0)
}

waitForVite()
