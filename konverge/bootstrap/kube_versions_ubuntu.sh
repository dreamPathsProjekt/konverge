#!/usr/bin/env bash

apt-cache madison kubeadm | grep "${KUBE_MAJOR_VERSION}"
apt-cache madison docker-ce | grep "${DOCKER_MAJOR_VERSION}"