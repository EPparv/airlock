import AppKit
let out = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
let standard = [("icon_16x16",16),("icon_16x16@2x",32),("icon_32x32",32),("icon_32x32@2x",64),("icon_128x128",128),("icon_128x128@2x",256),("icon_256x256",256),("icon_256x256@2x",512),("icon_512x512",512),("icon_512x512@2x",1024)]
let sizes = CommandLine.arguments.count > 2 ? [("icon-180",180),("icon-192",192),("icon-512",512)] : standard
for (name, size) in sizes {
 let bitmap = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
 let scale=CGFloat(size)/1024; (AffineTransform(scale:scale) as NSAffineTransform).concat()
 let shadow=NSShadow();shadow.shadowColor=NSColor.black.withAlphaComponent(0.24);shadow.shadowBlurRadius=25;shadow.shadowOffset=NSSize(width:0,height:-10);shadow.set()
 let tile=NSBezierPath(roundedRect:NSRect(x:60,y:60,width:904,height:904),xRadius:210,yRadius:210)
 NSGradient(starting:NSColor(red:0.055,green:0.086,blue:0.14,alpha:1),ending:NSColor(red:0.17,green:0.23,blue:0.32,alpha:1))!.draw(in:tile,angle:70)
 NSShadow().set();NSColor(red:0.33,green:0.42,blue:0.55,alpha:1).setStroke();tile.lineWidth=3;tile.stroke()
 let gate=NSBezierPath();gate.move(to:NSPoint(x:420,y:755));gate.line(to:NSPoint(x:325,y:755));gate.curve(to:NSPoint(x:270,y:700),controlPoint1:NSPoint(x:290,y:755),controlPoint2:NSPoint(x:270,y:735));gate.line(to:NSPoint(x:270,y:324));gate.curve(to:NSPoint(x:325,y:269),controlPoint1:NSPoint(x:270,y:289),controlPoint2:NSPoint(x:290,y:269));gate.line(to:NSPoint(x:420,y:269))
 gate.move(to:NSPoint(x:604,y:755));gate.line(to:NSPoint(x:699,y:755));gate.curve(to:NSPoint(x:754,y:700),controlPoint1:NSPoint(x:734,y:755),controlPoint2:NSPoint(x:754,y:735));gate.line(to:NSPoint(x:754,y:324));gate.curve(to:NSPoint(x:699,y:269),controlPoint1:NSPoint(x:754,y:289),controlPoint2:NSPoint(x:734,y:269));gate.line(to:NSPoint(x:604,y:269))
 NSColor(red:0.88,green:0.94,blue:1,alpha:1).setStroke();gate.lineWidth=65;gate.lineCapStyle = .round;gate.lineJoinStyle = .round;gate.stroke()
 NSColor(red:0.66,green:0.81,blue:1,alpha:1).setFill();NSBezierPath(roundedRect:NSRect(x:478,y:393,width:68,height:238),xRadius:34,yRadius:34).fill()
 NSGraphicsContext.restoreGraphicsState();try bitmap.representation(using:.png,properties:[:])!.write(to:out.appendingPathComponent(name+".png"))
}
