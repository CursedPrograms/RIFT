#!/bin/bash
#!/bin/bash

echo "🔧 Setting execute permissions..."

FILES=(
    "install_requirements.sh"
    "freeze_requirements.sh"
    "setup.sh"
    "run.sh"
    "launch.sh"
    "run_server.sh"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        chmod +x "$file"
        echo "✔ $file"
    else
        echo "⚠ $file not found"
    fi
done

echo "✅ Done!"

