# Gamification

Nova by Horizon includes a gamification system that makes monitoring your trading performance more engaging. As your bot trades, you earn XP, level up, unlock achievements, and climb the rank ladder.

---

## Overview

The gamification system is entirely client-side -- it computes your stats from your actual trading data. There is nothing to configure or enable; it works automatically as soon as your bot starts executing trades.

Gamification elements appear in two places:
1. **Dashboard** -- Overview tab shows your level, rank, XP bar, win streak, and recent achievements
2. **Settings** -- Profile section displays your rank badge and achievement count

---

## Levels

Your level is calculated from your total number of completed trades using the formula:

```
level = floor(sqrt(total_trades)) + 1
```

### Level Progression Examples

| Total Trades | Level |
|---|---|
| 0 | 1 |
| 1 | 2 |
| 4 | 3 |
| 9 | 4 |
| 16 | 5 |
| 25 | 6 |
| 36 | 7 |
| 49 | 8 |
| 64 | 9 |
| 81 | 10 |
| 100 | 11 |
| 225 | 16 |
| 400 | 21 |
| 625 | 26 |
| 900 | 31 |
| 1225 | 36 |

The square root function means early levels come quickly, but higher levels require progressively more trades. This keeps the progression rewarding both for new traders and experienced ones.

---

## XP (Experience Points)

XP is earned from trading activity:

```
XP = (total_trades * 10) + (wins * 25)
```

- Every completed trade earns 10 XP
- Every winning trade earns an additional 25 XP (35 XP total for a win)
- Losing trades still earn 10 XP

### XP Required for Next Level

The XP required to reach the next level is:

```
xp_for_level = level * level * 35
```

| Level | XP Required |
|---|---|
| 2 | 140 |
| 3 | 315 |
| 5 | 875 |
| 10 | 3,500 |
| 15 | 7,875 |
| 20 | 14,000 |
| 25 | 21,875 |
| 30 | 31,500 |
| 35 | 42,875 |

### XP Progress Bar

The dashboard displays a progress bar showing how close you are to the next level. The bar fills based on `current_xp / xp_for_next_level`.

---

## Ranks

Ranks are earned based on your current level. Each rank has a distinct badge, color scheme, and title.

| Rank | Min Level | Badge Icon | Color Theme |
|---|---|---|---|
| **Recruit** | 0 | Shield | Slate gray |
| **Bronze** | 2 | Award | Amber/bronze |
| **Silver** | 5 | Star | Light silver |
| **Gold** | 10 | Trophy | Golden amber |
| **Platinum** | 20 | Gem | Cyan blue |
| **Diamond** | 35 | Crown | Purple |

### Rank Display

Your rank badge appears:
- Next to your name in the dashboard header
- On the overview tab's gamification widget
- In the settings profile section
- With a colored background and border matching the rank theme

### Rank Progression

To reach each rank, you need approximately:
- **Recruit**: 0 trades (everyone starts here)
- **Bronze**: 1+ trades (Level 2)
- **Silver**: 16+ trades (Level 5)
- **Gold**: 81+ trades (Level 10)
- **Platinum**: 361+ trades (Level 20)
- **Diamond**: 1,156+ trades (Level 35)

---

## Achievements

There are 12 achievements that can be unlocked based on your trading performance. Each achievement has a unique icon, name, description, and unlock condition.

### Trade Volume Achievements

| Achievement | Name | Condition | Icon |
|---|---|---|---|
| first_trade | **First Blood** | Execute 1 trade | Crosshair |
| ten_trades | **Getting Warmed Up** | Complete 10 trades | Activity |
| fifty_trades | **Battle-Tested** | Complete 50 trades | Shield |
| hundred_trades | **Centurion** | Complete 100 trades | Crown |

### Win Streak Achievements

| Achievement | Name | Condition | Icon |
|---|---|---|---|
| streak_3 | **Hot Hand** | Win 3 consecutive trades | Flame |
| streak_5 | **On Fire** | Win 5 consecutive trades | Zap |
| streak_10 | **Untouchable** | Win 10 consecutive trades | Star |

### Win Rate Achievements

| Achievement | Name | Condition | Icon |
|---|---|---|---|
| win_rate_60 | **Sharp Shooter** | 60% win rate (min 10 trades) | Target |
| win_rate_70 | **Sniper** | 70% win rate (min 20 trades) | Eye |

Note: Win rate achievements require a minimum number of trades to prevent meaningless early unlocks (e.g., winning 1 out of 1 trade should not award "Sharp Shooter").

### Profit Achievements

| Achievement | Name | Condition | Icon |
|---|---|---|---|
| profit_100 | **First Bag** | $100+ total profit | DollarSign |
| profit_1k | **Comma Club** | $1,000+ total profit | Trophy |

### Strategy Achievements

| Achievement | Name | Condition | Icon |
|---|---|---|---|
| multi_strat | **Diversified** | Profit from 3+ different strategies | Layers |

### Achievement Display

Unlocked achievements appear in the dashboard with:
- The achievement icon in its designated color
- The achievement name in bold
- The description text
- A visual indicator (glow or checkmark) showing it is unlocked
- Locked achievements appear grayed out with their unlock conditions visible

---

## Win Streaks

The system tracks both your current and best (all-time) win streaks.

### How Streaks Are Calculated

1. Trades are sorted by exit time (newest first)
2. Starting from the most recent trade, consecutive profitable trades (P&L > 0) are counted
3. When a losing trade is encountered, the current streak count stops
4. For the best streak, the algorithm scans all trades from oldest to newest, tracking the longest run of consecutive wins

### Streak Display

The dashboard shows:
- **Current Streak**: How many consecutive wins from your most recent trade
- **Best Streak**: Your all-time longest winning streak
- A fire icon animation when on an active streak of 3+

---

## Gamification Data Source

All gamification data is computed client-side from the trade data returned by the bot proxy API. No gamification state is stored server-side -- it is recalculated each time the dashboard loads.

The context object used for achievement evaluation includes:
- `totalTrades`: Total number of completed trades
- `wins`: Number of winning trades
- `winRate`: Win percentage (0-100)
- `bestStreak`: Longest consecutive win streak
- `totalPnl`: Cumulative profit/loss in dollars
- `strategies`: Number of strategies with positive P&L
- `positions`: Number of currently open positions

---

## Milestone Email Notifications

When you unlock an achievement, a milestone notification email can be sent (if enabled in your notification preferences under Performance Reports > Milestone Achievements). The email includes:
- The achievement name and description
- Your current level and rank
- A congratulatory message
- A link to view your dashboard

---

*Last updated: March 2026*
