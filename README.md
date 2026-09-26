# vda-report

Schedule VDA working papers, built from on-chain evidence.

One rule governs the whole codebase: **a figure that cannot be traced back to
a transaction hash is not a figure, it is a guess.** Where the engine cannot
value something, it says so on the report instead of substituting a zero.

~~~bash
python3 -m vdareport --fixture fixtures/taxpayer_a.json --csv out/schedule_vda.csv
python3 -m pytest -v
~~~

No dependencies outside the standard library. `pytest` only for the tests.

---

## The problem

From **1 April 2027**, under the OECD's Crypto-Asset Reporting Framework,
India's tax department begins receiving data on residents' foreign exchange
accounts and self-custody wallets.

The person that exposes has a harder filing problem than a domestic trader.
They owe **Schedule VDA** (per-transaction, in rupees), **Schedule FA**
(foreign assets), and a foreign tax credit calculation. Getting Schedule FA
wrong carries penalties up to Rs 10 lakh and prosecution exposure.

Existing tools are built around Indian exchange APIs — CoinDCX, ZebPay,
WazirX. They cannot serve someone whose history lives on a foreign venue and
a wallet they hold the keys to. Today that person's only option is a manual
engagement with an accountant.

This reads the chain instead.

---

## Three things it gets right that are easy to get wrong

**1. Moving tokens between your own wallets is not a sale.**

On-chain, sending 1.5 ETH from your wallet to your other wallet looks exactly
like selling it to a stranger. A tool that misses the distinction invents a
taxable event that never happened.

The fix is a modelling decision rather than a heuristic: **the unit of
assessment is the taxpayer, not the address.** All of a person's wallets are
pooled into one ledger, so an internal movement rearranges nothing and
realises nothing. It falls out by construction — not detected, just
impossible to miscount.

**2. Losses do not reduce gains.**

Section 115BBH allows no set-off of losses against gains and no
carry-forward. Each gain is taxed at 30% on its own.

Generic crypto tax tools net them, because that is what almost every other
country does. For India it understates the liability, and the taxpayer finds
out when the notice arrives. The report states gains and losses separately
and taxes only the gains.

**3. An unpriceable asset is refused, not zeroed.**

If there is no recorded price for a token at the moment it moved, the engine
will not value it. It goes on a list of gaps with the transaction hash and a
written reason.

A report with a visible hole can be finished by hand. A report whose holes
have been quietly filled looks finished and cannot be defended.

---

## What it produces

~~~
  3. 1000 USDT
     acquired  2026-09-01   cost  Rs 84,200.00
     disposed  2026-11-10   for   Rs 81,340.00
     loss      Rs 2,860.00
     acquisition tx  0x1a01c0ffee000000...
     disposal tx     0x1a01c0ffee000000...

  Gains                           Rs 193,625.00
  Losses (NOT deductible)         Rs 2,860.00
  Taxable income                  Rs 193,625.00
  Tax at 30%                      Rs 58,087.50
  Health & education cess 4%      Rs 2,323.50
  Total payable                   Rs 60,411.00
~~~

Plus a CSV in Schedule VDA's own columns, where the last two hold the
acquisition and disposal transaction hashes — so any figure can be checked
against the chain by whoever is reading it.

---

## How it is put together

| Module | Does |
| --- | --- |
| `models.py` | The vocabulary. Money is `Decimal`, never `float`. Timestamps carry a timezone. |
| `sources/etherscan.py` | The only module that touches the network. |
| `sources/fixture.py` | A recorded history, so the engine is testable offline. |
| `classify.py` | Acquisition, disposal, or internal movement. |
| `prices.py` | USD price x USD/INR at the transaction date — or a refusal with a reason. |
| `fifo.py` | Lot matching, oldest first, one row per matched parcel. |
| `report.py` | s.115BBH, financial-year filtering, Schedule FA peak balance, rendering. |

The network lives behind one module on purpose. Swapping Etherscan for a
direct node, Blockscout, or another chain touches that file and nothing
else — and the engine can be tested with no network at all.

**Pure arithmetic.** No model, no randomness, no clock. The same history
always produces the same report, which is the property you need when somebody
asks you to justify a figure eight months later. There is a test for it.

**The financial year runs on Indian time.** 1 April to 31 March, IST. A
disposal at 23:00 UTC on 31 March has already become 1 April in India and
belongs to the next year. Every timestamp carries a timezone so that
comparison can be made correctly.

---

## Running it against a real wallet

Put an Etherscan API key in `.env` in the project root:

~~~
ETHERSCAN_API_KEY=your_key_here
~~~

Then:

~~~bash
python3 -m vdareport \
  --wallet 0xYourFirstWallet \
  --wallet 0xYourSecondWallet \
  --fy 2026-27
~~~

Without `--prices` it still classifies the history and lists the internal
movements it found — which is the part that is hard and needs no price data.
Supply `--prices` for the rupee figures.

The exit code carries information: `0` for a complete report, `1` when
anything went unvalued, `2` when the chain could not be read.

`.env` is gitignored, and was gitignored before this repo had anywhere to
push to.

---

## What is deliberately not built yet

Named rather than hidden, because each one is a real decision and not an
oversight:

- **ERC-20 tokens.** `txlist` returns ETH movements only. Tokens live on the
  `tokentx` endpoint. Next substantial piece of work.
- **Chains other than Ethereum.** `--chain-id` is plumbed through; the other
  chains need testing, not new code.
- **Unsolicited inbound dust.** Pointing the tool at a real wallet turned up
  33 micro-transfers nobody asked for. It currently records them as
  acquisitions, which is the right mechanical answer and probably the wrong
  tax one — but a de minimis threshold I invent is a threshold I would have
  to defend. Open question, flagged rather than guessed.
- **Airdrops, staking rewards, mining.** Their treatment under s.115BBH is
  genuinely unsettled, and guessing would be worse than declining.
- **Gas fee deductibility.** s.115BBH allows only the cost of acquisition.
  Whether gas forms part of it is contested; fees are visible in the source
  data and excluded from the computation until that is resolved.
- **Intraday pricing.** Valuation is at date resolution. A day-traded
  portfolio would need the timestamp.
- **Surcharge.** Depends on the taxpayer's income outside the VDA.
- **1% TDS reconciliation** against Form 26AS / AIS.
- **A true Schedule FA peak.** The peak balance is sampled on transaction
  dates only, so it is reported as a floor with that caveat attached.

---

## The tests are the argument

~~~
test_moving_tokens_between_your_own_wallets_is_not_a_sale
test_the_same_movement_seen_from_both_wallets_is_not_double_counted
test_a_disposal_spanning_two_lots_produces_a_row_for_each
test_the_arithmetic_is_right_to_the_paisa
test_the_rows_sum_back_to_the_consideration_received
test_a_split_that_does_not_divide_evenly_still_reconciles
test_losses_do_not_reduce_gains
test_the_loss_is_recorded_even_though_it_is_not_deductible
test_tax_and_cess
test_the_financial_year_runs_on_indian_time
test_disposals_outside_the_year_are_excluded_but_still_shape_the_basis
test_every_reported_row_names_the_transactions_it_came_from
test_the_csv_carries_the_hashes_through_to_the_filing
test_an_asset_with_no_price_is_refused_not_zeroed
test_selling_more_than_the_history_accounts_for_is_flagged
test_both_kinds_of_missing_data_are_distinguishable
test_a_reverted_transaction_is_not_a_disposal
test_wei_converts_to_ether_exactly
test_the_same_history_always_produces_the_same_report
test_money_never_touches_a_float
test_rounding_is_half_up_not_half_even
~~~

Anyone can emit a plausible-looking tax table. The question is whether the
arithmetic survives the cases that actually arise, and each test above is one
of those cases written down.

---

*Working software, not tax advice. It computes what happened; it never
suggests what to do next.*
