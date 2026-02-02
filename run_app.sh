#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/.venv"

# 1. Unset potentially conflicting environment variables
# Anaconda and other Qt installations often set these
unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH
unset DYLD_LIBRARY_PATH
unset DYLD_FRAMEWORK_PATH
unset PYTHONPATH
unset QT_API

# 2. Set the correct plugin and framework paths explicitly
PLUGIN_PATH="$VENV_DIR/lib/python3.11/site-packages/PyQt6/Qt6/plugins"
FRAMEWORK_PATH="$VENV_DIR/lib/python3.11/site-packages/PyQt6/Qt6/lib"

export QT_PLUGIN_PATH="$PLUGIN_PATH"
# We set DYLD_FRAMEWORK_PATH to ensure the plugin can find QtGui/QtCore
export DYLD_FRAMEWORK_PATH="$FRAMEWORK_PATH"

# 3. Run using the absolute path to the venv python
# This avoids any alias or PATH confusion
PYTHON_EXEC="$VENV_DIR/bin/python"

echo "Starting MicroPL..."
echo "Using Python: $PYTHON_EXEC"
echo "Plugin Path: $QT_PLUGIN_PATH"
echo "Framework Path: $DYLD_FRAMEWORK_PATH"

"$PYTHON_EXEC" "$SCRIPT_DIR/src/micropl/scripts/run.py"
