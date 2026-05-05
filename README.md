FINscope is a full-stack financial intelligence platform demonstrating how modern tooling can deliver institutional-grade analysis at near-zero marginal cost.

The backend is a Python serverless API on Vercel that queries Finnhub in parallel, runs quantitative calculations (Altman Z-Score, Piotroski F-Score, RSI, MACD, SMA cross) server-side, then passes structured data to GPT-4o for synthesis.

The weekly email pipeline runs on Make.com: every Monday it reads user watchlists from Supabase, calls the API for each ticker, and sends a personalised executive sum
