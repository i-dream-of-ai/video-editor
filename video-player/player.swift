import AVFoundation
import AVKit
import AppKit
import Foundation
import PythonKit  // You'll need to add this dependency to your project

NSApplication.shared.activate(ignoringOtherApps: true)

class VideoPlayerDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var playerView: AVPlayerView!
    var player: AVPlayer!
    var queuePlayer: AVQueuePlayer!
    var playerLooper: AVPlayerLooper?
    
    // Frame processing
    var pythonProcessor: PythonFrameProcessor!
    var isProcessingEnabled: Bool = false
    var processingOutput: AVSampleBufferDisplayLayer!
    var displayLink: CVDisplayLink?
    
    // Python script editor
    var editorWindow: NSWindow?
    var editorTextView: NSTextView?
    var currentScript: String = ""
    
    // Playlist management
    struct VideoEntry {
        let path: String
        let videoName: String
    }
    var videos: [VideoEntry] = []
    var currentVideoIndex: Int = 0

    // UI Elements
    var controlsView: NSView!
    var previousButton: NSButton!
    var nextButton: NSButton!
    var videoLabel: NSTextField!
    var processButton: NSButton!
    var editScriptButton: NSButton!
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Initialize Python processor
        pythonProcessor = PythonFrameProcessor()
        
        // Need at least a video name and video path pair
        guard CommandLine.arguments.count > 2 else {
            print("Usage: vj-player \"Video Name 1\" video1.mp4 \"Video Name 2\" video2.mp4 ...")
            NSApplication.shared.terminate(nil)
            return
        }
        
        // Parse arguments into video entries
        let args = Array(CommandLine.arguments.dropFirst())
        if args.count % 2 != 0 {
            NSApplication.shared.terminate(nil)
            return
        }
        
        // Create video entries from pairs of arguments
        for i in stride(from: 0, to: args.count, by: 2) {
            videos.append(VideoEntry(path: args[i + 1], videoName: args[i]))
        }
        
        // Create the window
        let windowRect = NSRect(x: 0, y: 0, width: 800, height: 650)
        window = NSWindow(
            contentRect: windowRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.level = .floating 
        
        // Create the main container view
        let containerView = NSView(frame: windowRect)
        window.contentView = containerView
        
        // Create the player view
        let playerRect = NSRect(x: 0, y: 50, width: windowRect.width, height: windowRect.height - 50)
        playerView = AVPlayerView(frame: playerRect)
        playerView.autoresizingMask = [.width, .height]
        playerView.controlsStyle = .floating
        playerView.showsFullScreenToggleButton = true
        containerView.addSubview(playerView)
        
        // Create controls view with more space for additional buttons
        let controlsRect = NSRect(x: 0, y: 0, width: windowRect.width, height: 50)
        controlsView = NSView(frame: controlsRect)
        controlsView.autoresizingMask = [.width]
        containerView.addSubview(controlsView)
        
        // Create navigation buttons
        previousButton = NSButton(frame: NSRect(x: 10, y: 10, width: 80, height: 30))
        previousButton.title = "Previous"
        previousButton.bezelStyle = .rounded
        previousButton.target = self
        previousButton.action = #selector(previousVideo)
        controlsView.addSubview(previousButton)
        
        nextButton = NSButton(frame: NSRect(x: 100, y: 10, width: 80, height: 30))
        nextButton.title = "Next"
        nextButton.bezelStyle = .rounded
        nextButton.target = self
        nextButton.action = #selector(nextVideo)
        controlsView.addSubview(nextButton)
        
        // Create process button
        processButton = NSButton(frame: NSRect(x: 190, y: 10, width: 120, height: 30))
        processButton.title = "Enable Processing"
        processButton.bezelStyle = .rounded
        processButton.target = self
        processButton.action = #selector(toggleProcessing)
        controlsView.addSubview(processButton)
        
        // Create edit script button
        editScriptButton = NSButton(frame: NSRect(x: 320, y: 10, width: 100, height: 30))
        editScriptButton.title = "Edit Script"
        editScriptButton.bezelStyle = .rounded
        editScriptButton.target = self
        editScriptButton.action = #selector(openScriptEditor)
        controlsView.addSubview(editScriptButton)
        
        // Create video label
        videoLabel = NSTextField(frame: NSRect(x: 430, y: 15, width: 300, height: 20))
        videoLabel.isEditable = false
        videoLabel.isBordered = false
        videoLabel.backgroundColor = .clear
        videoLabel.font = NSFont.systemFont(ofSize: 14, weight: .bold)
        controlsView.addSubview(videoLabel)
        
        // Setup window
        window.title = "Video Player with Python Processing"
        window.center()
        window.makeKeyAndOrderFront(nil)
        
        // Start playing first video
        playCurrentVideo()
        
        // Create default Python script if none exists
        if !FileManager.default.fileExists(atPath: pythonProcessor.scriptPath.path) {
            createDefaultPythonScript()
        }
        
        // Load the current script
        do {
            currentScript = try String(contentsOf: pythonProcessor.scriptPath, encoding: .utf8)
        } catch {
            print("Error loading script: \(error)")
            currentScript = defaultPythonScript()
        }
        
        // Set up keyboard event monitoring
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            self.handleKeyEvent(event)
            return event
        }
    }
    
    @objc func toggleProcessing() {
        isProcessingEnabled.toggle()
        
        if isProcessingEnabled {
            processButton.title = "Disable Processing"
            setupFrameProcessing()
        } else {
            processButton.title = "Enable Processing"
            tearDownFrameProcessing()
        }
    }
    
    func setupFrameProcessing() {
        guard let playerItem = queuePlayer.currentItem else { return }
        
        // Add video output to player item
        let videoOutput = AVPlayerItemVideoOutput(pixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ])
        playerItem.add(videoOutput)
        
        // Setup display link for synchronized frame capture
        CVDisplayLinkCreateWithActiveCGDisplays(&displayLink)
        
        if let displayLink = displayLink {
            CVDisplayLinkSetOutputCallback(displayLink, { (displayLink, inNow, inOutputTime, flagsIn, flagsOut, displayLinkContext) -> CVReturn in
                let videoPlayerDelegate = Unmanaged<VideoPlayerDelegate>.fromOpaque(displayLinkContext!).takeUnretainedValue()
                videoPlayerDelegate.processCurrentFrame()
                return kCVReturnSuccess
            }, Unmanaged.passUnretained(self).toOpaque())
            
            CVDisplayLinkStart(displayLink)
        }
    }
    
    func tearDownFrameProcessing() {
        if let displayLink = displayLink {
            CVDisplayLinkStop(displayLink)
            self.displayLink = nil
        }
        
        // Remove video output
        queuePlayer.currentItem?.outputs.forEach { output in
            queuePlayer.currentItem?.remove(output)
        }
    }
    
    func processCurrentFrame() {
        guard isProcessingEnabled,
              let playerItem = queuePlayer.currentItem,
              let videoOutput = playerItem.outputs.first as? AVPlayerItemVideoOutput else {
            return
        }
        
        let itemTime = queuePlayer.currentTime()
        
        guard videoOutput.hasNewPixelBuffer(forItemTime: itemTime) else {
            return
        }
        
        guard let pixelBuffer = videoOutput.copyPixelBuffer(forItemTime: itemTime, itemTimeForDisplay: nil) else {
            return
        }
        
        // Process frame with Python
        if let processedBuffer = pythonProcessor.processFrame(pixelBuffer) {
            // Display the processed frame
            DispatchQueue.main.async {
                // Here you would replace or overlay the frame in your player view
                // This is complex and depends on how you want to display the processed frames
                // For simplicity, we're just logging that we processed a frame
                print("Processed frame at time: \(CMTimeGetSeconds(itemTime))")
            }
        }
    }
    
    // Script Editor
    @objc func openScriptEditor() {
        if editorWindow == nil {
            createScriptEditorWindow()
        }
        
        editorWindow?.makeKeyAndOrderFront(nil)
    }
    
    func createScriptEditorWindow() {
        let windowRect = NSRect(x: 0, y: 0, width: 600, height: 400)
        editorWindow = NSWindow(
            contentRect: windowRect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        
        editorWindow?.title = "Python Script Editor"
        
        // Create scroll view for text editor
        let scrollView = NSScrollView(frame: NSRect(x: 0, y: 50, width: windowRect.width, height: windowRect.height - 50))
        scrollView.autoresizingMask = [.width, .height]
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = true
        scrollView.borderType = .noBorder
        
        // Create text view
        let contentSize = scrollView.contentSize
        let textStorage = NSTextStorage()
        let layoutManager = NSLayoutManager()
        textStorage.addLayoutManager(layoutManager)
        let textContainer = NSTextContainer(containerSize: NSSize(width: contentSize.width, height: CGFloat.greatestFiniteMagnitude))
        textContainer.widthTracksTextView = true
        layoutManager.addTextContainer(textContainer)
        
        editorTextView = NSTextView(frame: NSRect(x: 0, y: 0, width: contentSize.width, height: contentSize.height), textContainer: textContainer)
        if let editorTextView = editorTextView {
            editorTextView.autoresizingMask = [.width]
            editorTextView.font = NSFont(name: "Menlo", size: 12)
            editorTextView.isRichText = false
            editorTextView.isEditable = true
            editorTextView.backgroundColor = NSColor(white: 0.95, alpha: 1.0)
            editorTextView.string = currentScript
            
            scrollView.documentView = editorTextView
        }
        
        // Create buttons
        let saveButton = NSButton(frame: NSRect(x: windowRect.width - 180, y: 10, width: 80, height: 30))
        saveButton.title = "Save"
        saveButton.bezelStyle = .rounded
        saveButton.target = self
        saveButton.action = #selector(saveScript)
        
        let cancelButton = NSButton(frame: NSRect(x: windowRect.width - 90, y: 10, width: 80, height: 30))
        cancelButton.title = "Cancel"
        cancelButton.bezelStyle = .rounded
        cancelButton.target = self
        cancelButton.action = #selector(closeScriptEditor)
        
        // Add controls to window
        if let contentView = editorWindow?.contentView {
            contentView.addSubview(scrollView)
            contentView.addSubview(saveButton)
            contentView.addSubview(cancelButton)
        }
        
        editorWindow?.center()
    }
    
    @objc func saveScript() {
        guard let scriptText = editorTextView?.string else { return }
        
        do {
            try scriptText.write(to: pythonProcessor.scriptPath, atomically: true, encoding: .utf8)
            currentScript = scriptText
            
            // Reload the Python script
            pythonProcessor.reloadScript()
            
            closeScriptEditor()
        } catch {
            let alert = NSAlert()
            alert.messageText = "Error Saving Script"
            alert.informativeText = error.localizedDescription
            alert.alertStyle = .warning
            alert.addButton(withTitle: "OK")
            alert.runModal()
        }
    }
    
    @objc func closeScriptEditor() {
        editorWindow?.close()
    }
    
    func createDefaultPythonScript() {
        do {
            try defaultPythonScript().write(to: pythonProcessor.scriptPath, atomically: true, encoding: .utf8)
        } catch {
            print("Error creating default script: \(error)")
        }
    }
    
    func defaultPythonScript() -> String {
        return """
        import numpy as np
        import cv2
        
        def process_frame(frame):
            '''
            Process a video frame.
            
            Args:
                frame: NumPy array representing the frame (BGR format)
                
            Returns:
                Processed frame as NumPy array (BGR format)
            '''
            # Example: Convert to grayscale and then back to color
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        """
    }
    
    func playCurrentVideo() {
        guard currentVideoIndex >= 0 && currentVideoIndex < videos.count else {
            return
        }
        
        // If processing was enabled, disable and re-enable to reset for new video
        let wasProcessingEnabled = isProcessingEnabled
        if wasProcessingEnabled {
            tearDownFrameProcessing()
        }
        
        let videoEntry = videos[currentVideoIndex]
        let videoURL = URL(fileURLWithPath: videoEntry.path)
        
        // Create a new player item
        let playerItem = AVPlayerItem(url: videoURL)
        
        // Create or reuse queue player
        if queuePlayer == nil {
            queuePlayer = AVQueuePlayer()
            playerView.player = queuePlayer
        }
        
        // Remove existing looper if any
        playerLooper?.disableLooping()
        playerLooper = nil
        
        // Create new looper
        playerLooper = AVPlayerLooper(player: queuePlayer, templateItem: playerItem)
        
        // Update window title and video label
        window.title = "Video Player with Python Processing - \(videoURL.lastPathComponent) [\(currentVideoIndex + 1)/\(videos.count)]"
        videoLabel.stringValue = videoEntry.videoName
        
        // Update button states
        previousButton.isEnabled = currentVideoIndex > 0
        nextButton.isEnabled = currentVideoIndex < videos.count - 1
        
        // Re-enable processing if it was enabled
        if wasProcessingEnabled {
            setupFrameProcessing()
        }
        
        queuePlayer.play()
    }
    
    @objc func previousVideo() {
        if currentVideoIndex > 0 {
            currentVideoIndex -= 1
            playCurrentVideo()
        }
    }
    
    @objc func nextVideo() {
        if currentVideoIndex < videos.count - 1 {
            currentVideoIndex += 1
            playCurrentVideo()
        }
    }
    
    func handleKeyEvent(_ event: NSEvent) {
       guard let characters = event.characters else { return }
        
        switch characters {
        case " ":
            // Toggle play/pause
            if queuePlayer.rate == 0 {
                queuePlayer.play()
            } else {
                queuePlayer.pause()
            }
            
        case String(Character(UnicodeScalar(NSLeftArrowFunctionKey)!)):
            // Seek backward 10 seconds
            let currentTime = queuePlayer.currentTime()
            let newTime = CMTimeAdd(currentTime, CMTime(seconds: -10, preferredTimescale: 1))
            queuePlayer.seek(to: newTime)
            
        case String(Character(UnicodeScalar(NSRightArrowFunctionKey)!)):
            // Seek forward 10 seconds
            let currentTime = queuePlayer.currentTime()
            let newTime = CMTimeAdd(currentTime, CMTime(seconds: 10, preferredTimescale: 1))
            queuePlayer.seek(to: newTime)
            
        case "n", "N":
            nextVideo()
            
        case "p", "P":
            previousVideo()
            
        case "e", "E":
            openScriptEditor()
            
        case "f", "F":
            toggleProcessing()
            
        case "q", "Q":
            NSApplication.shared.terminate(nil)
            
        default:
            break
        }
    }
    
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

// Python Frame Processor Class
class PythonFrameProcessor {
    private let python: Python
    private let sys: PythonObject
    private let np: PythonObject
    private let cv2: PythonObject
    private var userModule: PythonObject
    
    let scriptPath: URL
    
    init() {
        // Initialize Python
        python = Python.shared
        sys = python.import("sys")
        
        // Add necessary paths for Python libraries
        let resourcePath = Bundle.main.resourcePath ?? ""
        sys.path.append(resourcePath)
        sys.path.append("\(resourcePath)/python-stdlib")
        sys.path.append("\(resourcePath)/python-packages")
        
        // Import required modules
        np = python.import("numpy")
        cv2 = python.import("cv2")
        
        // Set up script directory
        let fileManager = FileManager.default
        
        // Use the Application Support directory
        let appSupportDir = try! fileManager.url(for: .applicationSupportDirectory,
                                               in: .userDomainMask,
                                               appropriateFor: nil,
                                               create: true)
            .appendingPathComponent("VideoPlayerPython", isDirectory: true)
        
        // Create directory if it doesn't exist
        if !fileManager.fileExists(atPath: appSupportDir.path) {
            try! fileManager.createDirectory(at: appSupportDir, withIntermediateDirectories: true)
        }
        
        // Set script path
        scriptPath = appSupportDir.appendingPathComponent("video_processor.py")
        
        // Import user module (or create if it doesn't exist)
        reloadScript()
    }
    
    func reloadScript() {
        // Make sure the script exists
        if !FileManager.default.fileExists(atPath: scriptPath.path) {
            // Create a basic script if it doesn't exist
            let basicScript = """
            import numpy as np
            import cv2
            
            def process_frame(frame):
                # Default: return the frame unchanged
                return frame
            """
            
            try? basicScript.write(to: scriptPath, atomically: true, encoding: .utf8)
        }
        
        // Add script directory to Python path
        sys.path.append(scriptPath.deletingLastPathComponent().path)
        
        // Try to import the user script
        do {
            // If we've already imported it, reload it
            if userModule != nil {
                let importlib = python.import("importlib")
                userModule = importlib.reload(userModule)
            } else {
                // First time import
                userModule = python.import("video_processor")
            }
        } catch {
            print("Error loading Python script: \(error)")
            // Create a fallback module with a basic function
            let globals = python.globals()
            userModule = globals.get("__builtins__").get("type")("video_processor", python.tuple([]), python.dict([]))
            userModule.process_frame = python.def { (frame: PythonObject) -> PythonObject in
                return frame
            }
        }
    }
    
    func processFrame(_ pixelBuffer: CVPixelBuffer) -> CVPixelBuffer? {
        // Lock the pixel buffer for reading
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        
        // Get dimensions
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer)!
        
        // Convert CVPixelBuffer to numpy array
        let buffer = UnsafeMutableRawPointer(baseAddress)
        let data = np.frombuffer(Python.bytes(buffer.assumingMemoryBound(to: UInt8.self), count: bytesPerRow * height),
                             dtype: np.uint8)
        let frame = data.reshape(height, width, 4)  // BGRA format
        
        // Convert to BGR for OpenCV
        let bgrFrame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        
        // Process the frame with the user's Python function
        let processedFrame: PythonObject
        do {
            processedFrame = userModule.process_frame(bgrFrame)
        } catch {
            print("Error in Python processing: \(error)")
            CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly)
            return nil
        }
        
        // Convert back to BGRA
        let processedBGRA = cv2.cvtColor(processedFrame, cv2.COLOR_BGR2BGRA)
        
        // Create a new pixel buffer
        var newPixelBuffer: CVPixelBuffer?
        let status = CVPixelBufferCreate(kCFAllocatorDefault,
                                       width, height,
                                       kCVPixelFormatType_32BGRA,
                                       [kCVPixelBufferCGImageCompatibilityKey: true,
                                        kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary,
                                       &newPixelBuffer)
        
        guard status == kCVReturnSuccess, let newPixelBuffer = newPixelBuffer else {
            CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly)
            return nil
        }
        
        // Copy processed data to the new pixel buffer
        CVPixelBufferLockBaseAddress(newPixelBuffer, [])
        let newBaseAddress = CVPixelBufferGetBaseAddress(newPixelBuffer)!
        let newBytesPerRow = CVPixelBufferGetBytesPerRow(newPixelBuffer)
        let newBuffer = UnsafeMutableRawPointer(newBaseAddress)
        
        // Get numpy array data bytes
        let npData = Python.bytes(processedBGRA.tobytes())
        let count = npData.__len__()
        
        // Copy the data
        let npDataPtr = npData.data_as(np.ctypeslib.as_ctypes_type(np.dtype("B").char))
        let bytesPointer = UnsafeMutableRawPointer(npDataPtr.__array_interface__["data"][0])
        
        // Copy data carefully, accounting for possible stride differences
        for y in 0..<height {
            let srcRow = bytesPointer!.advanced(by: y * width * 4)
            let destRow = newBuffer.advanced(by: y * newBytesPerRow)
            memcpy(destRow, srcRow, width * 4)
        }
        
        // Unlock buffers
        CVPixelBufferUnlockBaseAddress(newPixelBuffer, [])
        CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly)
        
        return newPixelBuffer
    }
}

// Create and start the application
let delegate = VideoPlayerDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.run()