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
git clone https://github.com/lukebest/openevolve.git vendor/openevolve
```

```toml
[evolve]
backend = "openevolve"
```

Without OpenEvolve, `archzero evolve` uses built-in MAP-Elites. The shim at
`archzero/llm/shim.py` forwards OE traffic to the Cursor SDK when OE is present.
