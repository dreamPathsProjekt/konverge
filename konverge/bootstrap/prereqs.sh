#!/usr/bin/env bash

if [[ -z "${DAEMON_JSON_LOCATION}" ]]; then
    DAEMON_JSON_LOCATION=/opt/kube/bootstrap
fi

if [[ -z "${KUBE_VERSION}" ]]; then
    KUBE_VERSION=1.16.3-00
fi

if [[ -z "${DOCKER_VERSION}" ]]; then
    DOCKER_VERSION=18.09.7-0ubuntu1~18.04.4
fi

# Assuming swap is off
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -y "deb http://apt.kubernetes.io/ kubernetes-xenial main"

# Install required packages
sudo apt-get install -y docker.io=${DOCKER_VERSION}
# Mark packages on hold - upgrade k8s through k8s & not apt
sudo apt-mark hold docker.io

sudo cp "${DAEMON_JSON_LOCATION}/daemon.json" /etc/docker

# Apply new dockerd settings with cgroupdriver=systemd
sudo systemctl daemon-reload && \
sudo systemctl restart docker.service && \
sudo systemctl status docker.service

sudo apt-get install -y kubelet=${KUBE_VERSION} kubeadm=${KUBE_VERSION} kubectl=${KUBE_VERSION}
sudo apt-mark hold kubelet kubeadm kubectl

sudo systemctl status kubelet.service

# Enable start on-boot
sudo systemctl enable kubelet.service
sudo systemctl enable docker.service
echo "source <(kubeadm completion bash)" >> "${HOME}"/.bashrc
echo "source <(kubectl completion bash)" >> "${HOME}"/.bashrc
