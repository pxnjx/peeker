# Generates the Peeker brand assets from the geometry in public/icon.svg so the
# favicon, touch icons, PWA icons and OpenGraph image all stay one design:
# Substack ink tile (#313131), white map pin, electric-blue pin-dot (#0000ee).
#
# Run: powershell -ExecutionPolicy Bypass -File tools\generate-brand-assets.ps1
# Requires only .NET System.Drawing (bundled with Windows PowerShell 5.1).

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$outDir = Join-Path $PSScriptRoot "..\public"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$navy = [System.Drawing.Color]::FromArgb(255, 49, 49, 49)     # Substack ink #313131
$indigo = [System.Drawing.Color]::FromArgb(255, 0, 0, 238)     # Substack primary #0000ee
$canvas = [System.Drawing.Color]::FromArgb(255, 255, 255, 255) # Substack canvas #ffffff
$muted = [System.Drawing.Color]::FromArgb(255, 92, 92, 92)     # muted text token
$hairline = [System.Drawing.Color]::FromArgb(255, 212, 212, 212) # hairline token
$white = [System.Drawing.Color]::White

function New-RoundRectPath {
  param([float]$X, [float]$Y, [float]$W, [float]$H, [float]$R)
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = 2 * $R
  $p.AddArc($X, $Y, $d, $d, 180, 90)
  $p.AddArc($X + $W - $d, $Y, $d, $d, 270, 90)
  $p.AddArc($X + $W - $d, $Y + $H - $d, $d, $d, 0, 90)
  $p.AddArc($X, $Y + $H - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

# The map-pin mark: teardrop body + head hole, plus one accent pin-dot.
function Draw-BrandMark {
  param(
    [System.Drawing.Graphics]$G,
    [float]$Size,      # canvas edge length
    [switch]$FullBleed # solid square instead of rounded tile, content pulled into
                       # the maskable safe zone for PWA / touch icons
  )
  $k = $Size / 64.0
  $pad = 1.0 # keep strokes inside the canvas edge
  $scale = 1.0
  if ($FullBleed) {
    $brush = New-Object System.Drawing.SolidBrush($navy)
    $G.FillRectangle($brush, 0, 0, $Size, $Size)
    $brush.Dispose()
    # pull every coordinate 18% toward the centre (maskable safe zone)
    $scale = 0.82
    $cx = $Size / 2.0
    $mx = { param($x) [float]($cx + ($x - 32.0) * $scale * $k) }
    $my = { param($y) [float]($cx + ($y - 32.0) * $scale * $k) }
  } else {
    $r = [float](14 * $k)
    $tile = New-RoundRectPath $pad $pad ($Size - 2 * $pad) ($Size - 2 * $pad) $r
    $brush = New-Object System.Drawing.SolidBrush($navy)
    $G.FillPath($brush, $tile)
    $brush.Dispose()
    $tile.Dispose()
    $mx = { param($x) [float]($x * $k) }
    $my = { param($y) [float]($y * $k) }
  }

  # Teardrop pin body (matches the path in public/icon.svg).
  $pin = New-Object System.Drawing.Drawing2D.GraphicsPath
  $pin.AddBezier(
    (& $mx 32), (& $my 10),
    (& $mx 23.2), (& $my 10),
    (& $mx 16), (& $my 17.2),
    (& $mx 16), (& $my 26)
  )
  $pin.AddBezier(
    (& $mx 16), (& $my 26),
    (& $mx 16), (& $my 37.5),
    (& $mx 32), (& $my 49),
    (& $mx 32), (& $my 51.3)
  )
  $pin.AddBezier(
    (& $mx 32), (& $my 51.3),
    (& $mx 32), (& $my 49),
    (& $mx 48), (& $my 37.5),
    (& $mx 48), (& $my 26)
  )
  $pin.AddBezier(
    (& $mx 48), (& $my 26),
    (& $mx 48), (& $my 17.2),
    (& $mx 40.8), (& $my 10),
    (& $mx 32), (& $my 10)
  )
  $pin.CloseFigure()
  $hole = New-Object System.Drawing.Drawing2D.GraphicsPath
  $holeR = [float](6.5 * $k * $scale)
  $holeX = & $mx 32
  $holeY = & $my 26
  $hole.AddEllipse(($holeX - $holeR), ($holeY - $holeR), (2 * $holeR), (2 * $holeR))
  $pin.AddPath($hole, $false)
  $hole.Dispose()
  $brush = New-Object System.Drawing.SolidBrush($white)
  $G.FillPath($brush, $pin)
  $brush.Dispose()
  $pin.Dispose()

  $dotR = [float](4.5 * $k * $scale)
  $dotX = & $mx 32
  $dotY = & $my 26
  $dotBrush = New-Object System.Drawing.SolidBrush($indigo)
  $G.FillEllipse($dotBrush, ($dotX - $dotR), ($dotY - $dotR), (2 * $dotR), (2 * $dotR))
  $dotBrush.Dispose()
}

function New-BrandBitmap {
  param([int]$Size, [switch]$FullBleed)
  $bmp = New-Object System.Drawing.Bitmap($Size, $Size)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = "AntiAlias"
  $g.TextRenderingHint = "AntiAliasGridFit"
  $g.PageUnit = "Pixel"
  if (-not $FullBleed) { $g.Clear([System.Drawing.Color]::Transparent) }
  Draw-BrandMark -G $g -Size $Size -FullBleed:$FullBleed
  $g.Dispose()
  return $bmp
}

function Save-Png {
  param([System.Drawing.Bitmap]$Bmp, [string]$Name)
  $Bmp.Save((Join-Path $outDir $Name), [System.Drawing.Imaging.ImageFormat]::Png)
  $Bmp.Dispose()
  Write-Host "wrote $Name"
}

# --- Rounded-tile favicon at 16 / 32 / 48, packed as PNG entries in an ICO ---
$icoImages = @()
foreach ($size in 16, 32, 48) {
  $bmp = New-BrandBitmap -Size $size
  $ms = New-Object System.IO.MemoryStream
  $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $icoImages += @{ Size = $size; Bytes = $ms.ToArray() }
  $ms.Dispose()
}
$bw = New-Object System.IO.BinaryWriter([System.IO.File]::Create((Join-Path $outDir "favicon.ico")))
try {
  $bw.Write([uint16]0) # reserved
  $bw.Write([uint16]1) # type: icon
  $bw.Write([uint16]$icoImages.Count)
  $offset = 6 + 16 * $icoImages.Count
  foreach ($img in $icoImages) {
    $bw.Write([byte]($img.Size -band 0xFF))
    $bw.Write([byte]($img.Size -band 0xFF))
    $bw.Write([byte]0)
    $bw.Write([byte]0)
    $bw.Write([uint16]1)
    $bw.Write([uint16]32)
    $bw.Write([uint32]$img.Bytes.Length)
    $bw.Write([uint32]$offset)
    $offset += $img.Bytes.Length
  }
  foreach ($img in $icoImages) { $bw.Write($img.Bytes) }
} finally { $bw.Dispose() }
Write-Host "wrote favicon.ico"


# --- Full-bleed touch / PWA icons (opaque, maskable-safe) ---
Save-Png -Bmp (New-BrandBitmap -Size 180 -FullBleed) -Name "apple-touch-icon.png"
Save-Png -Bmp (New-BrandBitmap -Size 192 -FullBleed) -Name "icon-192.png"
Save-Png -Bmp (New-BrandBitmap -Size 512 -FullBleed) -Name "icon-512.png"

# --- OpenGraph card 1200x630, composed from the same tokens as globals.css ---
$og = New-Object System.Drawing.Bitmap(1200, 630)
$g = [System.Drawing.Graphics]::FromImage($og)
$g.SmoothingMode = "AntiAlias"
$g.TextRenderingHint = "AntiAliasGridFit"
$g.PageUnit = "Pixel"
$g.Clear($canvas)

$frame = New-RoundRectPath 40 40 1120 550 24
$pen = New-Object System.Drawing.Pen($hairline, 2)
$g.DrawPath($pen, $frame)
$pen.Dispose()
$frame.Dispose()

# Tile with the brand map pin: 150px, optically centred against the text block.
$tileSize = 150.0
$tileX = 96.0
$tileY = 213.0
$t = New-RoundRectPath $tileX $tileY $tileSize $tileSize 34
$brush = New-Object System.Drawing.SolidBrush($navy)
$g.FillPath($brush, $t)
$brush.Dispose()
$t.Dispose()

$k = $tileSize / 64.0
$pin = New-Object System.Drawing.Drawing2D.GraphicsPath
$pin.AddBezier(
  [float]($tileX + 32 * $k), [float]($tileY + 10 * $k),
  [float]($tileX + 23.2 * $k), [float]($tileY + 10 * $k),
  [float]($tileX + 16 * $k), [float]($tileY + 17.2 * $k),
  [float]($tileX + 16 * $k), [float]($tileY + 26 * $k)
)
$pin.AddBezier(
  [float]($tileX + 16 * $k), [float]($tileY + 26 * $k),
  [float]($tileX + 16 * $k), [float]($tileY + 37.5 * $k),
  [float]($tileX + 32 * $k), [float]($tileY + 49 * $k),
  [float]($tileX + 32 * $k), [float]($tileY + 51.3 * $k)
)
$pin.AddBezier(
  [float]($tileX + 32 * $k), [float]($tileY + 51.3 * $k),
  [float]($tileX + 32 * $k), [float]($tileY + 49 * $k),
  [float]($tileX + 48 * $k), [float]($tileY + 37.5 * $k),
  [float]($tileX + 48 * $k), [float]($tileY + 26 * $k)
)
$pin.AddBezier(
  [float]($tileX + 48 * $k), [float]($tileY + 26 * $k),
  [float]($tileX + 48 * $k), [float]($tileY + 17.2 * $k),
  [float]($tileX + 40.8 * $k), [float]($tileY + 10 * $k),
  [float]($tileX + 32 * $k), [float]($tileY + 10 * $k)
)
$pin.CloseFigure()
$hole = New-Object System.Drawing.Drawing2D.GraphicsPath
$holeR = [float](6.5 * $k)
$holeX = [float]($tileX + 32 * $k)
$holeY = [float]($tileY + 26 * $k)
$hole.AddEllipse(($holeX - $holeR), ($holeY - $holeR), (2 * $holeR), (2 * $holeR))
$pin.AddPath($hole, $false)
$hole.Dispose()
$pinBrush = New-Object System.Drawing.SolidBrush($white)
$g.FillPath($pinBrush, $pin)
$pinBrush.Dispose()
$pin.Dispose()
$dotR = [float](4.5 * $k)
$dotBrush = New-Object System.Drawing.SolidBrush($indigo)
$g.FillEllipse($dotBrush, ($holeX - $dotR), ($holeY - $dotR), (2 * $dotR), (2 * $dotR))
$dotBrush.Dispose()

$ink = New-Object System.Drawing.SolidBrush($navy)
$subBrush = New-Object System.Drawing.SolidBrush($muted)
$titleFont = New-Object System.Drawing.Font("Segoe UI", 72, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Point)
$subFont = New-Object System.Drawing.Font("Segoe UI", 26, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Point)
$g.DrawString("Peeker", $titleFont, $ink, 286, 186)
$g.DrawString("Google Maps review and competitor monitoring", $subFont, $subBrush, 290, 314)
$ink.Dispose()
$subBrush.Dispose()
$titleFont.Dispose()
$subFont.Dispose()

$accent = New-Object System.Drawing.SolidBrush($indigo)
$bar = New-RoundRectPath 292 376 72 10 5
$g.FillPath($accent, $bar)
$bar.Dispose()
$accent.Dispose()
$g.Dispose()
Save-Png -Bmp $og -Name "og.png"

Write-Host "done: favicon.ico, apple-touch-icon.png, icon-192.png, icon-512.png, og.png"
