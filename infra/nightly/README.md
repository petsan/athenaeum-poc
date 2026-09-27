# Athenaeum's nightly evaluation (batch 12, phase BA)

LXC 104 runs Athenaeum's full release evaluation 15 minutes after boot and every day at 02:30 (owner decision D19). It keeps the newest 90 runs, measures the fault matrix, rebuilds the dashboard, and publishes it to the LXC 250 report host at `http://192.168.0.104/athenaeum/` (D16).

| File | Where it runs | What it does |
|---|---|---|
| `athenaeum-nightly.sh` | LXC 104 | Evaluation into `evals/runs/<UTC stamp>/`, pruning to 90 runs, the fault matrix and dashboard (`evals/out/dashboard/`), then publishing. A failing verdict is still kept and published; only a missing results file (a broken harness) stops the run. |
| `athenaeum-nightly.service` / `.timer` | LXC 104 | A oneshot under the 80% cap (`CPUQuota=160%` of 2 cores, `MemoryMax=1600M`, nice 10, idle I/O). Boot + 02:30 daily, `Persistent=true`. |
| `receive-dashboard.sh` | LXC 250 | The **forced command** of the publishing key. It takes a tar on stdin, refuses links and any file type other than `.html`, `.json` and `.md`, and swaps the result into `/srv/evalgate/reports/athenaeum`, which evalgate's nginx already serves. That key can do nothing else. |

The code on LXC 104 is the synced working copy in `/root/athenaeum-poc` (the guest has no git), so the nightly evaluates whatever was last synced.

## Install on LXC 104 (done by Claude, 2026-09-27)

```sh
install -m 644 infra/nightly/athenaeum-nightly.service infra/nightly/athenaeum-nightly.timer /etc/systemd/system/
chmod 755 infra/nightly/athenaeum-nightly.sh
systemctl daemon-reload && systemctl enable --now athenaeum-nightly.timer
```

Enabling the timer on a guest that booted more than 15 minutes earlier starts a run at once, because `OnBootSec` has already passed. That happened on the first install; the run was stopped after 7 seconds and its directory removed. The daily time is 02:30 Pacific (the owner's time zone), not UTC, which is the container's clock.

The publishing key is `/root/.ssh/athenaeum_dashboard` (ed25519, no passphrase, comment `athenaeum-dashboard@lxc104`). LXC 250's host key is pinned in `/root/.ssh/known_hosts`; it was checked against the key already trusted for that host.

## One step for the owner: allow the key on LXC 250

Auto mode refuses to grant access to a host, so this is yours to run. From the Windows machine (Git Bash), in the repo:

```sh
scp -i ~/.ssh/evalgate_deploy infra/nightly/receive-dashboard.sh root@192.168.0.104:/tmp/athenaeum-receive-dashboard
ssh -i ~/.ssh/evalgate_deploy root@192.168.0.104 'set -e
id athenaeum-pub >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/athenaeum-pub --shell /bin/sh athenaeum-pub
install -m 755 -o root -g root /tmp/athenaeum-receive-dashboard /usr/local/bin/athenaeum-receive-dashboard && rm /tmp/athenaeum-receive-dashboard
install -d -o athenaeum-pub -g athenaeum-pub -m 755 /srv/evalgate/reports/athenaeum
install -d -o athenaeum-pub -g athenaeum-pub -m 700 /var/lib/athenaeum-pub/.ssh
echo "restrict,from=\"192.168.0.150\",command=\"/usr/local/bin/athenaeum-receive-dashboard\" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGtrTuXKLaG7hkyTLty94BjEVIFV1nOxMMGk5DiutJJ6 athenaeum-dashboard@lxc104" > /var/lib/athenaeum-pub/.ssh/authorized_keys
chown athenaeum-pub:athenaeum-pub /var/lib/athenaeum-pub/.ssh/authorized_keys
chmod 600 /var/lib/athenaeum-pub/.ssh/authorized_keys
echo ok'
```

What it grants: a new unprivileged user, `athenaeum-pub`, owning only `/srv/evalgate/reports/athenaeum`. Its one key works only from LXC 104's address (`from=`), gets no shell, forwarding or PTY (`restrict`), and runs only the receiver (`command=`). evalgate's index builder lists and prunes only directories named by date, so it never touches `athenaeum/`.

To check it afterwards, from LXC 104: `systemctl start athenaeum-nightly.service`, then `journalctl -u athenaeum-nightly -n 20`. The last line should read `published N files`.

To revoke it, on LXC 250: `userdel -r athenaeum-pub && rm -rf /srv/evalgate/reports/athenaeum /usr/local/bin/athenaeum-receive-dashboard`.
