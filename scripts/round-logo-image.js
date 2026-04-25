const { app, BrowserWindow } = require('electron')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const sourcePath = path.join(root, 'src', 'assets', 'qingflow-logo-source.png')
const outputPaths = [
  path.join(root, 'src', 'assets', 'qingflow-logo.png'),
  path.join(root, 'src', 'public', 'qingflow-logo.png'),
]

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 1024,
    height: 1024,
    show: false,
    transparent: true,
    backgroundColor: '#00000000',
    webPreferences: { offscreen: true },
  })

  const image = fs.readFileSync(sourcePath)
  const imageUrl = `data:image/png;base64,${image.toString('base64')}`
  const html = `<!doctype html>
    <html>
      <body style="margin:0;width:1024px;height:1024px;background:transparent;overflow:hidden">
        <div style="width:1024px;height:1024px;border-radius:226px;overflow:hidden;background:transparent">
          <img src="${imageUrl}" style="width:1024px;height:1024px;display:block;object-fit:cover" />
        </div>
      </body>
    </html>`

  await win.loadURL(`data:text/html;base64,${Buffer.from(html).toString('base64')}`)
  await new Promise(resolve => setTimeout(resolve, 250))
  const captured = await win.webContents.capturePage()
  const png = captured.toPNG()

  for (const outputPath of outputPaths) {
    fs.writeFileSync(outputPath, png)
  }

  win.destroy()
  app.quit()
})
