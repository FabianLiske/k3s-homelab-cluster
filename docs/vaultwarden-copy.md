# Vaultwarden-Files aus Docker Volume in Longhorn PVC übertragen

```bash
# Vaultwarden Deployment runterskalieren
kubectl -n svc-vaultwarden scale deploy/vaultwarden --replicas=0
kubectl -n svc-vaultwarden wait --for=delete pod -l app=vaultwarden --timeout=120s
# Hängenden Loader löschen und neu starten
kubectl -n svc-vaultwarden delete pod vw-loader --force --grace-period=0
kubectl -n svc-vaultwarden apply -f vault.rohrbom.be/vw-loader.yaml
kubectl -n svc-vaultwarden wait --for=condition=Ready pod/vw-loader --timeout=120s
# Daten ziehen
mkdir -p ~/migrate/vaultwarden-data
scp -r root@192.168.30.3:/root/public-stack/vaultwarden/data/* ~/migrate/vaultwarden-data/
# Daten pushen
tar -C ~/migrate/vaultwarden-data -cf - . \
| kubectl -n svc-vaultwarden exec -i vw-loader -- tar -C /data -xf -
# Rechte anpassen
kubectl -n svc-vaultwarden exec vw-loader -- sh -lc 'chown -R 1000:1000 /data'
# Vaultwarden neu starten
kubectl -n svc-vaultwarden rollout restart deploy/vaultwarden
# Checks
kubectl -n svc-vaultwarden get pods -o wide
kubectl -n svc-vaultwarden logs deploy/vaultwarden --tail=200
kubectl -n svc-vaultwarden get ingress
# Loader entfernen
kubectl -n svc-vaultwarden delete pod vw-loader
```