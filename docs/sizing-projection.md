# Sizing Projection — How the Cheat Sheet Works

## The Core Question

> "Given my account size, win rate, and stop distance, how many contracts can I trade without blowing up?"

The Sizing Cheat Sheet answers this by working backwards from the **worst-case losing streak** you should statistically expect.

---

## Key Concepts

### 1. Expected Maximum Losing Streak

Even a profitable trader with a 50% win rate will hit long losing streaks over enough trades. The question is: *how long?*

The formula calculates the **maximum consecutive losses** you should expect over a horizon of N trades at a given confidence level:

```
streak = ceil( log((1 - confidence) / horizon) / log(lossRate) )
```

Where:
- **lossRate** = `1 - (winRate / 100)` — probability of losing any single trade
- **horizon** = `200` trades — the lookahead window (how many trades you're planning for)
- **confidence** = how sure you want to be that you can survive this streak (0.99, 0.95, or 0.80)

#### Derivation (intuition)

The probability of hitting a losing streak of length `k` somewhere within `N` trades is approximately:

```
P(streak >= k in N trades) ≈ N * lossRate^k
```

We want to find the `k` where this probability crosses our confidence threshold. Setting `N * lossRate^k = (1 - confidence)` and solving for `k`:

```
lossRate^k = (1 - confidence) / N
k = log((1 - confidence) / N) / log(lossRate)
```

We `ceil()` the result because you can't have a fractional loss.

#### Example

With a **50% win rate** over **200 trades**:

| Tier | Confidence | Meaning | Expected Max Streak |
|------|-----------|---------|-------------------|
| Conservative | 99% | "I want to survive 99% of scenarios" | 15 losses |
| Standard | 95% | "I want to survive 95% of scenarios" | 12 losses |
| Aggressive | 80% | "I'm OK with 20% chance of exceeding this" | 10 losses |

### 2. Dollars Per Point (DPP)

Each instrument has a fixed dollar value per point of price movement:

| Instrument | Dollars Per Point |
|-----------|------------------|
| MES (Micro E-mini S&P) | $5/point |
| ES (E-mini S&P) | $50/point |

### 3. Cost Per Contract at a Given Stop

```
costPerContract = stopPoints * dollarsPerPoint
```

Example: 20-point stop on MES = `20 * $5 = $100` per contract lost if stopped out.

### 4. Maximum Qty Per Tier

The key sizing formula:

```
qty = floor( accountSize / streak / costPerContract )
```

This ensures that even if you hit the worst-case losing streak for that tier, you won't lose more than your account size.

#### Walkthrough

- Account size: **$2,500**
- Win rate: **50%**
- Stop: **20 points** on **MES** ($100/contract)
- Conservative tier (99% confidence): expected max streak = **15 losses**

```
qty = floor( 2500 / 15 / 100 )
    = floor( 1.67 )
    = 1 contract
```

Meaning: trading 1 MES with a 20-point stop, you'd lose $100 per loss. Even 15 consecutive losses ($1,500) wouldn't wipe out the $2,500 account.

- Standard tier (95% confidence): streak = **12 losses**

```
qty = floor( 2500 / 12 / 100 )
    = floor( 2.08 )
    = 2 contracts
```

At 2 contracts, the max drawdown scenario (12 * 2 * $100 = $2,400) still fits within the account.

---

## Three Risk Tiers

| Tier | Confidence | Philosophy |
|------|-----------|-----------|
| **Conservative** (green dot) | 99% | Maximum protection. You'd only exceed this streak in 1 out of 100 scenarios of 200 trades. Best for new accounts, evaluation accounts, or capital preservation mode. |
| **Standard** (yellow dot) | 95% | Balanced risk. 5% chance of exceeding the expected streak. Good default for funded accounts with established edge. |
| **Aggressive** (red dot) | 80% | Higher risk tolerance. 20% chance of a longer streak. Only for accounts where you're comfortable with deeper drawdowns and have strong conviction in your edge. |

---

## Auto Win Rate

The cheat sheet can auto-detect your win rate:

1. Looks at all accounts with **60+ trades** (enough data to be meaningful)
2. Computes a **trade-weighted blended win rate** across those accounts
3. Falls back to **50%** if no account qualifies

```
totalWins = sum( (account.winRate / 100) * account.tradeCount ) for accounts with 60+ trades
totalTrades = sum( account.tradeCount ) for accounts with 60+ trades
blendedWinRate = round( (totalWins / totalTrades) * 100 )
```

---

## Inline Account Size Override

You can click the account size on any tile to temporarily override it for what-if analysis. This is useful for:

- Simulating "what if my account grows to $5,000?"
- Comparing sizing across different hypothetical account sizes
- Planning for account scaling

These overrides are **session-only** and don't persist to the database.

---

## Implementation Details

### File
`templates/simulation.html` — all logic is client-side JavaScript within the Jinja2 template.

### Data Flow
1. Server passes `summaries` (list of account objects with `id`, `name`, `account_size`, `color`, `trade_count`, `win_rate`) via Jinja2
2. JavaScript stores account sizes in a mutable `acctSizes` map (allows inline edits)
3. On any control change (instrument, win rate, stop), `recalcSizing()` rebuilds all tiles

### Controls
- **Instrument toggle**: MES or ES — changes the dollars-per-point used in all calculations
- **Win rate input**: number field (1-99%) — directly affects streak length
- **Stop slider**: 5-50 points in steps of 5 — affects cost per contract

### Constants
- `HORIZON = 200` — the number of future trades considered for streak calculation
- `INST_DPP = {MES: 5, ES: 50}` — dollars per point per instrument
