# Podcasting Tool

The podcasting tool is designed to run in an isolated virtual environment (`.venv`) to ensure dependencies like `google-generativeai`, `Pillow`, and `google-cloud-texttospeech` do not conflict with system packages.

## Setup

1. **Create the virtual environment**:
   ```bash
   python3 -m venv .venv
   ```

2. **Activate and install dependencies**:
   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the project root with the following:
   ```
   GEMINI_API_KEY="your_api_key_here"
   GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/gcp/service-account-key.json" # Required for Google Cloud TTS (Optional, falls back to espeak)
   ```

## Running the tool

You can run the pipeline using the base `main.py` command, which is programmed to automatically use `.venv/bin/python3` if it exists:

```bash
python3 main.py podcasting --prompt "Your prompt here" --thinking minimal
```

Alternatively, you can run the test script which also utilizes the virtual environment automatically:

```bash
./test_podcasting.py
```
