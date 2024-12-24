import Cocoa

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
            let svgPath = "./Icon.svg"
            if let svgData = try? Data(contentsOf: URL(fileURLWithPath: svgPath)),
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

class UploaderViewController: NSViewController {
    private let uploadManager = UploadManager()
    
    override func loadView() {
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 400, height: 300))
        
        // URL Input Field
        let urlField = NSTextField(frame: NSRect(x: 20, y: 250, width: 360, height: 24))
        urlField.placeholderString = "Enter URL to upload"
        urlField.target = self
        urlField.action = #selector(handleURLInput(_:))
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