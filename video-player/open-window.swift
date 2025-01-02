import Cocoa

let workspace = NSWorkspace.shared
let bundleId = "com.skate85.videojungle"
let url = "videojungle://upload"

if let appURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) {
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.arguments = [url]
    
    // Check if app is already running
    let isRunning = NSWorkspace.shared.runningApplications.contains { 
        $0.bundleIdentifier == bundleId 
    }
    
    if isRunning {
        // If running, just open the URL
        if let urlObj = URL(string: url) {
            workspace.open(urlObj, configuration: configuration) { (app, error) in
                if let error = error {
                    print("Error opening URL: \(error)")
                    exit(1)
                }
                exit(0)
            }
        }
    } else {
        // If not running, launch with URL as parameter
        workspace.openApplication(at: appURL, 
                                configuration: configuration) { (app, error) in
            if let error = error {
                print("Error launching app: \(error)")
                exit(1)
            }
            exit(0)
        }
    }
    
    RunLoop.main.run(until: Date(timeIntervalSinceNow: 5))
} else {
    print("Could not find application")
    exit(1)
}