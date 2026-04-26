const fs = require('fs')
const path = require('path')
const zlib = require('zlib')

const root = path.resolve(__dirname, '..')
const sourcePath = path.join(root, 'src', 'assets', 'qingflow-logo.png')
const outputPath = path.join(root, 'resources', 'qingflow.ico')
const sizes = [256, 128, 64, 48, 32, 16]

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function writeUInt16LE(buffer, value, offset) {
  buffer.writeUInt16LE(value, offset)
}

function writeUInt32LE(buffer, value, offset) {
  buffer.writeUInt32LE(value, offset)
}

function crc32(buffer) {
  let crc = 0xffffffff

  for (const byte of buffer) {
    crc ^= byte
    for (let i = 0; i < 8; i += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1))
    }
  }

  return (crc ^ 0xffffffff) >>> 0
}

function createChunk(type, data) {
  const typeBuffer = Buffer.from(type)
  const length = Buffer.alloc(4)
  const crc = Buffer.alloc(4)

  length.writeUInt32BE(data.length, 0)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 0)

  return Buffer.concat([length, typeBuffer, data, crc])
}

function parsePng(buffer) {
  if (!buffer.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) {
    throw new Error(`${sourcePath} is not a PNG file`)
  }

  let offset = PNG_SIGNATURE.length
  let width = 0
  let height = 0
  let bitDepth = 0
  let colorType = 0
  const idatChunks = []

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset)
    const type = buffer.toString('ascii', offset + 4, offset + 8)
    const dataStart = offset + 8
    const dataEnd = dataStart + length
    const data = buffer.subarray(dataStart, dataEnd)

    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      bitDepth = data[8]
      colorType = data[9]
    } else if (type === 'IDAT') {
      idatChunks.push(data)
    } else if (type === 'IEND') {
      break
    }

    offset = dataEnd + 4
  }

  if (bitDepth !== 8 || (colorType !== 2 && colorType !== 6)) {
    throw new Error(`Unsupported PNG format: bitDepth=${bitDepth}, colorType=${colorType}`)
  }

  return {
    width,
    height,
    channels: colorType === 6 ? 4 : 3,
    data: zlib.inflateSync(Buffer.concat(idatChunks)),
  }
}

function paethPredictor(left, above, upperLeft) {
  const prediction = left + above - upperLeft
  const leftDistance = Math.abs(prediction - left)
  const aboveDistance = Math.abs(prediction - above)
  const upperLeftDistance = Math.abs(prediction - upperLeft)

  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left
  if (aboveDistance <= upperLeftDistance) return above
  return upperLeft
}

function unfilterPng({ width, height, channels, data }) {
  const stride = width * channels
  const pixels = Buffer.alloc(width * height * 4)
  let sourceOffset = 0
  let previousRow = Buffer.alloc(stride)

  for (let y = 0; y < height; y += 1) {
    const filter = data[sourceOffset]
    sourceOffset += 1
    const row = Buffer.from(data.subarray(sourceOffset, sourceOffset + stride))
    sourceOffset += stride

    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? row[x - channels] : 0
      const above = previousRow[x]
      const upperLeft = x >= channels ? previousRow[x - channels] : 0

      if (filter === 1) row[x] = (row[x] + left) & 0xff
      else if (filter === 2) row[x] = (row[x] + above) & 0xff
      else if (filter === 3) row[x] = (row[x] + Math.floor((left + above) / 2)) & 0xff
      else if (filter === 4) row[x] = (row[x] + paethPredictor(left, above, upperLeft)) & 0xff
      else if (filter !== 0) throw new Error(`Unsupported PNG filter: ${filter}`)
    }

    for (let x = 0; x < width; x += 1) {
      const source = x * channels
      const target = (y * width + x) * 4
      pixels[target] = row[source]
      pixels[target + 1] = row[source + 1]
      pixels[target + 2] = row[source + 2]
      pixels[target + 3] = channels === 4 ? row[source + 3] : 255
    }

    previousRow = row
  }

  return pixels
}

function resizeNearest(sourcePixels, sourceWidth, sourceHeight, size) {
  const resized = Buffer.alloc(size * size * 4)

  for (let y = 0; y < size; y += 1) {
    const sourceY = Math.min(sourceHeight - 1, Math.floor((y * sourceHeight) / size))

    for (let x = 0; x < size; x += 1) {
      const sourceX = Math.min(sourceWidth - 1, Math.floor((x * sourceWidth) / size))
      const source = (sourceY * sourceWidth + sourceX) * 4
      const target = (y * size + x) * 4

      resized[target] = sourcePixels[source]
      resized[target + 1] = sourcePixels[source + 1]
      resized[target + 2] = sourcePixels[source + 2]
      resized[target + 3] = sourcePixels[source + 3]
    }
  }

  return resized
}

function encodePng(width, height, rgbaPixels) {
  const rawStride = width * 4
  const raw = Buffer.alloc((rawStride + 1) * height)

  for (let y = 0; y < height; y += 1) {
    const rowStart = y * (rawStride + 1)
    raw[rowStart] = 0
    rgbaPixels.copy(raw, rowStart + 1, y * rawStride, (y + 1) * rawStride)
  }

  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 6
  ihdr[10] = 0
  ihdr[11] = 0
  ihdr[12] = 0

  return Buffer.concat([
    PNG_SIGNATURE,
    createChunk('IHDR', ihdr),
    createChunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    createChunk('IEND', Buffer.alloc(0)),
  ])
}

function createIco(images) {
  const headerSize = 6
  const entrySize = 16
  const header = Buffer.alloc(headerSize + images.length * entrySize)
  writeUInt16LE(header, 0, 0)
  writeUInt16LE(header, 1, 2)
  writeUInt16LE(header, images.length, 4)

  let offset = header.length
  images.forEach((image, index) => {
    const entryOffset = headerSize + index * entrySize
    header[entryOffset] = image.size === 256 ? 0 : image.size
    header[entryOffset + 1] = image.size === 256 ? 0 : image.size
    header[entryOffset + 2] = 0
    header[entryOffset + 3] = 0
    writeUInt16LE(header, 1, entryOffset + 4)
    writeUInt16LE(header, 32, entryOffset + 6)
    writeUInt32LE(header, image.png.length, entryOffset + 8)
    writeUInt32LE(header, offset, entryOffset + 12)
    offset += image.png.length
  })

  return Buffer.concat([header, ...images.map(image => image.png)])
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true })

const source = parsePng(fs.readFileSync(sourcePath))
const sourcePixels = unfilterPng(source)
const images = sizes.map(size => ({
  size,
  png: encodePng(size, size, resizeNearest(sourcePixels, source.width, source.height, size)),
}))

fs.writeFileSync(outputPath, createIco(images))
console.log(`Wrote ${outputPath}`)
