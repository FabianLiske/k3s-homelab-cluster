# Jirafeau

Jirafeau is exposed through the public ingress at
`https://share.rohrbom.be`. Uploads require the shared upload password;
downloads only require the generated sharing URL (and an optional per-file
password).

## Local test

The DNS record can stay on the public ingress address while testing:

```bash
curl --resolve share.rohrbom.be:443:172.26.30.151 \
  -I https://share.rohrbom.be/
```

If the local resolver already returns `172.26.30.151`, open
`https://share.rohrbom.be` directly.

Check the rollout and certificate:

```bash
kubectl -n svc-jirafeau get deploy,pod,pvc,ingress,certificate
kubectl -n svc-jirafeau logs deploy/jirafeau
```

Read the generated passwords locally:

```bash
export SOPS_AGE_KEY_FILE=./age.cluster.key
sops --decrypt apps/public/share.rohrbom.be/jirafeau-secret.yaml
```

The admin interface is available at `https://share.rohrbom.be/admin.php`.

## Before public DNS cutover

Forward TCP ports 80 and 443 to `172.26.30.151`, then change the DNS record
to the public IP. If Cloudflare DDNS should maintain the record afterward,
add `share.rohrbom.be` to `DOMAINS` in
`infrastructure/controllers/cloudflare-ddns/deployment.yaml`.

The deployment currently allows files up to 20 GiB and provisions a 100 GiB
Longhorn volume with daily backups. Sharing links use 32-character random
references.
