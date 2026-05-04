#!/usr/bin/env bash

iface="enx3c18a0452cbc"
echo "initialized on $iface"

sudo ethtool -K "$iface" tso off gso off gro off

# Ubuntu (sender)
sudo ip addr flush dev "$iface"
sudo ip addr add 172.16.1.2/24 dev "$iface"
sudo ip link set "$iface" up
sudo ip route add default via 172.16.1.1

# enable BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# fair queue qdisc. qdisc typically does not expect pacing, but bbr needs it.
sudo sysctl -w net.core.default_qdisc=fq

# avoid cpu throttling
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
