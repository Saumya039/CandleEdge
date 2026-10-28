# Compliance release gate

`CLAUDE.md` makes a compliance review a release gate. **It has not been done.** This file lists what must be reviewed by
a qualified person against current rules before real-money use, redistribution, or any move beyond personal paper trading.

- **Order placement**: the app has none. Adding it (or any automation) needs a separate requirement and a review of
  current SEBI/NSE rules on algorithmic trading, broker API terms, static-IP/registration requirements, and audit duties.
- **Market-data licensing**: Kite Connect data is licensed for the subscriber; check terms before sharing screens,
  redistributing data, or running this as a service for others.
- **Advice**: signals are educational decision support. Providing them to others may implicate investment-adviser or
  research-analyst regulation.
- **Disclosures shown in the UI**: estimated costs, simulated fills, setup score is not a probability, derivatives risk.
- **Data**: journal data stays local; broker secrets are backend-only environment variables.
- **Calendar**: verify holidays and special sessions against official NSE circulars.
