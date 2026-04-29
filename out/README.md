# output data

Top-level data dirs are of the form

```
{experimentnumber}-{matrixsize}-{algo(s)}
```

The `01/` experiments vary the Cartesian product:

```
RTT_MS = [10, 100]
BW_MBIT = [25, 50, 100, 300, 500, 1000]
BUF_BYTES = [100_000, 2_000_000, 10_000_000, 50_000_000, 100_000_000]
LOSS_PCT = [0, 1, 2]
```

The `02/` experiments vary the Cartesian product:

```
RTT_MS = [100]
BW_MBIT = [500]
BUF_BYTES = [6250000 // 10, 6250000, 6250000 * 10]
LOSS_PCT = [0, 1, 2]
```

Within each experiment set dir, data dirs are of the form:

```
rtt{ms}_bw{Mbps}_loss{percentage}_buf{bytes}_bbr
```

(bbr is included in the dir title but isn't relevant -- this is for backwards compatibility, just ignore it)
