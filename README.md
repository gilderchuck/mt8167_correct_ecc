Single pass BCH error correction for raw NAND flash dumps taken on MT8167 SoCs


# Goal
Correct bit errors in NAND dumps with 4K pagesize pulled from Mediatek's MT8167 family of SoCs with hardware ECC engine.

(Actually tested on a flash dump of an MT8516B only. But it's quite likely that the whole family of SoCs based on the MT8167 use the same hardware ECC module.)

# Background
[NFI's nandtool](https://github.com/NetherlandsForensicInstitute/nandtool) has been an invaluable tool for guessing/prototyping the BCH parameters used.

For my goal it was a bit of overkill though as my entire flash dump used the same ECC parameters.

Also I found nandtool had a few drawbacks:
* Linux-only due to extensive use of FUSE
* it cannot be ran as part of a [unix pipeline](https://en.wikipedia.org/wiki/Pipeline_(Unix))
* it has multiple library dependencies whereas I only needed bchlib


# Requirements
bchlib:
```
$ pip install --user --break-system-packages bchlib
```
(better use venv though)

