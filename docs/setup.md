# 1) Für alle Nodes

## 1.1) Init

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y kitty-terminfo
sudo timedatectl set-timezone Europe/Berlin
```

## 1.2) Swap deaktivieren

```bash
sudo swapoff -a
sudo sed -i 's/^\([^#].*swap\)/#\1/' /etc/fstab
```

## 1.3) K8s Module & Sysctls

```bash
echo -e "overlay\nbr_netfilter" | sudo tee /etc/modules-load.d/k8s.conf
sudo modprobe overlay && sudo modprobe br_netfilter
```

```bash
sudo nano /etc/sysctl.d/100-multivlan.conf
```

```yaml
net.bridge.bridge-nf-call-iptables=1
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1

net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
```

```bash
sudo nano /etc/netplan/90-net.yaml
```

Hinzufügen:

```yaml
network:
  version: 2
  renderer: networkd

  ethernets:
    eth0:
      dhcp4: true
      dhcp6: false
      optional: true
      dhcp4-overrides:
        use-dns: false
      nameservers:
        addresses: [1.1.1.1, 1.0.0.1]
        search: []

  vlans:
    vlan10:
      id: 10
      link: eth0
      dhcp4: true
      dhcp6: false
      dhcp4-overrides:
        use-dns: false
        use-routes: false
      nameservers:
        addresses: [1.1.1.1, 1.0.0.1]
        search: []
      routes:
        - to: default
          via: 172.26.10.1
          table: 10
      routing-policy:
        - from: 172.26.10.0/24
          table: 10

    vlan20:
      id: 20
      link: eth0
      dhcp4: true
      dhcp6: false
      dhcp4-overrides:
        use-dns: false
        use-routes: false
      nameservers:
        addresses: [1.1.1.1, 1.0.0.1]
        search: []
      routes:
        - to: default
          via: 172.26.20.1
          table: 20
      routing-policy:
        - from: 172.26.20.0/24
          table: 20

    vlan30:
      id: 30
      link: eth0
      dhcp4: true
      dhcp6: false
      dhcp4-overrides:
        use-dns: false
        use-routes: false
      nameservers:
        addresses: [1.1.1.1, 1.0.0.1]
        search: []
      routes:
        - to: default
          via: 172.26.30.1
          table: 30
      routing-policy:
        - from: 172.26.30.0/24
          table: 30
```

```bash
sudo chmod 600 /etc/netplan/90-net.yaml
sudo sysctl --system
sudo netplan try
sudo netplan apply
ip -br link | egrep '^vlan(10|20|30)\b'   # sollten UP sein
```

## 1.4) Longhorn Vorbereitung

```bash
sudo apt install -y open-iscsi nfs-common smartmontools
sudo systemctl enable --now iscsid
```

---

# 2) Control Plane Nodes

## 2.1) K3s auf cp-1

```bash
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="server \
    --cluster-init \
    --node-ip=172.26.100.11 \
    --disable traefik \
    --disable servicelb \
    --tls-san 172.26.100.100 \
    --tls-san api.cluster.rohrbom.be" \
  sh -

sudo cat /var/lib/rancher/k3s/server/node-token
```

## 2.2) Alle weiteren Control Plane Nodes

```bash
curl -sfL https://get.k3s.io | \
  K3S_TOKEN="<TOKEN>" \
  INSTALL_K3S_EXEC="server \
    --server https://172.26.100.11:6443 \
    --node-ip=172.26.100.1X \
    --disable traefik \
    --disable servicelb \
    --tls-san 172.26.100.100 \
    --tls-san api.cluster.rohrbom.be" \
  sh -
```

---

# 3) KubeVIP für externen Zugriff auf Cluster

## 3.1) DNS für API

api.cluster.rohrbom.be -> 172.26.100.100 in Cloudflare ohne Proxy

## 3.2) KubeVIP über cp-1 auf Cluster bringen

Auf PC:
```bash
scp kube-vip.yaml faba@172.26.100.11:~/
```

auf cp-1:
```bash
sudo kubectl apply -f kube-vip.yaml
```

---

# 4) Vorbereitung auf Admin-PC

## 4.1) Installation

```bash
sudo pacman -S kubectl
yay -S helm
```

## 4.2) Kubeconfig holen & auf VIP/FQDN umstellen

Auf CP-1:
```bash
sudo cat /etc/rancher/k3s/k3s.yaml > ~/k3s.yaml
chmod 600 ~/k3s.yaml
```

Auf PC
```bash
scp faba@172.26.100.11:~/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config
# VIP/FQDN eintragen (eine von beiden Varianten):
# sed -i 's#server: https://.*:6443#server: https://172.26.100.100:6443#' ~/.kube/config
sed -i 's#server: https://.*:6443#server: https://api.cluster.rohrbom.be:6443#' ~/.kube/config
kubectl get nodes
```

---

# 5) Worker dem Cluster joinen

## 5.1) Token von `cp-1` holen:

```bash
# auf cp-1:
sudo cat /var/lib/rancher/k3s/server/node-token
```

## 5.2) Auf **jedem Worker** (Token einsetzen):

```bash
curl -sfL https://get.k3s.io | \
  K3S_TOKEN="<TOKEN>" \
  INSTALL_K3S_EXEC="agent \
    --server https://172.26.100.100:6443 \
    --node-ip=172.26.100.2X" \
  sh -
```

Check:

```bash
kubectl get nodes -o wide
```

---

# 6) Longhorn installieren (ab hier wieder alles auf Admin-PC)

## 6.1) Control Plane tainten

```bash
kubectl taint nodes cp-X node-role.kubernetes.io/control-plane=:NoSchedule --overwrite
```

## 6.2) Worker tainten

```bash
kubectl label nodes wk-X node-role.kubernetes.io/worker= longhorn=storage --overwrite
```

# SOPS

Secret auf Cluster:

```bash
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey=./age.cluster.key
```

Decryption Spec:

```bash
kubectl edit kustomization flux-system -n flux-system
```

```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```
