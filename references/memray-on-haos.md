# memray on HAOS

Running [memray](https://github.com/bloomberg/memray) against a live Home Assistant Core process on HAOS to get an allocation flamegraph. The Python profiler of choice for this platform because py-spy is broken on Alpine/musllinux.

## Why memray, not py-spy

py-spy's bundled libunwind is glibc-linked. The HA Core container runs on Alpine Linux with musl libc. py-spy's wheel fails to load its unwinder even after `apk add libunwind`, because the wheel expects specific-hashed `.so` names that Alpine's package doesn't provide.

memray works cleanly on Alpine with CPython 3.14 out of the box.

## Prerequisites on HAOS

You need a **host shell** on the HAOS box with the `docker` CLI available. Two routes:

1. **Console (Proxmox VGA, IPMI, direct monitor)**: escape the supervisor `ha >` CLI by typing `login`. That drops you to a root shell on the HAOS host.
2. **Over the network**: install the community **"Advanced SSH & Web Terminal"** add-on (by frenck) and set **Protection Mode: off** in its config. The official "SSH server" core add-on does NOT work — it chroots you into a sandbox with no `docker` command.

Once on the HAOS host, `docker exec -it homeassistant sh` gets you inside HA Core's container.

## Capture recipe

```sh
# inside the homeassistant container
pip install memray
HA_PID=$(pidof python3)

# attach with a fixed window (preferred, self-terminates cleanly)
memray attach --duration 1200 --output /tmp/ha-leak.bin $HA_PID

# OR attach without duration (indefinite) - stop it later with:
memray detach $HA_PID
```

Duration guidance: **at least 15 min (900 s)** to cover 2+ polling cycles of integrations that refresh every 6 min. 20-30 min is ideal for leak-hunting.

## Generate reports

```sh
memray flamegraph --force -o /tmp/ha-leak.html /tmp/ha-leak.bin
memray stats /tmp/ha-leak.bin > /tmp/ha-leak-stats.txt
```

The flamegraph is a self-contained HTML file, safe to share publicly: only code paths and byte counts, no user data, no tokens.

Copy it off the host with `docker cp homeassistant:/tmp/ha-leak.html .`.

## Critical gotcha: `memray detach`, not `--stop`

If you attach **without** `--duration`, you cannot stop the capture with a flag like `memray attach --stop <PID>` — the `attach` subcommand has no such flag. The stop mechanism is a **separate top-level subcommand**:

```sh
memray detach <HA_PID>
```

It writes out the final `.bin` and detaches the tracker cleanly. Do NOT kill the HA process or the memray CLI directly — you end up with a truncated bin.

## Cost

`pip install memray` inside HA's container pulls in `textual`, `rich`, `jinja2`, etc. Adds ~20 MB. Fine for a one-off; lost on container rebuild. For repeated use, bake it into a custom image.

## Reading the output

- **`memray stats` "Top 5 largest allocating locations"** — file:line of the biggest allocators.
- **Wide bars at the top of the flamegraph** — the current-alive allocation surface.
- If your custom integration dominates → concrete fix target.
- If a dependency dominates (httpx, pydantic, hishel) → the leak is upstream; fix belongs in that project.
- If a core HA component dominates → integration-agnostic bug; file a core issue.

## When to use this vs [`../integrations/pytoyoda/memory-leak-fix.md`](../integrations/pytoyoda/memory-leak-fix.md)'s RSS harness

- Use the **RSS harness** when you need to prove whether a leak exists and its rate (MB/hour). Long-running (4+ hours), cheap to run, integration-agnostic.
- Use **memray** when the harness confirms a leak and you need file:line resolution for the fix. 15-30 min window, one-shot, needs host shell access.

The two are complements: RSS shows *that* it leaks; memray shows *where*.
