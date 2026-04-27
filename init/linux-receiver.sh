#!/usr/bin/env bash

iface="enp1s0"
echo "initialized on $iface"

sudo ip addr flush dev "$iface"
sudo ip addr add 172.16.2.2/24 dev "$iface"
sudo ip link set "$iface" up
sudo ip route add 172.16.1.0/24 via 172.16.2.1
