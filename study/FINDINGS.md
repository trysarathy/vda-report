# Reading less of the chain makes the tax look smaller

**s.115BBH applied to sixty ordinary Ethereum wallets, twice**

Aashmiin Kaur · Bachelor of Accountancy, Singapore Management University
29 September 2026

---

## The question

Section 115BBH taxes gains on virtual digital assets at 30% plus 4% cess,
allows no set-off of losses against gains, and no carry-forward. Schedule
VDA requires every disposal to be disclosed line by line.

Every other major jurisdiction permits set-off, so every tool built for
one of them computes gains minus losses. This study asks what that costs,
and — after the first run came back saying it cost almost nothing — what
it takes to see the cost at all.

## How the sample was drawn

Sixty addresses, drawn without being chosen.

Forty blocks were read at random from the last 20,000 on Ethereum mainnet
(latest block 26,076,685, seed 20260930). From each block, both ends were
taken of every transaction carrying value and no call data — a plain ETH
payment, whose sender and recipient are almost always ordinary wallets
rather than contracts. That gave 3,916 distinct addresses; those appearing
in more than two of the forty blocks were dropped as exchanges or services
rather than people, leaving 3,776, from which sixty were drawn.

Nothing in the selection depends on what the wallets contain. The seed is
fixed, so the draw repeats exactly.

Each address was then assessed as its own taxpayer for FY 2026-27, with
prices from Coinbase's daily close and USD/INR from the ECB's published
reference rate, weekend dates taking the preceding publication.

## The design: the same sample, read twice

The sample was run through the engine twice, changing exactly one thing:
how much history was read.

- **50 movements** — the most recent fifty ETH movements per wallet.
- **Full history** — every movement, paginated, refusing rather than
  truncating if a wallet exceeds the walk.

Everything else is identical: same addresses, same seed, same price
source, same engine, same 39 tests. Any difference between the two runs is
attributable to the window and to nothing else.

## Finding 1: truncation is biased, and biased towards gains

|  | 50 movements | full history |
|---|---|---|
| Wallets filing | 35 | 36 |
| Schedule VDA rows | 469 | 3,491 |
| Gains | ₹17,163,245.45 | ₹17,355,681.90 |
| Losses | ₹7,473.74 | ₹17,040,030.31 |
| Tax payable | ₹5,354,932.58 | ₹5,414,972.75 |
| Understated by netting | ₹1,682.58 | ₹5,111,891.04 |
| — as a share of liability | **0.0%** | **94.4%** |

The gains barely moved. The losses moved by three orders of magnitude.

The mechanism is FIFO. When a window hides the recent, higher-priced
acquisitions, disposals get matched against whatever older and cheaper
lots remain visible — and an old cheap lot disposed of today produces a
gain. A truncated read does not lose rows at random. It loses the
loss-making ones preferentially, and reports a tidier, larger, wronger
number with no indication that anything is missing.

This matters beyond this sample. Etherscan caps a single response at
10,000 rows and says nothing when it truncates. Any tool that takes the
first page and stops will exhibit this bias. The engine used here had
exactly that defect ten days before this study was run.

Reading in full is not merely more complete. It changes the sign of what
you conclude.

## Finding 2: netting understates the liability for most wallets that owe anything

Across the 23 wallets with any liability at all, on full histories:

| | |
|---|---|
| Median wallet's liability, overstated by netting | **20.2%** |
| Wallets where netting changes it by more than 10% | 12 of 23 |
| Wallets where netting changes it by more than 50% | 8 of 23 |
| Wallets where netting reports zero and the Act does not | 4 |

The median is the load-bearing figure. It cannot be moved by one large
address, however large. With the single biggest wallet removed from the
sample entirely, the remaining 22 still show a netting error of 9.3% on
₹164,437.76 of liability.

The headline 94.4% above is not this finding. That figure is dominated by
one address and should not be quoted as a population statistic.

## Finding 3: what no set-off does to a trader

One wallet in the sample, drawn at random like the rest:

| | |
|---|---|
| Schedule VDA rows | 865 |
| Gains | ₹16,828,637.80 |
| Losses | ₹16,335,361.31 |
| Net economic profit | ₹493,276.49 |
| Tax payable under s.115BBH | ₹5,250,534.99 |

**The tax is 10.6 times the profit.**

This is one wallet. It is an illustration, not a statistic, and nothing
about how often this occurs can be inferred from a sample of sixty. What
it does show is the shape of the rule: a taxpayer who trades in volume
and comes out roughly flat is taxed on the gross gains as though the
losses never happened, because as far as s.115BBH is concerned they
did not.

## Finding 4: disclosure without liability

**13 of the 36 wallets with a return to file owe ₹0.00 — and must still
file 78 rows between them.**

A count across wallets, so no single address can move it. Adding the 24
wallets with nothing to disclose at all: of sixty addresses, one carries
97% of the liability, and a third of the filers owe nothing whatsoever.

Liability under s.115BBH is a point mass. The duty to disclose is not.

## Finding 5, qualified: rows carrying almost no money

Pooled across the full-history run:

| Rows carrying under | Rows | Share of rows | Gains carried |
|---|---|---|---|
| ₹1 | 1,574 | 45.1% | ₹0.19 |
| ₹10 | 1,779 | 51.0% | ₹8.76 |
| ₹100 | 2,079 | 59.6% | ₹226.82 |

1,574 separate disclosure obligations carry nineteen paise between them.

This one must be qualified, and the qualification matters. Computed
*within* each wallet and taken at the median, the share is **0.0%** at all
three thresholds: 13 of 36 wallets have any row under ₹100 and 23 have
none. So this is not the typical filer's experience. It is the experience
of roughly a third of them, who each carry a great many such rows.

## What changed between the two runs, and why it is reported

The first version of this study reported the netting error as 0.03% and
concluded that an earlier single-wallet result showing a four-fold gap had
been a property of that wallet rather than of the rule.

That conclusion was wrong, and wrong for an instructive reason: it was
measured on truncated histories, which had removed the losses. Reading in
full reversed it. Both runs are committed, and Finding 1 exists because
the first answer was wrong in a way that turned out to be worth measuring.

## Limitations

- **Traffic weighting.** Addresses were drawn from block traffic, so a
  wallet that transacts often is likelier to appear. This over-represents
  active holders — and active holders are precisely the population
  Findings 2 and 3 concern, so the effect flatters those findings.
- **Not an Indian sample.** Nothing identifies any address as held by an
  Indian resident. This measures how the rule behaves when applied to
  ordinary on-chain activity. It does not describe the Indian holder
  population and no inference about it should be drawn.
- **ETH only.** ERC-20 movements are not read, so token activity —
  including stablecoins, where much retail volume sits — is invisible.
- **Holes remain.** 238 disposals across 7 of the 36 returns still have no
  acquisition on record. Reading in full reduced the number of affected
  returns from 14 to 7 but increased the number of individual holes, which
  are now concentrated in the largest histories. Every hole is reported as
  a hole. None became a zero.
- **n = 60.** Small. One address carries 97% of the liability, which is
  itself a caution about every pooled figure here.

## An open question

Many of the near-worthless rows arise from incoming transfers of trivial
value. Whether the holder asked for them cannot be determined from the
chain and is not claimed here. But it raises a question the Act does not
appear to answer:

> What is the cost of acquisition of an asset that arrives unsolicited,
> that the holder cannot refuse, and for which no consideration was given?

If it is nil, the entire proceeds on disposal are gain, taxable at 30%,
disclosed line by line — and when the asset becomes worthless, the loss is
not deductible and cannot be carried forward.

This study does not answer that. It establishes that the question has a
population: 1,574 rows, carrying nineteen paise.

## Reproducing this

    git clone https://github.com/trysarathy/vda-report
    cd vda-report
    echo "ETHERSCAN_API_KEY=your_key" > .env

    python3 study/sample.py                     # draws the same sixty addresses
    python3 study/run.py                        # 50-movement windows
    python3 study/run.py full                   # full histories
    python3 study/examine.py results-full.json  # concentration and magnitude
    python3 study/robust.py  results-full.json  # the same findings, per wallet
    python3 study/compare.py                    # what the window cost

The addresses, block numbers, seed, both price tables and both sets of
per-wallet results are committed under `study/`. Every figure above can be
recomputed from them.

The engine is covered by 39 tests: `python3 -m pytest -v`.
