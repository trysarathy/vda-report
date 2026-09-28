# Disclosure without liability

**What s.115BBH asks of sixty ordinary Ethereum wallets**

Aashmiin Kaur · Bachelor of Accountancy, Singapore Management University
28 September 2026

---

## The question

Section 115BBH taxes gains on virtual digital assets at 30% plus 4% cess,
allows no set-off of losses against gains, and no carry-forward. Schedule
VDA requires every disposal to be disclosed line by line, with its cost of
acquisition and its consideration.

The rate and the set-off rule are widely discussed. The disclosure
requirement is not. This study asks a narrower question, which turns out
to be answerable from the chain itself:

> When s.115BBH is applied to ordinary on-chain activity, who ends up
> owing tax, and who ends up filing?

## How the sample was drawn

Sixty addresses, drawn without being chosen.

Forty blocks were read at random from the last 20,000 on Ethereum mainnet
(latest block 26,076,685, seed 20260930). From each block, both ends were
taken of every transaction that carried value and no call data — a plain
ETH payment, whose sender and recipient are almost always ordinary wallets
rather than contracts. That produced 3,916 distinct addresses. Those
appearing in more than two of the forty blocks were dropped as exchanges,
routers or services rather than people, leaving 3,776, from which sixty
were drawn.

Nothing in the selection depends on what the wallets contain. The seed is
fixed, so the draw repeats exactly.

For each address the fifty most recent ETH movements were read — 958
movements in total, none unread. Each address was then assessed as its own
taxpayer for FY 2026-27, with prices from Coinbase's daily close and
USD/INR from the ECB's published reference rate, weekend dates taking the
preceding publication.

## What was measured

Two things, neither of which requires knowing *why* a transfer happened.
The chain does not record intent, so nothing here claims to know it.

1. **Where liability falls** — how the tax payable is distributed across
   the sixty wallets.
2. **Where the duty to disclose falls** — how many Schedule VDA rows each
   wallet must file, and how much money those rows carry.

## What was found

Of the sixty wallets, 35 had a Schedule VDA to file for FY 2026-27 and 25
had nothing to disclose. Between them the 35 produced **469 rows**,
carrying ₹1,71,63,245.45 of gains and ₹7,473.74 of losses.

### Liability is a point mass

| | |
|---|---|
| Largest single wallet | 98.1% of all liability |
| Largest five together | 100.0% |
| Median filer | ₹0.00 |

One address of sixty carried ₹52,50,534.83 of the ₹53,54,932.58 payable.
The median wallet with a return to file owed nothing at all.

A concentration this extreme in a sample of sixty is exactly the kind of
result that may not hold at larger n, and this study cannot establish that
it does. What it does establish is that a sample drawn without any
reference to wealth can be dominated by one address — which is a caution
about every aggregate figure computed over such a sample, including the
ones below.

### Nearly half of filers owe nothing

**15 of the 35 filers owe ₹0.00, and must still file 105 rows between
them — 22.4% of every row in the sample.**

This is a count across wallets, not a sum of money, so no single large
address can move it. It is the most robust finding here.

### Rows carrying almost no money are common, but not universal

Pooled across the sample:

| Rows carrying under | Rows | Share of rows | Gains carried | Share of gains |
|---|---|---|---|---|
| ₹1 | 88 | 18.8% | ₹0.03 | 0.0000% |
| ₹10 | 124 | 26.4% | ₹6.63 | 0.0000% |
| ₹100 | 178 | 38.0% | ₹56.07 | 0.0003% |

Eighty-eight separate disclosure obligations carry three paise between
them.

That pooled figure must be qualified, and the qualification matters.
Computed *within* each wallet and taken at the median, the share is
**0.0%** at all three thresholds: 14 of 35 wallets have any row under
₹100, and the remaining 21 have none. So this is not the experience of the
typical filer. It is the experience of a substantial minority — two in
five — who each carry a great many such rows.

Row counts are themselves uneven: the largest wallet files 49 rows (10.4%
of the sample's total), the median files 3.

## What was expected and did not appear

This study set out expecting to measure a second thing: the size of the
error made by tools that net losses against gains, as every jurisdiction
except India permits. An earlier single-wallet test had shown a liability
four times higher when computed correctly than when netted.

Across the sixty wallets the netting error was **₹1,682.58 on ₹53,54,932.58
— 0.03%.**

The reason is visible in the data. Under FIFO, disposals in 2026 are
matched against the oldest lots held, and acquisitions in this sample reach
back to 2017, when ETH traded at $434. Almost every disposal therefore
lands as a gain, and a sample with ₹17,163,245 of gains and ₹7,473 of
losses gives netting almost nothing to wrongly deduct.

The four-fold figure from the earlier test was a property of that wallet's
recent purchase history, not a general feature of the rule. It should not
be quoted as one.

## Limitations

- **The window.** Fifty movements per wallet, not full histories. 128
  disposals had no acquisition on record because it predates the window;
  14 of the 35 returns therefore carry at least one hole. Those holes are
  reported as holes and never filled with zeroes, but a full-history read
  would produce more rows and different totals.
- **Traffic weighting.** Addresses were drawn from block traffic, so a
  wallet that transacts often is likelier to appear than one that does not.
  This over-represents active holders.
- **Not an Indian sample.** Nothing identifies any address as held by an
  Indian resident. This measures how the rule *behaves* when applied to
  ordinary on-chain activity. It does not describe the Indian holder
  population, and no inference about that population should be drawn.
- **ETH only.** ERC-20 movements are not yet read, so token activity is
  invisible here.
- **n = 60.** Small.

## An open question

Many of the near-worthless rows arise from incoming transfers of trivial
value. Whether the holder asked for them cannot be determined from the
chain, and is not claimed here. But it raises a question the Act does not
appear to answer:

> What is the cost of acquisition of an asset that arrives unsolicited,
> that the holder cannot refuse, and that no consideration was given for?

If it is nil, the entire proceeds on disposal are gain, taxable at 30%,
disclosed line by line — and when the asset becomes worthless, the loss is
not deductible and cannot be carried forward.

This study does not answer that. It establishes that the question has a
population: rows exist, in quantity, attached to sums of a few paise.

## Reproducing this

    git clone https://github.com/trysarathy/vda-report
    cd vda-report
    echo "ETHERSCAN_API_KEY=your_key" > .env
    python3 study/sample.py      # draws the same sixty addresses
    python3 study/run.py         # reads them and computes the returns
    python3 study/inspect.py     # concentration and magnitude checks
    python3 study/robust.py      # the same findings, per wallet

The addresses, the block numbers, the seed, the price table and the
per-wallet results are all committed under `study/`. Every figure above
can be recomputed from them.

The engine itself is covered by 39 tests: `python3 -m pytest -v`.
