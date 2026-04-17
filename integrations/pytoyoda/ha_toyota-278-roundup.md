Quick round-up:

@denhaeseb55 @Paja-git Thanks for confirming the fix works. @denhaeseb55's clarification is the most useful: **the pip install must target the same Python environment Home Assistant Core itself uses**. The SSH & Web Terminal add-on ships its own Python (usually 3.12); HA Core runs on Python 3.14 with a separate `site-packages`.

@arhimidis64 Your output confirms the trap. `pip show pytoyoda` reports `Location: /usr/lib/python3.12/site-packages` (the add-on's Python), but HA Core's traceback still loads pytoyoda from `/usr/local/lib/python3.14/site-packages/`. You installed into the wrong environment; HA kept the old version.

### How to reach HA Core's Python depends on your install type

| Install type | How to reach HA Core's Python |
| --- | --- |
| HA OS | Install the SSH & Web Terminal add-on, disable "Protected mode" in its Configuration tab, then `docker exec -it homeassistant /bin/bash` |
| HA Container / Supervised | SSH to the Docker host, then `docker exec -it homeassistant /bin/bash` |

(If you're on bare HA Core in a Python venv, activate the venv and `pip install` directly; you're not going through a container.)

Inside, `which python3` should point at `/usr/local/bin/python3` (reports 3.14 on current HA). Then the workaround from my earlier comment: pip install the fork branch with `--no-deps`, exit, and restart HA (`ha core restart`, or `docker restart homeassistant` depending on install type).

If you're not comfortable with SSH at all, the cleanest path is to wait. PR pytoyoda/pytoyoda#249 has green CI and is pending a human maintainer review. I'll post here when it merges and a pytoyoda release ships.
