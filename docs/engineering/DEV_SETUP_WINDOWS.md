# Dev setup on Windows (8 GB RAM, no GPU)

Target machine: i5-8365U, 8 GB RAM, Intel UHD 620, Windows 64-bit.

## 1. Install (all free)

- Python 3.11 (python.org, tick "Add to PATH")
- Git for Windows
- Node.js LTS
- VS Code (or PyCharm Community)

## 2. Clone and install

```powershell
git clone https://github.com/UnderAetheris/Aethens.git
cd Aethens
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
cd shell; npm install; cd ..
```

## 3. Verify

```powershell
ruff check src/ tests/ scripts/
python -m pytest tests/ -q
python scripts/check_architecture_integrity.py --check
```

## 4. Run

```powershell
# terminal 1
python -m uvicorn aetheris.api.app:app --reload
# terminal 2
cd shell; npm run dev
```

## 5. Models (free)

The laptop is the body, cloud free tiers are the brain (spec F01, F13). Get free keys from Google AI Studio (Gemini), Groq, and OpenRouter (`:free` models). Never commit keys; the vault (F20) will store them. Until then, use environment variables in your shell session only.

Optional local model for tiny jobs: Ollama with a 1.5B to 3B model. Not the main brain.

## 6. Keep it light

- Close browsers with many tabs while running eval suites
- Skip Docker Desktop (too heavy for 8 GB)
- Optional WSL2: create `%UserProfile%\.wslconfig` with `[wsl2]` `memory=3GB` `processors=2`
