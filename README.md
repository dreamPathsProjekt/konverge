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
pip install -e git+git@github.com:dreamPathsProjekt/konverge.git#egg=konverge
```