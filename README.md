# ModelDocker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.6+-green.svg)](https://doc.qt.io/qtforpython-6/)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](#quick-start)

> A Windows desktop AI chat client for OpenRouter — manage conversations, browse models, and work with streaming chat completions in a clean, distraction-free interface.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Building from Source](#building-from-source)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

ModelDocker is a native Windows desktop application that provides a polished interface for chatting with AI models hosted on [OpenRouter](https://openrouter.ai). It handles streaming completions, multi-session conversation management, model browsing with capability hints, and theme customization — all stored locally with no cloud dependency.

![ModelDocker banner](Modeldocker.jpg)

## Key Features

- **OpenRouter desktop client** with streaming chat completions
- **Model browser** with search, capability hints, pricing, and context information
- **Multi-session history** — conversations can be reopened, renamed, or deleted
- **Power-user composer** with model filters, temperature control, attachments, image actions, and video actions where supported
- **Dark and light themes** with settings saved locally
- **Local conversation storage** under `%USERPROFILE%\.modeldocker\`
- **Role and memory management** for persistent context across sessions

## Quick Start

### Option 1: Download the Executable

1. Download **[ModelDocker.exe](dist/ModelDocker.exe)**.
2. Double-click the executable.
3. Paste your [OpenRouter API key](https://openrouter.ai/keys) when prompted.
4. Pick a model and start chatting.

### Option 2: Run from Source

```powershell
git clone https://github.com/Skynet-Pro-Plus/modeldocker.git
cd modeldocker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Usage

1. Launch ModelDocker.
2. Enter your OpenRouter API key (stored securely via `keyring`).
3. Browse available models using the model browser — filter by capabilities and pricing.
4. Start a new conversation, choose a model, and send a message.
5. Use the session panel to manage conversation history.

## Project Structure

```
modeldocker/
├── main.py                 # Application entry point
├── launch.pyw              # Windowed launcher
├── openrouter_client.py    # OpenRouter API client
├── memory_store.py         # Conversation memory storage
├── role_store.py           # Role/prompt template management
├── requirements.txt        # Runtime dependencies
├── requirements-build.txt  # Build dependencies (PyInstaller)
├── ModelDocker.spec        # PyInstaller spec file
├── build_onefile.ps1       # Build script for single-file EXE
├── resources/              # Icons, fonts, and static assets
└── dist/                   # Built executables
```

## Tech Stack

- **Language:** Python 3.10+
- **GUI Framework:** PySide6 (Qt 6)
- **HTTP Client:** httpx
- **Credential Storage:** keyring
- **Packaging:** PyInstaller (single-file Windows EXE)

## Building from Source

```powershell
# Install build dependencies
pip install -r requirements-build.txt

# Build single-file executable
.\build_onefile.ps1

# Output
# dist/ModelDocker.exe
```

## Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Commit your changes (`git commit -m 'Add your feature'`).
4. Push to the branch (`git push origin feature/your-feature`).
5. Open a Pull Request.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for additional guidelines.

## License

This project is licensed under the [MIT License](LICENSE).
