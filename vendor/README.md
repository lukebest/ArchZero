# Optional vendored backends

## pyCircuit (Tier5 RTL)

```bash
# Preferred: setup script (submodule or shallow clone + LLVM 19 + pycc)
bash tools/setup_pycircuit.sh

# Or manually:
git submodule add https://github.com/lukebest/pyCircuit.git vendor/pycircuit
# then build with tools/setup_pycircuit.sh
```

Configure:

```toml
[rtl]
pycircuit_root = "vendor/pycircuit"
pyc_toolchain_root = ".pycircuit_out/toolchain/install"
```

## OpenEvolve (evolution)

```bash
git submodule update --init vendor/openevolve
uv sync --extra openevolve
```

```toml
[evolve]
backend = "openevolve"
```

`archzero evolve` then starts `archzero/llm/shim.py` (OpenAI-compatible
`/v1/chat/completions`) and points OpenEvolve at that URL so every LLM call
goes through the Cursor SDK. Without the submodule, the adapter falls back to
built-in MAP-Elites.
