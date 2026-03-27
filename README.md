# Okiner

Okiner is a Python based Discord bot project intended for server member interaction, community engagement, and roleplay-focused features.

The repository is currently setup  with the core structure needed to start development, including dependency management, environment configuration, and a minimal bot entrypoint.

## Setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Add your bot token to `.env`.

### Debian / Debian-based Linux

Install Python, virtual environment support, and `pip`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your bot token to `.env`.

## Run

### Windows (PowerShell)

```powershell
python main.py
```

### Debian / Debian-based Linux

```bash
python3 main.py
```
