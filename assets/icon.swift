import AppKit

let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()

// ---------- 圆角方（squircle 近似）底 ----------
let inset: CGFloat = 100
let side = size - inset * 2
let bg = NSBezierPath(roundedRect: NSRect(x: inset, y: inset, width: side, height: side),
                      xRadius: 186, yRadius: 186)
let grad = NSGradient(colors: [
    NSColor(red: 0.42, green: 0.68, blue: 0.61, alpha: 1),
    NSColor(red: 0.11, green: 0.33, blue: 0.28, alpha: 1)
])
grad?.draw(in: bg, angle: -55)

// 顶部高光（软渐变，避免硬边）
bg.setClip()
let sheen = NSGradient(colors: [
    NSColor.white.withAlphaComponent(0.0),
    NSColor.white.withAlphaComponent(0.13)
])
sheen?.draw(in: NSRect(x: 0, y: inset, width: size, height: side), angle: 90)

// ---------- 立方体门户（品牌符号 ◈） ----------
let s: CGFloat = 32.0
let cx: CGFloat = 512, cyv: CGFloat = 512 + 14
func pt(_ x: CGFloat, _ y: CGFloat) -> NSPoint {
    // SVG y 向下 → AppKit y 向上，以立方体中心 (12,11) 为锚
    return NSPoint(x: cx + (x - 12) * s, y: cyv + (11 - y) * s)
}
let top = pt(12, 2), right = pt(20, 6.5), br = pt(20, 15.5)
let bottom = pt(12, 20), bl = pt(4, 15.5), left = pt(4, 6.5), c = pt(12, 11)

func poly(_ pts: [NSPoint], _ color: NSColor) {
    let p = NSBezierPath()
    p.move(to: pts[0])
    for i in 1..<pts.count { p.line(to: pts[i]) }
    p.close()
    color.setFill()
    p.fill()
}
// 三个面：受光面 / 侧光面 / 背光面
poly([top, right, c, left],   NSColor.white.withAlphaComponent(0.94))
poly([c, left, bl, bottom],   NSColor.white.withAlphaComponent(0.72))
poly([c, right, br, bottom],  NSColor(white: 0.92, alpha: 0.40))

// 棱线
let outline = NSBezierPath()
outline.move(to: top); outline.line(to: right); outline.line(to: br)
outline.line(to: bottom); outline.line(to: bl); outline.line(to: left); outline.line(to: top)
outline.move(to: c); outline.line(to: left)
outline.move(to: c); outline.line(to: right)
outline.move(to: c); outline.line(to: bottom)
outline.lineWidth = 11
outline.lineJoinStyle = .round
NSColor.white.withAlphaComponent(0.96).setStroke()
outline.stroke()

// ---------- 金色顶点（发布的“信号”） ----------
let apex = pt(12, 2)
let halo = NSBezierPath(ovalIn: NSRect(x: apex.x - 34, y: apex.y - 34, width: 68, height: 68))
NSColor.white.withAlphaComponent(0.25).setFill()
halo.fill()
let dot = NSBezierPath(ovalIn: NSRect(x: apex.x - 21, y: apex.y - 21, width: 42, height: 42))
NSColor(red: 0.85, green: 0.70, blue: 0.42, alpha: 1).setFill()
dot.fill()
NSColor.white.withAlphaComponent(0.9).setStroke()
dot.lineWidth = 6
dot.stroke()

image.unlockFocus()

// ---------- 导出 PNG ----------
let tiff = image.tiffRepresentation!
let rep = NSBitmapImageRep(data: tiff)!
let png = rep.representation(using: .png, properties: [:])!
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon_1024.png"
try! png.write(to: URL(fileURLWithPath: out))
print("icon written: \(out)")
