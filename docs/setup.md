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

net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.vlan10.rp_filter=0
net.ipv4.conf.vlan20.rp_filter=0
net.ipv4.conf.vlan30.rp_filter=0
net.ipv4.conf.eth0.rp_filter=0
```

```bash
sudo sysctl --system
```

## 1.4) Longhorn Vorbereitung

```bash
sudo apt install -y open-iscsi nfs-common smartmontools
sudo systemctl enable --now iscsid
```

## 1.5) VLAN Subinterfaces

```bash
sudo nano /etc/netplan/90-vlans.yaml
```

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
  vlans:
    vlan10:
      id: 10
      link: eth0
      addresses: []
    vlan20:
      id: 20
      link: eth0
      addresses: []
    vlan30:
      id: 30
      link: eth0
      addresses: []
```

Apply und Test:

```bash
sudo netplan apply
# Wie ein guter Hobby-Admin ignorieren wir die Warnung zu den File Permissions
ip -br link | egrep '^vlan(10|20|30)\b'   # sollten UP sein
```

---

# 2) Control Plane Nodes

## 2.1) K3s auf cp-1

```bash
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="server \
    --cluster-init \
    --disable traefik \
    --disable servicelb \
    --tls-san 192.168.100.100 \
    --tls-san api.cluster.rohrbom.be" \
  sh -

sudo cat /var/lib/rancher/k3s/server/node-token
```

## 2.2) Alle weiteren Control Plane Nodes

```bash
curl -sfL https://get.k3s.io | \
  K3S_TOKEN="<TOKEN>" \
  INSTALL_K3S_EXEC="server \
    --server https://192.168.100.11:6443 \
    --disable traefik \
    --disable servicelb \
    --tls-san 192.168.100.100 \
    --tls-san api.cluster.rohrbom.be" \
  sh -
```

---

# 3) KubeVIP für externen Zugriff auf Cluster

## 3.1) DNS für API

api.cluster.rohrbom.be -> 192.168.100.100 in Cloudflare ohne Proxy

## 3.2) KubeVIP über cp-1 auf Cluster bringen

Auf PC:
```bash
scp kube-vip.yaml faba@192.168.100.11:~/
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

```bash
scp faba@192.168.100.11:/etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config
# VIP/FQDN eintragen (eine von beiden Varianten):
# sed -i 's#server: https://.*:6443#server: https://192.168.100.100:6443#' ~/.kube/config
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
  INSTALL_K3S_EXEC="agent --server https://192.168.100.100:6443" \
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