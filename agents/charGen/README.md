# charGen Agent

`charGen` creates reusable character packs in the shared library path:

- `library/characters/packs/<pack-id>.json`

## Usage

```bash
python3 main.py charGen --prompt "A trio of cyber detectives" --style cinematic_anime --count 3
```

## Output
- Character pack JSON with reusable metadata for downstream agents.
