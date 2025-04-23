import os
import sys

# Set DaVinci Resolve environment variables
os.environ["RESOLVE_SCRIPT_API"] = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
os.environ["RESOLVE_SCRIPT_LIB"] = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
)

# Add Resolve's Python modules to the path
script_module_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
if script_module_path not in sys.path:
    sys.path.append(script_module_path)

# Now import DaVinciResolveScript
try:
    import DaVinciResolveScript as dvr_script
except ImportError as e:
    print(f"Error importing DaVinciResolveScript: {e}")
    print("Make sure DaVinci Resolve is installed correctly.")
    # Re-raise the exception or set dvr_script to None as a fallback
    dvr_script = None


# Function to get a Resolve instance (optional helper)
def get_resolve_instance():
    """
    Get a handle to the currently running Resolve application.
    Returns None if Resolve is not running or there's an error.
    """
    if dvr_script is None:
        return None

    try:
        resolve = dvr_script.scriptapp("Resolve")
        return resolve
    except Exception as e:
        print(f"Error connecting to Resolve: {e}")
        return None
