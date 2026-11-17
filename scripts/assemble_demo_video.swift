import AVFoundation
import CoreGraphics
import Foundation
import ImageIO

let arguments = CommandLine.arguments
guard arguments.count >= 4 else {
    fputs("usage: assemble_demo_video.swift OUTPUT.mp4 FRAME.png...\n", stderr)
    exit(2)
}

let output = URL(fileURLWithPath: arguments[1])
let frameURLs = arguments.dropFirst(2).map { URL(fileURLWithPath: $0) }
let images: [CGImage] = frameURLs.compactMap { url in
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
}
guard images.count == frameURLs.count, let first = images.first else {
    fputs("could not read every input frame\n", stderr)
    exit(1)
}

try? FileManager.default.removeItem(at: output)
let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: first.width,
    AVVideoHeightKey: first.height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 2_400_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    ],
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
        kCVPixelBufferWidthKey as String: first.width,
        kCVPixelBufferHeightKey as String: first.height,
    ]
)
guard writer.canAdd(input) else {
    fputs("could not add video input\n", stderr)
    exit(1)
}
writer.add(input)
guard writer.startWriting() else {
    fputs("could not start video writer: \(writer.error?.localizedDescription ?? "unknown error")\n", stderr)
    exit(1)
}
writer.startSession(atSourceTime: .zero)

func pixelBuffer(for image: CGImage) -> CVPixelBuffer {
    var buffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        image.width,
        image.height,
        kCVPixelFormatType_32ARGB,
        [kCVPixelBufferCGImageCompatibilityKey: true,
         kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary,
        &buffer
    )
    precondition(status == kCVReturnSuccess && buffer != nil)
    let result = buffer!
    CVPixelBufferLockBaseAddress(result, [])
    defer { CVPixelBufferUnlockBaseAddress(result, []) }
    let context = CGContext(
        data: CVPixelBufferGetBaseAddress(result),
        width: image.width,
        height: image.height,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(result),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
    )!
    context.translateBy(x: 0, y: CGFloat(image.height))
    context.scaleBy(x: 1, y: -1)
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
    return result
}

let frameRate: Int32 = 10
let durations = images.indices.map { $0 == images.count - 1 ? 6.0 : 4.5 }
var frameNumber: Int64 = 0
for (index, image) in images.enumerated() {
    let buffer = pixelBuffer(for: image)
    let repeats = Int(durations[index] * Double(frameRate))
    for _ in 0..<repeats {
        while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.002) }
        let time = CMTime(value: frameNumber, timescale: frameRate)
        guard adaptor.append(buffer, withPresentationTime: time) else {
            fputs("could not append video frame: \(writer.error?.localizedDescription ?? "unknown error")\n", stderr)
            exit(1)
        }
        frameNumber += 1
    }
}

input.markAsFinished()
let semaphore = DispatchSemaphore(value: 0)
writer.finishWriting { semaphore.signal() }
semaphore.wait()
guard writer.status == .completed else {
    fputs("could not finalize video: \(writer.error?.localizedDescription ?? "unknown error")\n", stderr)
    exit(1)
}

