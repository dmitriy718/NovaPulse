# Nova|Pulse by Horizon Services -- Client Documentation

**Version:** 5.0.0
**Last updated:** 2026-03-02

Welcome to Nova|Pulse -- your AI-powered cryptocurrency and stock trading platform, built and operated by Horizon Services.

Nova|Pulse monitors the crypto and stock markets around the clock, analyzes price action using twelve intelligent trading strategies across three exchanges (Kraken, Coinbase, and Alpaca), and executes trades on your behalf with institutional-grade risk management. The Horizon web platform at [horizonsvc.com](https://horizonsvc.com) provides a modern dashboard for monitoring performance, managing your account, and tracking achievements.

Whether you are an experienced trader looking to automate your approach or completely new to algorithmic trading, Nova|Pulse is designed to keep you informed, in control, and protected.

**What is new in v5.0:** Ten optional advanced intelligence features including macro event calendar, lead-lag intelligence, regime transition prediction, on-chain data integration, structural stop loss placement, liquidity-aware position sizing, anomaly detection circuit breaker, P&L attribution reporting, ensemble ML (TFLite + LightGBM), and Bayesian hyperparameter optimization. All default to off for safe upgrades. See the [Advanced Features guide](Advanced-Features.md) for details.

---

## Table of Contents

### Getting Started
| # | Guide | What It Covers |
|---|-------|---------------|
| 1 | [Getting Started](Getting-Started.md) | Account creation, plan selection, exchange setup, bot connection, first scan |

### NovaPulse Trading Bot
| # | Guide | What It Covers |
|---|-------|---------------|
| 2 | [Bot Dashboard Walkthrough](Nova-Dashboard-Walkthrough.md) | Every panel, metric, and button on the NovaPulse command center |
| 3 | [Controls: Pause, Resume, Kill](Controls-Pause-Resume-Kill.md) | How to control trading -- pause, resume, close all positions, emergency stop |
| 4 | [Understanding Metrics](Understanding-Metrics.md) | Plain-language explanations of every performance number you will see |
| 5 | [Trading Strategies](Trading-Strategies.md) | How the twelve AI strategies work and why confluence matters |
| 6 | [Risk and Safety](Risk-Safety.md) | Every layer of protection keeping your capital safe |
| 7 | [Smart Exit System](Smart-Exit-System.md) | Adaptive multi-tier exits, trailing stops, and time-based position management |
| 8 | [Multi-Exchange Trading](Multi-Exchange-Trading.md) | How Nova|Pulse trades across Kraken, Coinbase, and stock markets simultaneously |
| 9 | [Stock Trading](Stock-Trading.md) | Swing trading US equities with dynamic universe scanning |
| 10 | [AI and ML Features](AI-ML-Features.md) | How artificial intelligence and machine learning improve your trading |
| 11 | [Advanced Features (v5.0)](Advanced-Features.md) | Event calendar, lead-lag, regime prediction, structural stops, ensemble ML, and more |
| 12 | [Notifications (Telegram/Discord/Slack)](Notifications.md) | Setting up bot alerts and commands on your phone |
| 13 | [Configuration Guide](Configuration-Guide.md) | Adjusting settings, pairs, risk levels, and strategy parameters |

### Horizon Web Platform
| # | Guide | What It Covers |
|---|-------|---------------|
| 14 | [Horizon Dashboard](Horizon-Dashboard.md) | The horizonsvc.com web dashboard -- connecting your bot, live monitoring, gamification |
| 15 | [Horizon Trading Features](Horizon-Trading-Features.md) | Overview of the NovaPulse engine as presented on the Horizon platform |
| 16 | [Scanner and Signals](Horizon-Scanner-Signals.md) | Pro-only live trading signals scanner and public signal feed |
| 17 | [Gamification](Horizon-Gamification.md) | Achievements, milestones, ranks, levels, XP, win streaks |
| 18 | [Email Notifications](Horizon-Email-Notifications.md) | Email notification categories, preferences, scheduled reports, unsubscribe |

### Account and Billing
| # | Guide | What It Covers |
|---|-------|---------------|
| 19 | [Billing and Plans](Billing-Plans.md) | Subscription tiers, hosting options, Stripe billing, refund policy |
| 20 | [Security and Privacy](Security-Privacy.md) | How your account, data, and API keys are protected across both systems |

### Help and Support
| # | Guide | What It Covers |
|---|-------|---------------|
| 21 | [Troubleshooting](Troubleshooting.md) | Common issues with the bot, dashboard, billing, and email -- and how to fix them |
| 22 | [FAQ](FAQ.md) | Frequently asked questions |
| 23 | [Contact and Support](Contact-Support.md) | How to reach us, ticket system, response times, escalation |

---

## Quick Links

| Action | Where to Go |
|---|---|
| Sign up | [horizonsvc.com/signup](https://horizonsvc.com/signup) |
| Log in | [horizonsvc.com/auth](https://horizonsvc.com/auth) |
| Dashboard | [horizonsvc.com/dashboard](https://horizonsvc.com/dashboard) |
| Settings | [horizonsvc.com/settings](https://horizonsvc.com/settings) |
| Pricing | [horizonsvc.com/pricing](https://horizonsvc.com/pricing) |
| Support | [horizonsvc.com/support](https://horizonsvc.com/support) |
| Academy | [horizonsvc.com/academy](https://horizonsvc.com/academy) |

---

## How Nova|Pulse Works (In 60 Seconds)

1. **Market Data Flows In.** Nova|Pulse connects to your exchange via WebSocket and pulls live price, volume, and order book data for every pair you are trading.

2. **Twelve Strategies Analyze Every Bar.** Each strategy uses different technical analysis methods -- Keltner Channels, Bollinger Bands, VWAP, order flow, swing structure, funding rates, and more. No single strategy decides on its own.

3. **Confluence Voting.** The strategies vote. Only when multiple strategies agree on a direction (and pass minimum confidence thresholds) does Nova|Pulse consider a trade. This is the "sure fire" filter that prevents impulsive entries.

4. **Risk Checks.** Before any trade is placed, the risk manager validates position sizing, daily loss limits, correlation exposure, and available bankroll. If the risk is too high, the trade is rejected.

5. **Execution.** Approved trades are placed on your exchange using limit orders (with automatic fallback to market orders if the price moves). Stop loss and take profit levels are set immediately.

6. **Active Management.** Open positions are checked every two seconds. Trailing stops tighten, breakeven logic activates, and the smart exit system closes positions in tiers as profit targets are reached.

7. **Continuous Learning.** Nova|Pulse records every trade and uses that data to retrain its ML models, adjust strategy weights, and improve session-by-session.

---

## A Note on Safety

Nova|Pulse is built with safety as the top priority. Multiple layers of protection -- stop losses on every trade, daily loss limits, circuit breakers, exposure caps, correlation limits, and more -- work together to guard your capital. We strongly recommend starting in **paper trading mode** (simulated trades with no real money) to get comfortable with the system before going live.

Trading cryptocurrency and stocks involves risk. Past performance does not guarantee future results. Nova|Pulse is a tool that helps you trade more systematically, but no system can guarantee profits. Please read the [Risk and Safety](Risk-Safety.md) guide and the [FAQ](FAQ.md) for a clear-eyed discussion of risk.

---

## Version History

| Version | Date | Highlights |
|---------|------|-----------|
| v5.0.0 | 2026-02-25 | 10 advanced features, ensemble ML, Bayesian optimization, dashboard overhaul |
| v4.5.0 | 2026-02-24 | 3 new strategies (12 total), correlation sizing, cross-engine risk, adaptive exits |
| v4.1.0 | 2026-02-21 | Dynamic stock universe scanner, Kraken WS v2, session performance |
| v4.0.0 | 2026-02-19 | Strategy overhaul (5 new, 4 removed), multi-timeframe, smart exit system |
| v3.5.0 | 2026-02-18 | Profitability recovery, percentage-based SL/TP floors |
| v3.0.0 | 2026-02-14 | Initial public release with Docker deployment |

---

*Nova|Pulse v5.0.0 by Horizon Services -- Built for traders who value discipline, transparency, and control.*
