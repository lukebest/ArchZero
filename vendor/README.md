# Optional vendored backends

Place a checkout of [openevolve](https://github.com/lukebest/openevolve) here as `vendor/openevolve` to enable the OpenEvolve evolution backend:

```bash
git clone https://github.com/lukebest/openevolve.git vendor/openevolve
```

Then set in `archzero.toml`:

```toml
[evolve]
backend = "openevolve"
```

Without this directory, `archzero evolve` uses the built-in MAP-Elites implementation. The OpenAI-compatible shim at `archzero/llm/shim.py` still forwards OE traffic to the Cursor SDK when OE is present.
