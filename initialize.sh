#!/usr/bin/env bash

source "$(dirname "$0")/ifaces.conf"

sender="$IFACE_REV"
receiver="$IFACE_FWD"

echo "sender: $sender / receiver: $receiver"

sudo ethtool -K "$sender" tso off gso off gro off
sudo ethtool -K "$receiver" tso off gso off gro off
sudo ip addr flush dev "$sender"
sudo ip addr flush dev "$receiver"

sudo ip addr add 172.16.1.1/24 dev "$sender"
sudo ip addr add 172.16.2.1/24 dev "$receiver"

sudo ip link set "$sender" up
sudo ip link set "$receiver" up

sudo sysctl -w net.ipv4.ip_forward=1
