# SOPS

## Verschlüsseln

Secrets werden nicht direkt im Repo getrackt, die kommen mit Age verschlüsselt ins Repo und dann über SOPS auf den Cluster. Dazu auf PC oder Rancher VM mit
```bash
sops --encrypt --in-place apps/<ordner>/<secret>.yaml
```
verschlüsseln. Am besten nicht im Repo entschlüsseln, lieber das verschlüsselte Secret auf den Cluster bringen und im Racher UI den Inhalt checken.

## Entschlüsseln

Key mit

```bash
export SOPS_AGE_KEY_FILE=./age.cluster.key
```

laden und dann mit

```bash
sops --decrypt apps/<ordner>/<secret>.yaml > <secret>.yaml.example
```