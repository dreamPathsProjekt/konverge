#!/usr/bin/env bash

echo "=== kubeadm ==="
apt-cache madison kubeadm | grep "${KUBE_MAJOR_VERSION}"
echo "=== docker-ce ==="
apt-cache madison docker-ce | grep "${DOCKER_MAJOR_VERSION}"