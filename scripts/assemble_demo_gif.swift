import Foundation
import ImageIO
import UniformTypeIdentifiers

let arguments = CommandLine.arguments
guard arguments.count >= 4 else {
    fputs("usage: assemble_demo_gif.swift OUTPUT.gif FRAME.png...\n", stderr)
    exit(2)
}

let output = URL(fileURLWithPath: arguments[1])
let frames = arguments.dropFirst(2).map { URL(fileURLWithPath: $0) }
guard let firstSource = CGImageSourceCreateWithURL(frames[0] as CFURL, nil),
      let firstImage = CGImageSourceCreateImageAtIndex(firstSource, 0, nil),
      let destination = CGImageDestinationCreateWithURL(
        output as CFURL,
        UTType.gif.identifier as CFString,
        frames.count,
        nil
      ) else {
    fputs("could not create GIF destination\n", stderr)
    exit(1)
}

let canvas = "{GIF}" as CFString
let loop = "LoopCount" as CFString
CGImageDestinationSetProperties(destination, [canvas: [loop: 0]] as CFDictionary)

for (index, frame) in frames.enumerated() {
    guard let source = CGImageSourceCreateWithURL(frame as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fputs("could not read \(frame.path)\n", stderr)
        exit(1)
    }
    _ = firstImage // Keep the first image alive while encoding on older ImageIO builds.
    let delay = index == frames.count - 1 ? 7.0 : 6.0
    let properties: [CFString: Any] = [
        "{GIF}" as CFString: [
            "DelayTime" as CFString: delay,
            "UnclampedDelayTime" as CFString: delay,
        ],
    ]
    CGImageDestinationAddImage(destination, image, properties as CFDictionary)
}

guard CGImageDestinationFinalize(destination) else {
    fputs("could not finalize GIF\n", stderr)
    exit(1)
}
