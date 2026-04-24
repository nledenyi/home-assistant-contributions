# ha_toyota #282 memray follow-up comment

Posted 2026-04-24 to [pytoyoda/ha_toyota#282](https://github.com/pytoyoda/ha_toyota/issues/282#issuecomment-4311840049) in reply to @arhimidis64's offer to run more tests, after their report that memory still ramped even with PR #283 applied.

Context:

- Our own harness + live HA runs were flat post-fix (zero tracemalloc growth, -226 net gc objects over 2h). We could not reproduce the residual ramp.
- Meant the remaining leak is environment-specific to their setup (response shape, entity mix, or another integration interacting).
- A memray allocation trace from their actual process is the only way to see what's retained.
- Also folded in a one-line ack to @Paja-git for their `dt_util.now()` review on our branch.

The comment validates that `memray` (not `py-spy`) is the right tool on HAOS / Alpine / musllinux. See [`../../references/memray-on-haos.md`](../../references/memray-on-haos.md) for the distilled methodology.

---

Thanks for offering to help @arhimidis64. Quick context before the instructions:

- I could not reproduce the residual ramp you describe. Tried a controlled
  test harness (replaying real Toyota response bodies, 2-hour runs) and
  also my own live HA instance with the patched branch - both run flat
  (zero tracemalloc growth, -226 net gc objects over 2h in the harness).
  That means the remaining leak is environment-specific to your setup:
  a different response shape, a different entity mix, or an interaction
  with another integration. A memray trace from your actual process is
  the only way for us to see what's retained.

- And thanks @Paja-git for the dt_util.now() review on our branch - applied.

Memray attaches to a running python process, records every allocation for a
time window, and produces a flamegraph of what is held.

Commands (tested on HAOS with Python 3.14, should work on Container and
Supervised installs too):

    # Step 0 (HAOS only): you need a host shell with the docker CLI.
    #  - Proxmox / direct console: if you see the `ha >` prompt, type `login`
    #    there to drop into the host shell.
    #  - SSH: you need the community "Advanced SSH & Web Terminal" add-on (by frenck)
    #    with "Protection Mode" disabled in its config. The official "SSH
    #    server" core add-on will NOT work - it has no docker command.
    # Container and Supervised installs already have host shell + docker, so
    # skip this step.
    login

    # Step 1: get into the HA Core container
    docker exec -it homeassistant /bin/sh

    # Step 2: install memray (py-spy is broken on musllinux, do not bother)
    pip install memray

    # Step 3: find HA's python PID inside the container
    HA_PID=$(pidof python3)
    echo "HA PID: $HA_PID"

    # Step 4: attach and record for 20 min. Start this RIGHT BEFORE you see
    # RSS start to climb; the window needs to cover at least 2-3 Toyota
    # coordinator refreshes (6 min each by default) to catch the leak source.
    memray attach --duration 1200 --output /tmp/ha-leak.bin $HA_PID

    # Step 5: render the flamegraph from the recording
    memray flamegraph --force -o /tmp/ha-leak.html /tmp/ha-leak.bin

    # Step 6: also generate the summary stats
    memray stats /tmp/ha-leak.bin > /tmp/ha-leak-stats.txt

    # Step 7: exit the container
    exit

    # Step 8: copy the artefacts off (paths depend on your install):
    # - HAOS via "Advanced SSH & Web Terminal" add-on: scp from there, or just
    #   cat the html to your clipboard; it is self-contained
    # - Container install: docker cp homeassistant:/tmp/ha-leak.html .

Artefacts to share (either attach to a reply here or upload to a gist):

- /tmp/ha-leak.html (the flamegraph, self-contained HTML, safe to share)
- /tmp/ha-leak-stats.txt (top allocation sites)

The flamegraph is generated from anonymised allocation traces. No VIN, no
email, no tokens appear in it. If you want to double-check, open the HTML in
a browser first - it is just code paths and byte counts.

What I am looking for: the "Top 5 largest allocating locations (by size)"
section of the stats output, and the wide bars at the top of the flamegraph.
If pytoyoda or ha_toyota code paths dominate, we have a concrete target. If
it is a dependency (hishel, httpx, pydantic) or another HA component, that
points somewhere very different.

If you would rather not post the artefacts publicly, ping me and I can share
an email address to send them to.
