#!/bin/bash
# download_friday.sh
# A script to download the DREAM repository

# Set the target directory (optional)
TARGET_DIR="$HOME/DREAM"

# Check if git is installed
if ! command -v git &> /dev/null
then
    echo "Git is not installed. Please install git first."
    exit 1
fi

# Clone the repository
if [ -d "$TARGET_DIR" ]; then
    echo "Directory $TARGET_DIR already exists. Pulling latest changes..."
    cd "$TARGET_DIR"
    git pull
else
    echo "Cloning DREAM into $TARGET_DIR..."
    git clone https://github.com/CursedPrograms/DREAM.git "$TARGET_DIR"
fi

echo "Done!"
