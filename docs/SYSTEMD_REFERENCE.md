KILL IT
sudo systemctl kill -s SIGKILL spider-robot


# Understanding systemd — Plain-English Reference

This doc explains what systemd is, what our `spider-robot` service actually
does, and the commands you'll use to control it day-to-day. Written for
future-us, assuming zero prior systemd knowledge.

---

## What is systemd?

Every Linux system needs something that starts up the moment the machine
boots, and whose job is to babysit all the other programs — starting them,
watching them, restarting them if they crash, and shutting them down
cleanly when needed.

On the Pi (and most modern Linux systems), that babysitter is called
**systemd**. It's the very first thing that runs when the Pi boots, and it
stays running the whole time, quietly managing everything else.

## What's a "service"?

A service is systemd's word for "a program I'm supposed to watch over."
You tell systemd about a service by writing a small text file (ours is
`spider-robot.service`) that says, in effect:

> "Here's a program called `spider-robot`. To start it, run this exact
> command. If it ever crashes, start it again automatically. Don't start
> it until the network's actually working, since it needs that to serve
> requests."

Once that file is registered with systemd, the relay server stops being
"a script I have to remember to run by hand" and becomes a permanent
resident of the Pi that systemd is responsible for. Before this, if an SSH
session died, the server could die or get orphaned along with it. Now
it's systemd's job to keep it alive — not the SSH session's.

## Where the pieces live

```
/home/spider/spider-robot.service     ← where it lands after scp (temporary)
/etc/systemd/system/spider-robot.service  ← where systemd actually reads it from
```

Copying it from your home folder into `/etc/systemd/system/` is what
"registers" it — that's the folder systemd watches for service definitions.

## The commands, in plain English

| Command | What it actually means |
|---|---|
| `sudo systemctl start spider-robot` | "Start watching over my robot server right now." |
| `sudo systemctl stop spider-robot` | "Stop it, cleanly, and stop watching it." Replaces the old grep-and-kill dance — systemd always knows exactly which process it started. |
| `sudo systemctl restart spider-robot` | "Stop it, then immediately start it again." You'll use this constantly after pushing new code. |
| `sudo systemctl status spider-robot` | "Is it running right now? Has it crashed recently? Give me a quick summary." |
| `sudo systemctl enable spider-robot` | "Remember this service forever — start it automatically on every future boot, even if I never touch it again." |
| `sudo systemctl disable spider-robot` | Undo the above — stop auto-starting it on boot (doesn't stop it if it's currently running). |
| `sudo systemctl daemon-reload` | "I changed the .service file itself — re-read it." Needed any time you edit the file in `/etc/systemd/system/`. |

## What's "journaling" / `journalctl`?

Whenever a systemd service prints anything — errors, normal output, crash
messages — systemd quietly saves all of it into one central, organized
log called **the journal**. It covers every service on the system, not
just ours.

```bash
sudo journalctl -u spider-robot -f
```

- `-u spider-robot` → only show lines belonging to our service (there are
  many other services' logs mixed into the same journal)
- `-f` → "follow" — keep watching and show new lines live, like a live
  feed rather than a static file

`Ctrl+C` on this command only stops *watching* the log — it does **not**
stop the service, since the log-watcher isn't the same thing as the
service itself.

Useful variants:
```bash
sudo journalctl -u spider-robot           # full history, not just live
sudo journalctl -u spider-robot --since "10 min ago"
sudo journalctl -u spider-robot -n 50     # last 50 lines only
```

## The one-line summary

Before: "running the robot server" meant personally opening a terminal,
typing a command, and keeping that window alive the whole time — fragile,
tied to the SSH connection.

After: the robot server is a permanent, self-healing background resident
of the Pi. It starts itself on boot, restarts itself if it crashes, and
gives us a clean on/off switch plus a readable log — no terminal
babysitting required.

## Our deploy loop, now

1. Edit code locally.
2. `scp` the changed file(s) to the Pi.
3. `sudo systemctl restart spider-robot`
4. `sudo journalctl -u spider-robot -f` to confirm it came back up clean.

(This whole loop is exactly what `deploy.py` will eventually automate.)
