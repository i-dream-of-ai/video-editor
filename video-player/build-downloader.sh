set -e

# App name and bundle structure
APP_NAME="VJ Uploader"
BUNDLE_NAME="$APP_NAME.app"
CONTENTS_DIR="$BUNDLE_NAME/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
ICONSET_NAME="AppIcon.iconset"

# Create bundle structure
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp Icon.svg "$RESOURCES_DIR/"
cp config.json "$RESOURCES_DIR/"

# Compile the application
swiftc downloader.swift -o "$MACOS_DIR/$APP_NAME"

# Copy Info.plist
cp Info.plist "$CONTENTS_DIR/"

# Create iconset directory
mkdir -p "$ICONSET_NAME"

# Generate different icon sizes from SVG
for size in 16 32 64 128 256 512; do
    # Generate regular size
    magick convert -background none -resize ${size}x${size} Icon.svg "$ICONSET_NAME/icon_${size}x${size}.png"
    
    # Generate @2x size
    if [ $size -lt 512 ]; then
        magick convert -background none -resize $((size*2))x$((size*2)) Icon.svg "$ICONSET_NAME/icon_${size}x${size}@2x.png"
    fi
done

# Convert iconset to icns
iconutil -c icns -o "$RESOURCES_DIR/AppIcon.icns" "$ICONSET_NAME"

# Clean up iconset directory
rm -rf "$ICONSET_NAME"

# Set executable permissions
chmod +x "$MACOS_DIR/$APP_NAME"

echo "Build complete: $BUNDLE_NAME"