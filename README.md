# Konverge

## Pre-requisites

### Install `kubectl` CLI

```Bash
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -y "deb http://apt.kubernetes.io/ kubernetes-xenial main"
sudo apt-get install -y kubectl

# Enable kubectl bash completion
echo "source <(kubectl completion bash)" >> "${HOME}"/.bashrc
```

## Installation

```Bash
# Upgrade pip to version ==20.0.2
pip install --upgrade pip
pip install -e git+https://github.com/dreamPathsProjekt/konverge#egg=konverge
```