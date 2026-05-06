# patches

Apply these via `git am`.

## iproute2

1. `001-ss-output-TCP-BBRv3-diag-information.patch` ([source](https://github.com/google/bbr/blob/v3/gtests/net/tcp/bbr/nsperf/0001-ss-output-TCP-BBRv3-diag-information.patch))

This patch works with BBRv2 as well due to struct alignment in the upstream Google kernel source.
Make sure to set BBRv2 as a module (BBRv3 sets the default bbr module to BBRv3; BBRv2 keeps it as BBRv1).

## kernel-bbrv2

1. `001-fix-use-after-free.patch` ([source](https://github.com/torvalds/linux/commit/52a9dab6d892763b2a8334a568bd4e2c1a6fde66))
