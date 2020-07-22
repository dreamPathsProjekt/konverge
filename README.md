# Konverge

## Pre-requisites

### Access to Proxmox Cluster & environment variables

- You need to export credentials for a __Proxmox VE__ cluster

```Bash
# Syntax
export PROXMOX_HOST=<host-or-ip>:<port>
export PROXMOX_USER=<username>@pam or <username@pve>
export PROXMOX_PASSWORD=<password>

# Example
export PROXMOX_HOST=10.100.1.1:443
export PROXMOX_USER=myuser@pve
export PROXMOX_PASSWORD=myuserpass
```

- You will also need __superuser__ or `root` access to Proxmox __nodes__ via ssh & an appropriate `~/.ssh/config` entry

```Bash
# Example
Host node1.proxmox
HostName 10.100.1.1
User root
IdentityFile ~/.ssh/node1.pem
```

- Finally you will need to have, or generate a `.pem` RSA private/public keypair for access to VMs or `LXC` containers that will be created.

### Install `kubectl` CLI

```Bash
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -y "deb http://apt.kubernetes.io/ kubernetes-xenial main"
sudo apt-get install -y kubectl

# Enable kubectl bash completion
echo "source <(kubectl completion bash)" >> "${HOME}"/.bashrc
```

## Install `konverge`

```Bash
# Upgrade pip to version > 20.0.2
pip install --upgrade pip
# Install tag version
pip install -e git+https://github.com/dreamPathsProjekt/konverge@v0.8.1#egg=konverge
# Install from master
pip install -e git+https://github.com/dreamPathsProjekt/konverge#egg=konverge
```

## `konverge` Auto Completion

### Bash

```Bash
# Add this to ~/.bashrc
eval "$(_KONVERGE_COMPLETE=source_bash konverge)"
```

### ZSH

```Bash
# Add this to ~/.zshrc
eval "$(_KONVERGE_COMPLETE=source_zsh konverge)"
```

### Fish

```Bash
# Add this to ~/.config/fish/completions/konverge.fish
eval "$(env _KONVERGE_COMPLETE=source_fish konverge)"
```
