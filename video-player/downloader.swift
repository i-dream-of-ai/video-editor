import AppKit
import Cocoa
import Foundation

class Config {
    static func getAPIKey() -> String? {
        if let configPath = Bundle.main.path(forResource: "config", ofType: "json"),
           let configData = try? Data(contentsOf: URL(fileURLWithPath: configPath)),
           let json = try? JSONSerialization.jsonObject(with: configData) as? [String: String] {
            return json["api_key"]
        }
        return nil
    }
}

struct VideoUpload: Codable {
    let name: String
    let filename: String
    let upload_method: String
}

enum UploadError: Error {
    case invalidURL
    case networkError(Error)
    case invalidResponse
    case serverError(Int)
    case noData
}

class VideoUploader {
    private let apiKey: String
    private let baseURL = "https://api.video-jungle.com/video-file"
    
    init(apiKey: String) {
        self.apiKey = apiKey
    }
    
    func uploadVideo(name: String, youtubeURL: String) async throws -> Data {
        guard let url = URL(string: baseURL) else {
            throw UploadError.invalidURL
        }
        
        // Prepare the upload data
        let uploadData = VideoUpload(
            name: name,
            filename: youtubeURL,
            upload_method: "url"
        )
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        
        // Encode the JSON data
        request.httpBody = try JSONEncoder().encode(uploadData)
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse else {
                throw UploadError.invalidResponse
            }
            
            switch httpResponse.statusCode {
            case 200...299:
                return data
            default:
                throw UploadError.serverError(httpResponse.statusCode)
            }
        } catch let error as UploadError {
            throw error
        } catch {
            throw UploadError.networkError(error)
        }
    }
}

class CustomTextField: NSTextField {
    
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.modifierFlags.contains(.command) {
            switch event.charactersIgnoringModifiers {
            case "v":
                if NSApp.sendAction(#selector(NSText.paste(_:)), to: nil, from: self) {
                    return true
                }
            case "c":
                if NSApp.sendAction(#selector(NSText.copy(_:)), to: nil, from: self) {
                    return true
                }
            case "x":
                if NSApp.sendAction(#selector(NSText.cut(_:)), to: nil, from: self) {
                    return true
                }
            case "a":
                if NSApp.sendAction(#selector(NSText.selectAll(_:)), to: nil, from: self) {
                    return true
                }
            default:
                break
            }
        }
        return super.performKeyEquivalent(with: event)
    }
}

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var statusItem: NSStatusItem!
    var uploadWindow: NSWindow?
    let uploadManager = UploadManager()
    
    func applicationDidFinishLaunching(_ notification: Notification) {
        setupStatusItem()
        // Register for Apple Events
        NSAppleEventManager.shared().setEventHandler(
            self,
            andSelector: #selector(handleURLEvent(_:withReplyEvent:)),
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL)
        )
    }
    
    @objc func handleURLEvent(_ event: NSAppleEventDescriptor, withReplyEvent: NSAppleEventDescriptor) {
        showUploadWindow()
    }

    func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        
        if let button = statusItem.button {
            // Try bundle path first
            let bundlePath = Bundle.main.path(forResource: "Icon", ofType: "svg")
            // Fall back to local path if bundle path fails
            let localPath = "./Icon.svg"
            
            let finalPath = bundlePath ?? localPath
            
            if let svgData = try? Data(contentsOf: URL(fileURLWithPath: finalPath)),
            let svgImage = NSImage(data: svgData) {
                button.image = svgImage
                button.image?.isTemplate = true
            }
        }
        
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Upload File or URL...", action: #selector(showUploadWindow), keyEquivalent: "u"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        
        statusItem.menu = menu
    }
    
    @objc func showUploadWindow() {
        if let window = uploadWindow {
            window.level = .floating
            window.orderFrontRegardless()
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 400, height: 300),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        
        window.title = "Upload File or URL"
        window.level = .floating
        window.center()
        window.delegate = self
        window.isReleasedWhenClosed = false
        
        let viewController = UploaderViewController()
        window.contentViewController = viewController
        
        window.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)
        
        uploadWindow = window
    }
    
    // Window delegate method to handle window closing
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)  // Hide the window
        return false  // Prevent the window from being destroyed
    }
}

class UploaderViewController: NSViewController, NSTextFieldDelegate {
    private let uploadManager: UploadManager = {
        guard let apiKey = Config.getAPIKey() else {
            fatalError("API key not found in config.json")
        }
        return UploadManager(apiKey: apiKey)
    }()

    override func loadView() {
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 400, height: 300))

        // URL Input Field
        let urlField = CustomTextField(frame: NSRect(x: 20, y: 250, width: 360, height: 24))
        urlField.placeholderString = "Enter URL to upload"
        urlField.target = self
        urlField.action = #selector(handleURLInput(_:))
        urlField.isEditable = true
        urlField.isSelectable = true
        urlField.usesSingleLineMode = true
        
        container.addSubview(urlField)
        container.addSubview(urlField)

        // Drop Zone
        let dropZone = DropZoneView(frame: NSRect(x: 20, y: 50, width: 360, height: 180))
        dropZone.uploadManager = uploadManager
        container.addSubview(dropZone)
        
        // Status Label
        let statusLabel = NSTextField(frame: NSRect(x: 20, y: 20, width: 360, height: 24))
        statusLabel.isEditable = false
        statusLabel.isBezeled = false
        statusLabel.drawsBackground = false
        statusLabel.stringValue = "Drag and drop files here or enter a URL above"
        container.addSubview(statusLabel)
        
        self.view = container
    }
    
    @objc func handleURLInput(_ sender: NSTextField) {
        guard let urlString = sender.stringValue.nilIfEmpty,
              let url = URL(string: urlString) else {
            showAlert(message: "Invalid URL")
            return
        }
        
        uploadManager.uploadURL(url) { result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self.showAlert(message: "URL uploaded successfully")
                case .failure(let error):
                    self.showAlert(message: "Upload failed: \(error.localizedDescription)")
                }
            }
        }
    }
    
    func showAlert(message: String) {
        let alert = NSAlert()
        alert.messageText = message
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
    // MARK: - NSTextDelegate Methods
    func textDidChange(_ notification: Notification) {
        // Handle text changes if needed
    }
    
    func textDidEndEditing(_ notification: Notification) {
        // Handle when editing ends if needed
    }
}

class DropZoneView: NSView {
    var uploadManager: UploadManager?
    private let dropLabel = NSTextField()
    
    var isReceivingDrag: Bool = false {
        didSet {
            needsDisplay = true
            updateDropLabel()
        }
    }
    
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        setupView()
    }
    
    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupView()
    }
    
    private func setupView() {
        registerForDraggedTypes([.fileURL])
        wantsLayer = true
        layer?.cornerRadius = 10
        
        // Setup drop label
        dropLabel.isEditable = false
        dropLabel.isBezeled = false
        dropLabel.drawsBackground = false
        dropLabel.alignment = .center
        dropLabel.font = NSFont.systemFont(ofSize: 16, weight: .medium)
        dropLabel.stringValue = "Drop files here to upload"
        dropLabel.textColor = .secondaryLabelColor
        addSubview(dropLabel)
    }
    
    override func layout() {
        super.layout()
        dropLabel.frame = bounds
    }
    
    private func updateDropLabel() {
        dropLabel.textColor = isReceivingDrag ? .systemBlue : .secondaryLabelColor
        
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            dropLabel.animator().alphaValue = isReceivingDrag ? 1.0 : 0.6
        }
    }
    
    override func draw(_ dirtyRect: NSRect) {
        let bounds = self.bounds
        
        // Background
        if isReceivingDrag {
            NSColor(calibratedWhite: 0.95, alpha: 1.0).setFill()
        } else {
            NSColor(calibratedWhite: 0.98, alpha: 1.0).setFill()
        }
        
        let path = NSBezierPath(roundedRect: bounds, xRadius: 10, yRadius: 10)
        path.fill()
        
        // Border
        if isReceivingDrag {
            NSColor.systemBlue.setStroke()
        } else {
            NSColor.separatorColor.setStroke()
        }
        
        path.lineWidth = 2
        path.stroke()
    }
    
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        isReceivingDrag = true
        return .copy
    }
    
    override func draggingExited(_ sender: NSDraggingInfo?) {
        isReceivingDrag = false
    }
    
    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        return true
    }
    
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        isReceivingDrag = false
        
        guard let draggedFileURL = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: nil)?.first as? URL else {
            return false
        }
        
        uploadManager?.uploadFile(draggedFileURL) { result in
            DispatchQueue.main.async {
                let alert = NSAlert()
                switch result {
                case .success:
                    alert.messageText = "File uploaded successfully"
                case .failure(let error):
                    alert.messageText = "Upload failed: \(error.localizedDescription)"
                }
                alert.alertStyle = .informational
                alert.addButton(withTitle: "OK")
                alert.runModal()
            }
        }
        
        return true
    }
}

class UploadManager {
    private let apiKey: String
    private let baseURL = "https://api.video-jungle.com/video-file"

    init(apiKey: String = "") { // Replace with your actual API key
        self.apiKey = apiKey
    }

    func uploadFile(_ fileURL: URL, completion: @escaping (Result<Void, Error>) -> Void) {
        // Implement your file upload logic here
        // This is a placeholder implementation
        DispatchQueue.global().async {
            // Simulating network delay
            Thread.sleep(forTimeInterval: 1.0)
            completion(.success(()))
        }
    }
    
    func uploadURL(_ url: URL, completion: @escaping (Result<Void, Error>) -> Void) {
        // Implement your URL upload logic here
        // This is a placeholder implementation
        DispatchQueue.global().async {
            // Simulating network delay
            Thread.sleep(forTimeInterval: 1.0)
            completion(.success(()))
        }
    }
}

extension String {
    var nilIfEmpty: String? {
        self.isEmpty ? nil : self
    }
}

// Main entry point
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()