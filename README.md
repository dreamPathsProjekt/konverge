# Konverge

## Installation

### Install `kubectl` CLI

```Bash
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -y "deb http://apt.kubernetes.io/ kubernetes-xenial main"
sudo apt-get install -y kubectl

# Enable kubectl bash completion
echo "source <(kubectl completion bash)" >> "${HOME}"/.bashrc
```

### Install `konverge` CLI

1. Clone this Repo

```Bash
git clone https://github.com/dreamPathsProjekt/konverge.git
cd konverge
```

2. Create & activate a Python 3.6.9 virtualenv - assumes python3 is version `3.6` and installed to your system

```Bash
sudo apt-get install python3-dev build-essential
python3 -m venv <some_virtualenv_directory>/
source <some_virtualenv_directory>/bin/activate
cd konverge
pip install --upgrade pip
pip install -r requirements.txt
```

1. Install `konverge` with virtualenv **activated**

```Bash
cd ncc-devops
pip install -e .
```
