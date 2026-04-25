const { app, BrowserWindow } = require('electron')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const svgPath = path.join(root, 'src', 'assets', 'qingflow-logo.svg')
const outputPaths = [
  path.join(root, 'src', 'assets', 'qingflow-logo.png'),
  path.join(root, 'src', 'public', 'qingflow-logo.png'),
]

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 1024,
    height: 1024,
    show: false,
    webPreferences: { offscreen: true },
  })
  const svg = fs.readFileSync(svgPath, 'utf8')
  const imageUrl = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`
  const html = `<!doctype html><html><body style="margin:0;background:transparent"><img src="${imageUrl}" style="width:1024px;height:1024px;display:block" /></body></html>`

  await win.loadURL(`data:text/html;base64,${Buffer.from(html).toString('base64')}`)
  await new Promise(resolve => setTimeout(resolve, 250))
  const image = await win.webContents.capturePage()
  const png = image.toPNG()

  for (const outputPath of outputPaths) {
    fs.writeFileSync(outputPath, png)
  }

  win.destroy()
  app.quit()
})
