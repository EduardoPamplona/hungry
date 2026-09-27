# Kubernetes homelab setup: what was done, why, and how it compares to AWS

A single-node Kubernetes cluster built with `kubeadm` on a spare machine, reachable over Tailscale. This document records every step, the reason for it, the problems hit along the way, and how each piece maps to a managed cloud offering such as AWS EKS.

## 1. Result

| Item | Value |
|---|---|
| Host | `homelab-ep`, Ubuntu 26.04, x86_64, 12 CPU, 15 GiB RAM, bare metal |
| Tailscale IP | `100.99.58.35` |
| LAN IP | `192.168.1.112` |
| Kubernetes | v1.34.12 (kubeadm, kubelet, kubectl) |
| Container runtime | containerd 2.2.2 |
| CNI (pod network) | Flannel v0.28.9, pod CIDR `10.244.0.0/16` |
| Topology | 1 node acting as control plane **and** worker |
| API server | `https://100.99.58.35:6443` |
| Client | `kubectl` v1.37.1 in `~/.local/bin`, config in `~/.kube/config` |

---

## 2. Background: what a Kubernetes cluster is made of

Every step below exists to bring up one of these parts.

**Control plane** (the brain):
- `kube-apiserver`: the only thing you and every other component talk to. A REST API.
- `etcd`: key-value database holding all cluster state. If etcd is lost, the cluster is lost.
- `kube-scheduler`: decides which node a new pod runs on.
- `kube-controller-manager`: runs control loops that push actual state toward desired state (for example "I want 2 replicas, only 1 exists, create another").

**Node components** (the muscle, on every machine that runs workloads):
- `kubelet`: agent that receives pod specs from the API server and makes the container runtime run them.
- Container runtime (containerd): actually pulls images and runs containers. Kubernetes talks to it through the CRI (Container Runtime Interface).
- `kube-proxy`: programs iptables/IPVS rules so a Service's virtual IP reaches the right pods.

**Add-ons** (needed for a usable cluster, but not part of the core):
- CNI plugin (Flannel here): gives each pod an IP and lets pods on different nodes talk.
- CoreDNS: in-cluster DNS, so `my-service.my-namespace.svc.cluster.local` resolves.

`kubeadm` is the official bootstrap tool. It generates certificates, writes the static-pod manifests for the control plane, starts etcd, and prints a join command for more nodes. It deliberately does **not** install the runtime, the CNI, ingress, storage, monitoring or a load balancer. That is why the steps below have several manual parts.

---

## 3. Step by step

### Step 0: Connect and inspect the machine

```bash
ssh root@100.99.58.35 'cat /etc/os-release; uname -m; nproc; free -h; df -h /; systemd-detect-virt'
```

**Why:** Package names, architecture (amd64 vs arm64), RAM and disk decide what will work. kubeadm needs at least 2 CPU and about 2 GiB RAM. `systemd-detect-virt` returned `none`, meaning bare metal, so there is no nested-virtualization concern.

**Note on access:** the first attempt used `ssh 100.99.58.35`, which tried the local username `duka`. Tailscale SSH refused because that user does not exist on the remote machine (`failed to look up local user "duka"`). Using `root@` worked. Working as root is convenient for learning but is not what you would do in production.

### Step 1: Disable swap

```bash
swapoff -a
sed -i '/swap/s/^/#/' /etc/fstab
```

**Why:**
- The kubelet historically refuses to start if swap is enabled. Kubernetes schedules pods based on declared memory requests and limits, and swap makes memory behavior unpredictable: a pod that exceeds its limit is slowed down instead of being killed cleanly. (Newer versions can tolerate swap with explicit configuration, but the default and simplest path is off.)
- `swapoff -a` turns it off now. Commenting the line in `/etc/fstab` keeps it off after a reboot. Verified afterward: `#/swap.img none swap sw 0 0`.

**Caveat:** the `sed` comments any line containing "swap". Fine here (one entry), but check `/etc/fstab` on other machines before running it.

### Step 2: Kernel modules and sysctl settings

```bash
cat <<EOF > /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

cat <<EOF > /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system
```

**Why each item:**
- `overlay`: kernel module for the overlayfs filesystem containerd uses to layer container images.
- `br_netfilter`: makes traffic crossing a Linux bridge visible to iptables. Pod traffic goes over bridges, and kube-proxy's Service rules are iptables rules, so without this Services would not work correctly.
- `bridge-nf-call-iptables/ip6tables = 1`: the sysctl that actually turns that behavior on.
- `ip_forward = 1`: lets the host route packets between interfaces. A node forwards packets between pods and the outside network, so this is mandatory.
- Files in `/etc/modules-load.d/` and `/etc/sysctl.d/` make these persist across reboots. The `modprobe` call applies them immediately.

### Step 3: Install containerd (the container runtime)

```bash
apt-get update
apt-get install -y containerd apt-transport-https ca-certificates curl gpg

mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd
```

**Why:**
- Kubernetes no longer includes a runtime. It needs any CRI-compatible one. containerd is the common default (Docker itself uses containerd underneath). The machine already had Docker installed, but the cluster does not use it. Docker's own containerd and this one are separate instances and do not conflict.
- `containerd config default` writes a full config file so there is something to edit.
- **`SystemdCgroup = true` matters.** Cgroups are how Linux limits and accounts CPU and memory per container. On a systemd host, systemd manages cgroups. If the kubelet uses the systemd cgroup driver and containerd uses `cgroupfs` (the default), two managers fight over the same resources and the node becomes unstable under load. Both must agree. Verified: `SystemdCgroup = true` in containerd, and `cgroupDriver: systemd` in `/var/lib/kubelet/config.yaml` (kubeadm's default).
- `ca-certificates`, `curl`, `gpg`, `apt-transport-https`: needed to fetch the Kubernetes apt repository securely.

### Step 4: Add the Kubernetes apt repository and install the tools

```bash
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.34/deb/Release.key \
  | gpg --batch --yes --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.34/deb/ /' \
  > /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
```

**Why:**
- Ubuntu's own repos do not carry current Kubernetes releases. The project runs `pkgs.k8s.io`, with **one repository per minor version** (here `v1.34`). Choosing the repo chooses the version line.
- `signed-by=` with a dearmored key means apt trusts this key only for this repo, not system-wide.
- Three packages: `kubeadm` (bootstraps the cluster), `kubelet` (the node agent, runs as a systemd service), `kubectl` (CLI client). `kubernetes-cni` (standard CNI plugin binaries) came along as a dependency.
- `apt-mark hold`: Kubernetes upgrades must be done deliberately, one minor version at a time, in a specific order (control plane first, then nodes). A routine `apt upgrade` silently bumping the kubelet would break that.

**Problem hit:** the first attempt failed with `gpg: cannot open '/dev/tty'` because there was no terminal in the SSH session, and `gpg` tried to prompt about overwriting a file. The fix was `--batch --yes`. The resulting keyring file was empty at first, which is why I checked its size afterward instead of assuming success.

### Step 5: Initialize the control plane

```bash
kubeadm init \
  --apiserver-advertise-address=100.99.58.35 \
  --apiserver-cert-extra-sans=100.99.58.35,192.168.1.112 \
  --pod-network-cidr=10.244.0.0/16 \
  --node-name=homelab-ep
```

**What kubeadm did:** ran preflight checks, generated a CA and component certificates in `/etc/kubernetes/pki`, wrote static-pod manifests for apiserver, controller-manager, scheduler and etcd into `/etc/kubernetes/manifests` (the kubelet starts anything it finds there), created RBAC rules, published bootstrap tokens, and installed CoreDNS and kube-proxy. It also added the taint `node-role.kubernetes.io/control-plane:NoSchedule` so ordinary pods stay off control-plane nodes.

**Why each flag:**
- `--apiserver-advertise-address=100.99.58.35`: which IP the API server announces and listens on. The machine has several (`192.168.1.112` LAN, `100.99.58.35` Tailscale, plus Docker bridges `172.17.0.1`, `172.18.0.1`). Without the flag, kubeadm picks the default-route interface (the LAN address), and this laptop could not reach it. Using the Tailscale IP means the cluster is reachable from any device on the tailnet.
- `--apiserver-cert-extra-sans=...`: the API server's TLS certificate is only valid for names/IPs listed in it. `kubectl` checks that the address you connect to appears there. Listing both IPs lets you connect via either.
- `--pod-network-cidr=10.244.0.0/16`: the IP range pods get. This must match the CNI configuration (Flannel defaults to `10.244.0.0/16`).
- `--node-name=homelab-ep`: a short stable node name instead of the hostname `homelab-ep-MS-7B86`.

**Important design decision, the CIDR:** Calico's default pod range is `192.168.0.0/16`. That would have **overlapped this machine's LAN (`192.168.1.0/24`)**, so pod traffic destined for the LAN would be routed to pods instead. Pod, Service and node ranges must not overlap. I chose Flannel with `10.244.0.0/16`, which overlaps nothing on this host (LAN `192.168.1.0/24`, Docker `172.17/16` and `172.18/16`, Tailscale `100.64.0.0/10`). The Service range kubeadm chose by default is `10.96.0.0/12`, also non-overlapping.

### Step 6: Configure kubectl on the node

```bash
mkdir -p $HOME/.kube
cp /etc/kubernetes/admin.conf $HOME/.kube/config
```

**Why:** `admin.conf` is the kubeconfig kubeadm generates. It contains the API address, the cluster CA and a client certificate with `cluster-admin` rights. `kubectl` looks in `~/.kube/config` by default.

### Step 7: Install a CNI plugin (Flannel)

```bash
kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml
```

**Why:** Until a CNI is installed, the node stays `NotReady` and CoreDNS stays `Pending`, because nothing can assign pod IPs. Kubernetes defines the networking model (every pod gets its own routable IP, and pods can reach each other without NAT) but does not implement it. A CNI plugin does. Flannel is the simplest: it runs a DaemonSet (one pod per node) and builds a VXLAN overlay network.

**Caveat:** this pulled the manifest from Flannel's `master` branch, which is **unpinned**: repeating the command later may install something different. For anything you want reproducible, download a tagged release manifest and keep it in version control. The image that came up was `ghcr.io/flannel-io/flannel:v0.28.9`.

### Step 8: Remove the control-plane taint

```bash
kubectl taint nodes homelab-ep node-role.kubernetes.io/control-plane:NoSchedule-
```

**Why:** A taint repels pods unless they carry a matching toleration. With only one node, leaving the taint means no normal workload can ever schedule. The trailing `-` removes it. On a multi-node or production cluster you would keep it and add separate worker nodes.

### Step 9: Bring the kubeconfig to this machine

```bash
scp root@100.99.58.35:/etc/kubernetes/admin.conf ~/.kube/config
sed -i 's#server: https://.*:6443#server: https://100.99.58.35:6443#' ~/.kube/config
chmod 600 ~/.kube/config
```

`kubectl` was installed into `~/.local/bin` because `sudo` needs a terminal here, and no root access was needed for a single binary.

**Why:** The server field is rewritten to the Tailscale address so this machine can reach the API. The certificate is valid for that IP because of `--apiserver-cert-extra-sans` in step 5. `chmod 600` because the file contains admin credentials.

**Version note:** local `kubectl` is v1.37.1, the cluster is v1.34.12. Kubernetes only supports `kubectl` within one minor version of the API server (older or newer). Three versions apart is outside the supported skew. It worked for the basics I tried, but you may see odd behavior. Fix: install `kubectl` 1.34 locally if it bites.

### Step 10: Smoke test

```bash
kubectl create deployment nginx-test --image=nginx --replicas=2
kubectl expose deployment nginx-test --port=80 --type=NodePort
curl http://100.99.58.35:<nodeport>/     # returned HTTP 200
kubectl delete deployment nginx-test; kubectl delete svc nginx-test
```

**What this proved:** the scheduler placed pods (Deployment controller and scheduler work), containerd pulled and ran the image, Flannel gave pods IPs (`10.244.0.4`, `10.244.0.5`), kube-proxy exposed the NodePort (`31076`), and the node is reachable over Tailscale.

---

## 4. Files and locations

**On the node:**
- `/etc/kubernetes/admin.conf`: admin kubeconfig (treat as a root password)
- `/etc/kubernetes/pki/`: cluster CA and component certificates
- `/etc/kubernetes/manifests/`: static-pod definitions for the control plane
- `/var/lib/kubelet/config.yaml`: kubelet configuration
- `/var/lib/etcd/`: the cluster's database (back this up if the data matters)
- `/etc/containerd/config.toml`: runtime configuration

**On this machine:**
- `/home/duka/workspace/k/`: project directory, holds everything for this project (this doc, `kubeconfig`, `.gitignore`, and any manifests or notes you add). Keep new files here.
- `/home/duka/workspace/k/kubeconfig`: copy of the admin kubeconfig (mode 600, git-ignored). Use it with `export KUBECONFIG=/home/duka/workspace/k/kubeconfig`.
- `~/.kube/config`: identical copy so plain `kubectl` works without setting `KUBECONFIG`.
- `~/.local/bin/kubectl`: the client binary.

---

## 5. How this compares to AWS (EKS)

Amazon EKS is the closest managed equivalent. The Kubernetes API you use is the same. What differs is who runs what.

### 5.1 Ownership: what you run vs. what AWS runs

| Component | This homelab (kubeadm) | AWS EKS |
|---|---|---|
| kube-apiserver, etcd, scheduler, controller-manager | You install, certificate-rotate, back up, upgrade, monitor | **AWS-managed** control plane, multi-AZ, hidden from you. You never SSH into it |
| Control-plane certificates | Generated by kubeadm, expire in 1 year unless renewed (`kubeadm certs renew`) | Handled by AWS |
| etcd backups | Yours (manual snapshots) | AWS |
| Worker nodes | The same machine | EC2 instances (managed node groups, self-managed, Karpenter) or serverless with Fargate |
| Container runtime | You install and configure containerd | Preinstalled in the EKS-optimized AMI (Amazon Linux / Bottlerocket) |
| OS patching and kernel settings (swap, sysctls, modules) | You (steps 1 and 2 here) | Handled by the AMI. Managed node groups can roll AMI updates |
| Kubernetes upgrades | You, manually, one minor version at a time | One API call or console click for the control plane, then rolling node updates |
| Cost | Electricity and the hardware you own | About $0.10/hour per cluster for the control plane, plus EC2/Fargate, load balancers, NAT gateways, data transfer |
| High availability | None (single node, single etcd) | Control plane across 3 AZs by default. You add nodes across AZs |

### 5.2 Feature-by-feature mapping

| Concern | Homelab | AWS |
|---|---|---|
| **Cluster creation** | `kubeadm init` and ten manual steps | `eksctl create cluster`, Terraform, or console: minutes, one declarative definition |
| **Authentication to the API** | Static client certificate in `admin.conf`, shared by anyone who has the file | AWS IAM. Users and roles map to Kubernetes RBAC through EKS access entries. Tokens are short-lived (`aws eks get-token`) and auditable in CloudTrail |
| **Pod networking (CNI)** | Flannel VXLAN overlay: pod IPs are virtual, encapsulated | **Amazon VPC CNI**: pods get real VPC IP addresses from your subnets, so security groups and VPC flow logs apply directly. Trade-off: you can exhaust subnet IPs (needs planning; prefix delegation helps) |
| **Pod CIDR planning** | Had to avoid overlap with the LAN by hand (step 5) | Pod IPs come from VPC subnets. You plan the VPC CIDR instead |
| **Services of type `LoadBalancer`** | Stays `<pending>` forever. There is no cloud to provision one. Options: NodePort (used here), or install MetalLB | Provisions an AWS NLB/ALB automatically (AWS Load Balancer Controller for ALB via Ingress) |
| **Ingress** | Install ingress-nginx yourself, exposed by NodePort or MetalLB | AWS Load Balancer Controller creates an ALB per Ingress |
| **Persistent storage** | Nothing by default. PVCs stay `Pending` until you add something like `local-path-provisioner` or Longhorn | EBS CSI driver: a PVC provisions an EBS volume (block, single-AZ). EFS CSI for shared file storage |
| **DNS** | CoreDNS in-cluster only. You reach services by NodePort and Tailscale IP | CoreDNS in-cluster, plus Route 53 (ExternalDNS can sync records) |
| **Node autoscaling** | None. One fixed machine | Cluster Autoscaler or Karpenter adds and removes EC2 nodes on demand |
| **Secrets** | Base64 in etcd, unencrypted at rest by default | Envelope encryption with KMS, optionally with AWS Secrets Manager integration |
| **Container images** | Public registries (Docker Hub rate limits apply) | ECR, private, IAM-authenticated, same network |
| **Pod-to-AWS-service permissions** | Not applicable | IRSA or EKS Pod Identity: a pod assumes an IAM role without long-lived keys |
| **Logging and metrics** | Nothing installed | CloudWatch Container Insights, or managed Prometheus and Grafana |
| **Network exposure** | Private by design (Tailscale only). Nothing is exposed to the internet | Endpoint can be public, private or both. Nodes normally sit in private subnets behind NAT |
| **Multi-node and failure domains** | One node: if it dies, everything stops | Nodes across AZs. Pods get rescheduled elsewhere |

### 5.3 What the homelab teaches that EKS hides

- How TLS trust in the cluster is built (CA, SANs). It is the reason `--apiserver-cert-extra-sans` was needed.
- What the kubelet, containerd and cgroups actually do, and why swap must be off.
- Why a CNI is a separate, pluggable piece, and what breaks without one.
- That `LoadBalancer` and `PersistentVolumeClaim` are contracts fulfilled by a cloud integration, not built-in magic.
- Why control-plane upgrades and certificate expiry are real operational work.

### 5.4 What EKS gives you that this cannot

Real high availability, IAM integration, elastic scaling, a load-balancer and storage backend that "just work", and no control plane to babysit. Almost everything in section 3 (steps 1 to 6) disappears; steps 7 to 9 become an add-on toggle and an `aws eks update-kubeconfig` command.

### 5.5 Skills that transfer directly

The workload API is identical: Deployments, Services, ConfigMaps, Secrets, Ingress, RBAC, resource requests and limits, probes, namespaces, Helm charts, `kubectl`. Manifests written here run on EKS with changes mostly limited to storage classes, ingress annotations and load-balancer annotations.

---

## 6. Caveats and security notes

- **SSH as root and a cluster-admin kubeconfig** are fine for a private tailnet lab. In production, use least-privilege users and per-user credentials.
- **`admin.conf` gives full control of the cluster.** Do not commit it or paste it anywhere.
- **Single node, single etcd:** no redundancy. Back up `/var/lib/etcd` (or use `etcdctl snapshot save`) if you build something you care about.
- **Control-plane certificates expire after 1 year.** Check with `kubeadm certs check-expiration` and renew with `kubeadm certs renew all`.
- **Join token** printed by `kubeadm init` expires in 24 hours. Mint a new one with `kubeadm token create --print-join-command`.
- **Flannel manifest unpinned** (see step 7).
- **kubectl version skew** (see step 9).
- **Version pinning:** the packages are held at 1.34. Upgrade on purpose, with `kubeadm upgrade plan`.

---

## 7. Useful commands for exploring

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl describe node homelab-ep          # capacity, taints, conditions
kubectl get events -A --sort-by=.lastTimestamp
kubectl -n kube-system get pods -o wide   # the control plane running as pods
kubectl api-resources                     # every object type the API serves
kubectl explain deployment.spec.strategy  # built-in schema docs

# on the node
crictl ps                                 # containers as containerd sees them
journalctl -u kubelet -f                  # kubelet logs
ls /etc/kubernetes/manifests              # static pods for the control plane
kubeadm certs check-expiration
```

## 8. Suggested next exercises

1. Deploy an app with a Deployment, Service and ConfigMap. Kill a pod and watch it come back.
2. Try a rolling update, then `kubectl rollout undo`.
3. Install `local-path-provisioner`, then create a PVC and mount it (the storage gap from 5.2).
4. Install MetalLB to make `LoadBalancer` services work, then `ingress-nginx` (the LB and ingress gaps).
5. Install `metrics-server`, set resource requests and limits, and try a HorizontalPodAutoscaler.
6. Add NetworkPolicies. Note that Flannel does **not** enforce them; Calico or Cilium would (a real difference from the VPC CNI plus network policy support on EKS).
7. Install Helm and deploy a chart.
8. Take an etcd snapshot, break something, restore.
9. Add a second machine with `kubeadm join`, then restore the control-plane taint.
10. Do a `kubeadm upgrade` from 1.34 to the next minor version.

## 9. Teardown

```bash
kubeadm reset -f                 # on the node: removes the cluster state
rm -rf /etc/cni/net.d ~/.kube    # leftovers kubeadm reset does not delete
```
