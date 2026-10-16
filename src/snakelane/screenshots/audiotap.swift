// snakelane's audio tap: records one process's audio output, through a Core Audio process tap
// (macOS 14.2+), until SIGINT or SIGTERM. `snakelane preview` builds it with swiftc on first use.
//
//   audiotap <pid> <out.caf>
//
// A simulated app is a Mac process with its own Core Audio process object, so tapping its pid
// takes its sound and nothing else: not the Mac's, not another simulator's.
// Why: docs/design/screenshots.md#a-previews-sound-is-tapped-from-the-apps-process
//
// stdout, one JSON line each: {"started": <epoch>} once the tap runs, and at exit
// {"first_buffer": <epoch>|null, "frames": n, "rate": hz, "peak": 0…1}. Frame 0 of the file is
// "first_buffer": the tap delivers nothing until the process first plays a sound. A gap in the
// process's output is written as silence, so the file stays on the wall clock.
import AVFoundation
import CoreAudio
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("audiotap: \(message)\n".utf8))
    exit(1)
}

func property<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, _ initial: T) -> T? {
    var address = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                             mElement: kAudioObjectPropertyElementMain)
    var value = initial
    var size = UInt32(MemoryLayout<T>.size)
    return withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(object, &address, 0, nil, &size, $0) == noErr
    } ? value : nil
}

func processObject(for pid: pid_t) -> AudioObjectID? {
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
                                             mScope: kAudioObjectPropertyScopeGlobal,
                                             mElement: kAudioObjectPropertyElementMain)
    let system = AudioObjectID(kAudioObjectSystemObject)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr else { return nil }
    var objects = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &objects) == noErr else { return nil }
    return objects.first { property($0, kAudioProcessPropertyPID, pid_t(-1)) == pid }
}

let arguments = CommandLine.arguments
guard arguments.count == 3, let pid = pid_t(arguments[1]) else { fail("usage: audiotap <pid> <out.caf>") }
// The process object can appear a moment after launch; give it a few seconds.
var target: AudioObjectID?
for _ in 0..<50 {
    if let found = processObject(for: pid) { target = found; break }
    Thread.sleep(forTimeInterval: 0.1)
}
guard let target else { fail("Core Audio has no process object for pid \(pid)") }

let description = CATapDescription(stereoMixdownOfProcesses: [target])
description.uuid = UUID()
description.muteBehavior = .unmuted
var tap = AudioObjectID(kAudioObjectUnknown)
var status = AudioHardwareCreateProcessTap(description, &tap)
guard status == noErr else { fail("AudioHardwareCreateProcessTap failed (\(status)); is audio capture allowed?") }
guard var format = property(tap, kAudioTapPropertyFormat, AudioStreamBasicDescription()) else {
    fail("the tap has no format")
}
let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "snakelane-audiotap",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: description.uuid.uuidString]],
]
var device = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &device)
guard status == noErr else { fail("AudioHardwareCreateAggregateDevice failed (\(status))") }

guard let audioFormat = AVAudioFormat(streamDescription: &format) else { fail("unreadable tap format") }
let file: AVAudioFile
do {
    file = try AVAudioFile(forWriting: URL(fileURLWithPath: arguments[2]), settings: audioFormat.settings,
                           commonFormat: .pcmFormatFloat32, interleaved: audioFormat.isInterleaved)
} catch { fail("cannot write \(arguments[2]): \(error)") }

var timebase = mach_timebase_info_data_t()
mach_timebase_info(&timebase)
func seconds(_ ticks: UInt64) -> Double { Double(ticks) * Double(timebase.numer) / Double(timebase.denom) / 1e9 }
let startHost = mach_absolute_time()
let startEpoch = Date().timeIntervalSince1970
let rate = audioFormat.sampleRate
var firstHost: UInt64 = 0
var written: Int64 = 0
var peak: Float = 0
let lock = NSLock()

var ioProc: AudioDeviceIOProcID?
status = AudioDeviceCreateIOProcIDWithBlock(&ioProc, device, nil) { _, input, inputTime, _, _ in
    lock.lock(); defer { lock.unlock() }
    guard let buffer = AVAudioPCMBuffer(pcmFormat: audioFormat, bufferListNoCopy: input, deallocator: nil),
          buffer.frameLength > 0 else { return }
    let host = inputTime.pointee.mHostTime
    if firstHost == 0 { firstHost = host }
    // Where this buffer belongs on the clock; more than 20 ms past the file's end is a gap to fill.
    let due = Int64((seconds(host &- firstHost) * rate).rounded())
    if due - written > Int64(rate * 0.02),
       let silence = AVAudioPCMBuffer(pcmFormat: audioFormat, frameCapacity: AVAudioFrameCount(due - written)) {
        silence.frameLength = silence.frameCapacity  // zero-filled
        try? file.write(from: silence)
        written += Int64(silence.frameLength)
    }
    if let channels = buffer.floatChannelData {
        for c in 0..<Int(buffer.format.channelCount) {
            for i in 0..<Int(buffer.frameLength) { peak = max(peak, abs(channels[c][i])) }
        }
    }
    try? file.write(from: buffer)
    written += Int64(buffer.frameLength)
}
guard status == noErr, let ioProc else { fail("AudioDeviceCreateIOProcIDWithBlock failed (\(status))") }
status = AudioDeviceStart(device, ioProc)
guard status == noErr else { fail("AudioDeviceStart failed (\(status))") }
print("{\"started\": \(startEpoch)}")
fflush(stdout)

let done = DispatchSemaphore(value: 0)
var sources: [DispatchSourceSignal] = []
for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .global())
    source.setEventHandler { done.signal() }
    source.resume()
    sources.append(source)
}
done.wait()

AudioDeviceStop(device, ioProc)
AudioDeviceDestroyIOProcID(device, ioProc)
AudioHardwareDestroyAggregateDevice(device)
AudioHardwareDestroyProcessTap(tap)
lock.lock()
let first = firstHost == 0 ? "null" : String(startEpoch + seconds(firstHost &- startHost))
print("{\"first_buffer\": \(first), \"frames\": \(written), \"rate\": \(rate), \"peak\": \(peak)}")
lock.unlock()
