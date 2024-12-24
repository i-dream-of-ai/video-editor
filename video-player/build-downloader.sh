#!/bin/bash

# Exit on error
set -e

# App name and bundle structure
APP_NAME="VJ Uploader"
BUNDLE_NAME="$APP_NAME.app"
CONTENTS_DIR="$BUNDLE_NAME/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Create bundle structure
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

# Compile the application
swiftc downloader.swift -o "$MACOS_DIR/$APP_NAME"

# Copy Info.plist
cp Info.plist "$CONTENTS_DIR/"

# Convert and copy icon
# Note: You'll need ImageMagick installed for this
magick convert -background none -resize 512x512 icon2.svg "$RESOURCES_DIR/AppIcon.icns"

# Set executable permissions
chmod +x "$MACOS_DIR/$APP_NAME"

echo "Build complete: $BUNDLE_NAME"