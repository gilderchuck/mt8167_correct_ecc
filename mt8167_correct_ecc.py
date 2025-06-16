#!/usr/bin/env python3

# For updates please check https://github.com/gilderchuck/mtk-nand-utils
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2025 Gilderchuck

import sys
import argparse
import bchlib

VERSION = "0.1"


# make command pipeline-friendly by printing all messages to stderr
# (logging module might be overkill)
def eprint(*args, **kwargs):
    kwargs['file'] = sys.stderr
    print(*args, **kwargs)


# chunk & ecc are mutable bytearrays, so make sure they return updated values
def ecc_correct_chunk(bch, chunk, ecc, return_ecc = False):
    flips = bch.decode(chunk, ecc)

    if flips > 0:
        bch.correct(chunk, ecc)

    # in case the ECC code itself had bit errors
    if return_ecc:
        ecc[:] = bch.encode(chunk)

    return flips


def main(argv):
    parser = argparse.ArgumentParser(
        description="Run BCH error correction on raw NAND flash dumps taken "
        "on MT8167-based SoCs. Outputs flash dump without OOB data. "
        "Supports page size 4096, OOB size 256 only.")
    parser.add_argument(
        "-o", "--output", dest="outfile",
        help="file to write ECC corrected pages into")
    parser.add_argument(
        "-c", "--chunks", type=int, default=4, dest="chunks",
        help="number of chunks (subpages) per page, defaults to 4")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="verbose output")
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="force completion even if encountering uncorrectable chunks")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument(
        "infile", nargs="?",
        help="raw NAND dump with OOB data")
    args = parser.parse_args()

    # tested on this combination only for now
    args.pagesize = 4096
    args.oobsize = 256

    if args.chunks == 4:
        bch = bchlib.BCH(t=32, prim_poly=17475, swap_bits=True)
    elif args.chunks == 8:
        bch = bchlib.BCH(t=12, prim_poly=8219, swap_bits=True)
    else:
        sys.exit("ERROR: number of chunks per page not supported")

    if args.verbose:
        eprint(f"INFO: BCH parameters: t={bch.t}, m={bch.m}, "
               f"n={bch.n}, prim_poly={bch.prim_poly}")

    raw_page_length = args.pagesize + args.oobsize
    if args.verbose:
        eprint(f"DEBUG: raw_page_length: {raw_page_length}")

    cooked_chunk_length = args.pagesize // args.chunks
    if args.verbose:
        eprint(f"DEBUG: cooked_chunk_length: {cooked_chunk_length}")

    ecclen = len(bch.encode(b"\xFF" * (cooked_chunk_length + 8)))
    if args.verbose:
        eprint(f"DEBUG: ECC bytes per chunk: {ecclen}")

    raw_chunk_length = cooked_chunk_length + 8 + ecclen
    if args.verbose:
        eprint(f"DEBUG: raw_chunk_length: {raw_chunk_length}")

    if args.oobsize < (ecclen + 8) * args.chunks:
        sys.exit(f"ERROR: selected ECC size ({ecclen}) "
                 f"would not fit into OOB size")

    # do not expect an input filename if part of a unix pipeline
    if args.infile is None and not sys.stdin.isatty():
        fi = sys.stdin.buffer
    elif args.infile is None:
        eprint(f"ERROR: no input file specified")
        parser.print_usage(file=sys.stderr)
        sys.exit(1)
    elif args.infile == "-":
        fi = sys.stdin.buffer
    else:
        try:
            fi = open(args.infile, "rb")
        except IOError as e:
            sys.exit(f"ERROR: unable to open input file ({e.errno}): "
                     f"{e.strerror}")

    # do not expect an output filename if part of a unix pipeline
    if args.outfile is None and not sys.stdout.isatty():
        fo = sys.stdout.buffer
    elif args.outfile is None:
        eprint(f"ERROR: no output file specified")
        parser.print_usage(file=sys.stderr)
        sys.exit(1)
    elif args.outfile == "-":
        fo = sys.stdout.buffer
    else:
        try:
            fo = open(args.outfile, "wb")
        except IOError as e:
            sys.exit(f"ERROR: unable to open output file ({e.errno}): "
                     f"{e.strerror}")

    erased_page = b"\xFF" * raw_page_length
    erased_spare = b"\xFF" * 8
    null_spare = b"\x00" * 8
    pagenum = 0
    flips_prev = 0
    flips_total = 0
    # page index of the first page which contains non-uniform pattern
    # in its spare space after ECC correction
    tainted_spare = -1

    while True:
        page = fi.read(raw_page_length)

        if len(page) != raw_page_length:
            break

        if page == erased_page:
            fo.write(page[:args.pagesize])
            if args.verbose:
                eprint(f"INFO: page: {pagenum} empty")

        else:
            flips_prev = flips_total
            flips = 0
            buffer = bytearray()
            uncorrectable = False

            # slice each page into chunks,
            # include 8 bytes of spare space,
            # run ECC correction on them individually
            for i in range(args.chunks):
                chunk = bytearray(page[
                        i * raw_chunk_length:
                        i * raw_chunk_length + cooked_chunk_length + 8])
                ecc = bytearray(page[
                        i * raw_chunk_length + cooked_chunk_length + 8:
                        (i + 1) * raw_chunk_length])

                flips = ecc_correct_chunk(bch, chunk, ecc)
                buffer += chunk[0:cooked_chunk_length]

                if flips == -1:
                    if not args.force:
                        sys.exit(f"ERROR: page {pagenum} chunk {i} "
                                 f"uncorrectable")
                    else:
                        uncorrectable = True
                else:
                    flips_total += flips
                    if (tainted_spare == -1 and chunk[-8:] != erased_spare
                            and chunk[-8:] != null_spare):
                        # eprint(" ".join(f"{b:02X}" for b in chunk[:8]))
                        tainted_spare = pagenum
            if uncorrectable:
                eprint(f"WARNING: page: {pagenum} uncorrectable, "
                       f"passing through corrupt data as requested")
            fo.write(buffer)
            if args.verbose:
                eprint(f"INFO: page: {pagenum} bitflips: "
                       f"{flips_total - flips_prev}")
        pagenum += 1

    fi.close()
    fo.close()

    # let the user know that the stripped OOB data potentially contained
    # old-style BBT and/or JFFS2 bad/erased block markers
    if tainted_spare != -1:
        eprint(f"WARNING: non-uniform data found in spare area for "
               f"page {tainted_spare}, potential OOB data might have been "
               f"lost during transformation")
    eprint(f"INFO: total pages: {pagenum}, corrected bitflips: {flips_total}")


if __name__ == "__main__":
    main(sys.argv)
