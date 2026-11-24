## What it does

vgacap's RTL capture framer (`mithro/vgacap` `rtl/vgacap_raw_framer`) fed
with the `tt_um_vgacal_bars` picture on every other clock. `uo_out` carries
vgacap chunk bytes (`RAW ` chunks of 256 samples, overrun `TIME` chunks) and
`uio[0]` is high on the clocks that carry one. A capture of uio+uo_out, kept
where `uio[0]` is set, is a vgacap stream whose samples are the bars picture.

## How to test

Capture `uio[0]` and `uo_out` together (16 bits), keep the bytes marked
valid, parse them as vgacap chunks: the samples must be the bars picture on
every other clock, with no `overrun` TIME chunk.
