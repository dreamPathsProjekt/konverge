#!/usr/bin/env bash

echo "=== kubeadm ==="
apt-cache madison kubeadm | grep "${KUBE_MAJOR_VERSION}"
echo ""

echo "=== kubelet ==="
apt-cache madison kubelet | grep "${KUBE_MAJOR_VERSION}"
echo ""

echo "=== kubectl ==="
apt-cache madison kubectl | grep "${KUBE_MAJOR_VERSION}"
echo ""

echo "=== docker.io ==="
apt-cache madison docker.io | grep "${DOCKER_MAJOR_VERSION}"
echo ""

echo "=== docker-ce ==="
apt-cache madison docker-ce | grep "${DOCKER_MAJOR_VERSION}"
echo ""