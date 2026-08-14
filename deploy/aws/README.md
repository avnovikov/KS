# KS UI — AWS Lightsail bootstrap (eu-west-1)

Idempotent-ish install for the Discord-auth heroes UI on Ubuntu Lightsail.

## On your Mac (before running this on the server)

1. Grant IAM user `aaaa137` **AmazonLightsailFullAccess** (see `IAM-PERMISSIONS.md`).
2. Create the instance (helper): `./deploy/aws/create-lightsail.sh`
3. Point Spaceship DNS: `www` **A** → instance public IP
4. Fill `deploy-secrets/ks-ui.env` (local only; never commit)
5. Copy secrets + run remote install:

```bash
./deploy/aws/push-and-install.sh <PUBLIC_IP>
```

## What the remote install does

- Installs Python 3.12+, Caddy
- Clones/updates KS repo under `/opt/ks`
- Creates `/var/lib/ks/users` data dir
- Installs systemd unit `ks-ui.service`
- Configures Caddy for `www.aaaa137.fun` with Let's Encrypt

Discord `guild_id` must still be set in `/opt/ks/config/auth.yaml` once the server admin sends it.
