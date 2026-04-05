#!/bin/bash
# download_comcentre.sh
# A script to download the ComCentre repository

# Set the target directory (optional)
TARGET_DIR="$HOME/ComCentre"

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
    echo "Cloning ComCentre into $TARGET_DIR..."
    git clone https://github.com/CursedPrograms/ComCentre.git "$TARGET_DIR"
fi

echo "Done!"
